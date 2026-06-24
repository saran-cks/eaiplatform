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
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Send

from config.settings import Settings
from core.domain.entities.message import Message, Role
from core.domain.entities.session import AgentSession
from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.agent import AgentPort
from core.ports.llm import LLMPort

logger = logging.getLogger(__name__)


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

    def __init__(self, settings: Settings, llm: LLMPort, peer_registry: Any = None) -> None:
        self._settings = settings
        self._llm = llm
        self._peer_registry = peer_registry

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

        # superstep failure isolation try/except block
        try:
            # Simulate fetching logs via MCP
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

        try:
            await asyncio.sleep(0.4)
            content = "CODE: src/api/middleware/auth.py contains verification key matching settings"
            success = True
        except Exception as e:
            content = f"Code worker failed: {e}"
            success = False

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

        try:
            await asyncio.sleep(0.3)
            content = "TICKETS: Ticket #1024 states: 'Intermittent 401 on health check endpoints'"
            success = True
        except Exception as e:
            content = f"Ticket worker failed: {e}"
            success = False

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
        return self._run_generator(agent_session, prompt)

    async def _run_generator(
        self,
        agent_session: AgentSession,
        prompt: str,
    ) -> AsyncIterator[Mapping[str, Any]]:
        sid = agent_session.agent_session_id

        # Clear previous interrupt flags if any
        self._interrupted.discard(sid)

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

            # If task finished with exception, propagate it
            if task.done() and task.exception() is not None:
                raise task.exception()  # type: ignore[misc]

        except asyncio.CancelledError:
            logger.info("LangGraphRunner.run: Task cancelled cooperatively for session %s", sid)
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
