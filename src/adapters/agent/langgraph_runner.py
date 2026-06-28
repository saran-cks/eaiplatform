"""LangGraph Agent runner implementing AgentPort.

Uses StateGraph to execute a Map-Reduce parallel correlation query across logs,
code, and tickets. Communicates status and thoughts via an async queue back
to the EventSource HTTP stream.
"""

from __future__ import annotations

import asyncio
import logging
import operator
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Send

from config.settings import Settings
from core.domain.agent_control import AgentKillRegistry
from core.domain.entities.message import Message, Role
from core.domain.entities.session import AgentSession
from core.domain.policy.types import PolicyViolation, TrajectoryKill
from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.agent import AgentPort
from core.ports.llm import LLMPort
from core.ports.mcp_connector import MCPConnectorPort
from core.ports.observability import ObsAttr, ObservabilityPort, SpanKind

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _noop_span():
    """Fallback when no ObservabilityPort is injected (keeps tests obs-free)."""
    yield None


def _find_kill(exc: BaseException | None) -> TrajectoryKill | None:
    """Walk the cause/context chain for a TrajectoryKill (LangGraph may wrap it)."""
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, TrajectoryKill):
            return exc
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return None


# ---------------------------------------------------------------------------
# State Schemas
# ---------------------------------------------------------------------------
class WorkerResult(TypedDict):
    source: str  # "logs" | "code" | "tickets"
    content: str  # retrieved text, or error description
    success: bool  # False if the worker caught an exception


class AgentState(TypedDict):
    agent_session_id: str
    prompt: str
    sources_to_query: list[str]
    sub_agent_results: Annotated[list[WorkerResult], operator.add]
    final_synthesis: str
    iteration_count: int
    truncated: bool


# ---------------------------------------------------------------------------
# LangGraph Runner Implementation
# ---------------------------------------------------------------------------
class LangGraphRunner(AgentPort):
    """LangGraph-backed Agent execution engine implementing AgentPort."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMPort,
        peer_registry: Any = None,
        mcp: MCPConnectorPort | None = None,
        kill_registry: AgentKillRegistry | None = None,
        observability: ObservabilityPort | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._peer_registry = peer_registry
        # The PDP-guarded MCP connector (DD-8/DD-11). Workers fetch external data through it;
        # when absent (unit tests) workers fall back to simulated content.
        self._mcp = mcp
        self._kill_registry = kill_registry
        self._obs = observability

        # Interrupted sessions registry (cooperative cancellation)
        self._interrupted: set[str] = set()
        self._tasks: dict[str, asyncio.Task[Any]] = {}

        # Compile the graph
        self._graph = self._compile_graph()

    def _compile_graph(self) -> Any:
        builder = StateGraph(AgentState)

        # Add Nodes
        builder.add_node("planner", self._planner_node)
        builder.add_node("log_worker", self._log_worker_node)
        builder.add_node("code_worker", self._code_worker_node)
        builder.add_node("ticket_worker", self._ticket_worker_node)
        builder.add_node("synthesizer", self._synthesizer_node)

        # Build connections
        builder.add_edge(START, "planner")

        # Define conditional router from planner
        def _route_planner(state: AgentState) -> str | list[Send]:
            if state.get("truncated"):
                return "synthesizer"

            sends = []
            for src in state.get("sources_to_query", []):
                # Map source identifier to target node names
                node_map = {
                    "logs": "log_worker",
                    "code": "code_worker",
                    "tickets": "ticket_worker",
                }
                if src in node_map:
                    sends.append(
                        Send(
                            node_map[src],
                            {
                                "prompt": state["prompt"],
                                "agent_session_id": state["agent_session_id"],
                            },
                        )
                    )

            if not sends:
                return "synthesizer"
            return sends

        builder.add_conditional_edges(
            "planner",
            _route_planner,
            ["log_worker", "code_worker", "ticket_worker", "synthesizer"],
        )

        builder.add_edge("log_worker", "synthesizer")
        builder.add_edge("code_worker", "synthesizer")
        builder.add_edge("ticket_worker", "synthesizer")
        builder.add_edge("synthesizer", END)

        return builder.compile()

    # -----------------------------------------------------------------------
    # Node Functions
    # -----------------------------------------------------------------------
    def _check_interruption(self, state: AgentState) -> None:
        sid = state.get("agent_session_id")
        if sid and sid in self._interrupted:
            raise asyncio.CancelledError(f"Agent session {sid} was interrupted.")

    async def _fetch_via_mcp(
        self,
        *,
        config: RunnableConfig,
        sid: str,
        label: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> tuple[str, bool]:
        """Fetch external data through the PDP-guarded connector (DD-8/DD-11).

        Returns ``(content, success)``. A PDP denial degrades this one worker (success=False)
        without aborting the run; a ``TrajectoryKill`` is re-raised so it tears down the whole
        session — cumulative session risk is fatal to the agent, not to a single source.
        Falls back to simulated content when no connector/scope is wired (unit tests).
        """
        scope = config.get("configurable", {}).get("scope")
        if self._mcp is None or scope is None:
            return f"{label}: (simulated — MCP connector not wired)", True
        try:
            result = await self._mcp.call_tool(
                name=tool, arguments=arguments, scope=scope, session_id=sid
            )
            return f"{label}: {result.get('result', result)}", True
        except TrajectoryKill:
            raise  # never swallow — must propagate to reap the session (DD-11)
        except PolicyViolation as exc:
            return f"{label}: access denied by policy ({exc})", False
        except Exception as exc:  # transport/network failure — isolate to this worker
            return f"{label}: source unavailable ({exc})", False

    async def _planner_node(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        self._check_interruption(state)
        queue = config.get("configurable", {}).get("queue")

        iteration = state.get("iteration_count", 0) + 1

        # Enforce iteration limit loop-guard
        if iteration > self._settings.agent_max_iterations:
            if queue:
                max_iter = self._settings.agent_max_iterations
                await queue.put(
                    {
                        "event": "thought",
                        "data": {
                            "content": (
                                f"[Max iterations of {max_iter} reached "
                                "— routing to synthesis]"
                            )
                        },
                    }
                )
            return {"truncated": True, "iteration_count": iteration}

        if queue:
            await queue.put(
                {
                    "event": "thought",
                    "data": {"content": f"Planner analysis (Iteration {iteration})..."},
                }
            )

        # Logic to parse prompt and determine target sources
        prompt_lower = state["prompt"].lower()
        sources = []
        if "log" in prompt_lower or "trace" in prompt_lower or "error" in prompt_lower:
            sources.append("logs")
        if "code" in prompt_lower or "function" in prompt_lower or "src" in prompt_lower:
            sources.append("code")
        if "ticket" in prompt_lower or "issue" in prompt_lower or "bug" in prompt_lower:
            sources.append("tickets")

        # Fallback to query all sources if none detected
        if not sources:
            sources = ["logs", "code", "tickets"]

        if queue:
            await queue.put(
                {
                    "event": "thought",
                    "data": {"content": f"Planner scheduled target tasks: {sources}"},
                }
            )

        return {
            "sources_to_query": sources,
            "iteration_count": iteration,
        }

    async def _log_worker_node(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        self._check_interruption(state)
        queue = config.get("configurable", {}).get("queue")

        if queue:
            await queue.put({"event": "worker_start", "data": {"source": "logs"}})

        # superstep failure isolation try/except block.
        # NOTE: logs have no phase-1 MCP tool (a Loki/CloudWatch connector is FUTURE), so this
        # worker stays simulated while code/ticket workers route through the PDP chokepoint.
        try:
            await asyncio.sleep(0.5)
            content = (
                "LOGS: Found traceback on line 42 of auth middleware: Signature verification failed"
            )
            success = True
        except Exception as e:
            content = f"Log worker failed: {e}"
            success = False

        if queue:
            await queue.put(
                {"event": "worker_done", "data": {"source": "logs", "success": success}}
            )

        return {"sub_agent_results": [{"source": "logs", "content": content, "success": success}]}

    async def _code_worker_node(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        self._check_interruption(state)
        queue = config.get("configurable", {}).get("queue")

        if queue:
            await queue.put({"event": "worker_start", "data": {"source": "code"}})

        # Real external read through the chokepoint: requires `github:read` in scope.
        content, success = await self._fetch_via_mcp(
            config=config,
            sid=state["agent_session_id"],
            label="CODE",
            tool="github.get_file",
            arguments={"repo": "core-api", "path": "src/api/middleware/auth.py", "ref": "main"},
        )

        if queue:
            await queue.put(
                {"event": "worker_done", "data": {"source": "code", "success": success}}
            )

        return {"sub_agent_results": [{"source": "code", "content": content, "success": success}]}

    async def _ticket_worker_node(
        self, state: AgentState, config: RunnableConfig
    ) -> dict[str, Any]:
        self._check_interruption(state)
        queue = config.get("configurable", {}).get("queue")

        if queue:
            await queue.put({"event": "worker_start", "data": {"source": "tickets"}})

        # Real external read through the chokepoint: requires `servicenow:read` in scope.
        content, success = await self._fetch_via_mcp(
            config=config,
            sid=state["agent_session_id"],
            label="TICKETS",
            tool="servicenow.get_incident",
            arguments={"number": "INC0001024"},
        )

        if queue:
            await queue.put(
                {"event": "worker_done", "data": {"source": "tickets", "success": success}}
            )

        return {
            "sub_agent_results": [{"source": "tickets", "content": content, "success": success}]
        }

    async def _synthesizer_node(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        self._check_interruption(state)
        queue = config.get("configurable", {}).get("queue")

        if queue:
            await queue.put(
                {"event": "synthesis", "data": {"content": "Synthesizing cross-source findings..."}}
            )

        # Extract worker outputs
        results = state.get("sub_agent_results", [])

        # Build synthesis prompt context
        context_parts = []
        truncated = state.get("truncated", False)

        for r in results:
            if not r["success"]:
                truncated = True
                context_parts.append(f"[{r['source'].upper()}]: Source unavailable: {r['content']}")
            else:
                context_parts.append(f"[{r['source'].upper()}]: {r['content']}")

        context_str = "\n".join(context_parts)

        # Build prompt for LLM
        messages = [
            Message(
                session_id=state["agent_session_id"],
                role=Role.USER,
                content=(
                    f"Correlate the following findings:\n{context_str}\n\n"
                    f"User request: {state['prompt']}"
                ),
            )
        ]

        # Stream the LLM response directly to the queue
        collected = []
        try:
            # We call the real LLM or mock stream
            async for token in self._llm.stream(
                messages=messages,
                system=(
                    "You are an expert troubleshooter. "
                    "Synthesize the findings and explain the correlation."
                ),
            ):
                collected.append(token)
                if queue:
                    await queue.put(
                        {"event": "output", "data": {"content": token, "truncated": truncated}}
                    )
        except Exception as e:
            logger.error("LLM stream failed in Synthesizer: %s", e)
            raise

        synthesis_text = "".join(collected)
        return {"final_synthesis": synthesis_text, "truncated": truncated}

    # -----------------------------------------------------------------------
    # AgentPort Implementation
    # -----------------------------------------------------------------------
    def run(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        scope: PermissionScope,
    ) -> AsyncIterator[Mapping[str, Any]]:
        """Run the state graph and yield events for SSE."""
        return self._run_generator(agent_session, prompt, scope)

    def _agent_span(self, sid: str, scope: PermissionScope, prompt: str):
        """Root AGENT span for the run. Opening it as the current span before the graph
        task is created lets the connector's per-tool spans (DD-8/DD-11 forensics) nest
        under it — contextvars propagate into ``create_task``."""
        if self._obs is None:
            return _noop_span()
        attrs: dict[str, Any] = {
            ObsAttr.SESSION_ID: sid,
            ObsAttr.TENANT_ID: scope.tenant_id,
            ObsAttr.INPUT: prompt,
        }
        if scope.subject_id:
            attrs[ObsAttr.USER_ID] = scope.subject_id
        return self._obs.span(f"agent.run.{sid}", kind=SpanKind.AGENT, attributes=attrs)

    async def _run_generator(
        self,
        agent_session: AgentSession,
        prompt: str,
        scope: PermissionScope,
    ) -> AsyncIterator[Mapping[str, Any]]:
        sid = agent_session.agent_session_id

        # Clear previous interrupt flags if any
        self._interrupted.discard(sid)

        async with self._agent_span(sid, scope, prompt) as aspan:
            queue: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue()
            initial_state = AgentState(
                agent_session_id=sid,
                prompt=prompt,
                sources_to_query=[],
                sub_agent_results=[],
                final_synthesis="",
                iteration_count=0,
                truncated=False,
            )

            config = {
                "configurable": {
                    "queue": queue,
                    "scope": scope,  # workers fetch through the PDP chokepoint with this scope
                    "max_concurrency": self._settings.agent_max_concurrency,
                }
            }

            # Run the graph as a background task so we can consume the queue concurrently
            task = asyncio.create_task(self._graph.ainvoke(initial_state, config))
            self._tasks[sid] = task

            try:
                while not task.done() or not queue.empty():
                    try:
                        # Poll queue to yield values
                        item = await asyncio.wait_for(queue.get(), timeout=0.05)
                        yield item
                    except TimeoutError:
                        continue

                # If task finished with exception, propagate it. A trajectory KILL (DD-11) is
                # special: record it for the reaper and emit a terminal `killed` event so the
                # client learns *why* before the exception tears the stream down.
                if task.done() and task.exception() is not None:
                    exc = task.exception()
                    kill = _find_kill(exc)
                    if kill is not None:
                        reason = str(kill)
                        if self._kill_registry is not None:
                            self._kill_registry.record(sid, reason)
                        logger.warning(
                            "LangGraphRunner: session %s KILLED (DD-11): %s", sid, reason
                        )
                        yield {
                            "event": "killed",
                            "data": {"reason": reason, "source": "trajectory-monitor"},
                        }
                        raise kill
                    raise exc  # type: ignore[misc]

                if aspan is not None and task.done() and task.exception() is None:
                    result = task.result()
                    if isinstance(result, Mapping):
                        aspan.set_attribute(ObsAttr.OUTPUT, result.get("final_synthesis", ""))

            except asyncio.CancelledError:
                logger.info(
                    "LangGraphRunner.run: Task cancelled cooperatively for session %s", sid
                )
                task.cancel()
                raise
            finally:
                self._tasks.pop(sid, None)
                self._interrupted.discard(sid)

    async def register_tool(self, *, agent_session_id: str, tool_name: str) -> None:
        """Stub for tool registration (filtering handled by use case)."""
        pass

    async def interrupt(self, *, agent_session_id: str) -> None:
        """Mark agent session as interrupted for cooperative cancellation."""
        logger.info("Interrupt requested for agent session %s", agent_session_id)
        self._interrupted.add(agent_session_id)
        # Also cancel the running task if present
        task = self._tasks.get(agent_session_id)
        if task:
            task.cancel()

    async def terminate(self, *, agent_session_id: str) -> None:
        """Hard stop session task."""
        logger.info("Terminate requested for agent session %s", agent_session_id)
        self._interrupted.add(agent_session_id)
        task = self._tasks.get(agent_session_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
