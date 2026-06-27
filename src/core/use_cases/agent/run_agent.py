"""RunAgentUseCase — Orchestrates agent instantiation, tracking, and execution.

Flow:
1. Ensure the session exists and create an AgentSession entry in the store.
2. Unconditionally write status='running' to Postgres before streaming.
3. Open a finally block wrapping the entire generator.
4. Stream graph events from the AgentPort runner and yield them.
5. On completion, update the AgentSession status to 'completed' / 'interrupted' / 'failed'.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

from core.domain.entities.session import AgentSession, AgentStatus
from core.domain.value_objects.guard_verdict import GuardVerdict
from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.agent import AgentPort
from core.ports.guard import GuardPort
from core.ports.store import StorePort

logger = logging.getLogger(__name__)

# Shown to the user when the prompt guard blocks the agent prompt (or screening fails closed).
_GUARD_REFUSAL = (
    "I can't run that request because it was flagged by our safety filter."
)


class RunAgentUseCase:
    """Orchestrates starting an agent session, execution, and lifecycle persistence."""

    def __init__(self, store: StorePort, agent: AgentPort, guard: GuardPort) -> None:
        self._store = store
        self._agent = agent
        self._guard = guard

    async def execute(
        self,
        *,
        session_id: str,
        agent_session_id: str,
        prompt: str,
        scope: PermissionScope,
    ) -> AsyncIterator[Mapping[str, Any]]:
        """Launch the agent loop, yield execution steps, and guarantee status update on exit."""
        # 0. Screen the prompt (first line of defence; fail-closed). A blocked prompt
        # must not start an agent run — refuse before any session/state is created.
        try:
            verdict = await self._guard.screen(prompt)
        except Exception as exc:
            logger.error("Guard screening unavailable for agent prompt; failing closed: %s", exc)
            verdict = GuardVerdict.refuse()
        if verdict.blocked:
            logger.warning(
                "Agent prompt blocked by prompt guard (tenant=%s, label=%s, score=%.4f)",
                scope.tenant_id, verdict.label, verdict.score,
            )
            return self._refusal_stream()

        # 1. Initialize and save the AgentSession with 'running' status
        agent_session = AgentSession(
            agent_session_id=agent_session_id,
            session_id=session_id,
            tenant_id=scope.tenant_id,
            subject_id=scope.subject_id,
            status=AgentStatus.RUNNING,
            started_at=datetime.now(tz=UTC),
        )
        
        await self._store.create_agent_session(agent_session)
        logger.info("RunAgentUseCase: Session %s initialized as RUNNING", agent_session_id)

        # 2. Return the generator that yields events and wraps the run in a finally block
        return self._run_lifecycle(agent_session, prompt, scope)

    async def _refusal_stream(self) -> AsyncIterator[Mapping[str, Any]]:
        """Single-event stream emitting the guard refusal as the agent's output.

        No AgentSession is created for a blocked prompt; the route appends the
        terminating ``done`` event.
        """
        yield {
            "event": "output",
            "data": {"content": _GUARD_REFUSAL, "truncated": False, "source": "guard"},
        }

    async def _run_lifecycle(
        self,
        agent_session: AgentSession,
        prompt: str,
        scope: PermissionScope,
    ) -> AsyncIterator[Mapping[str, Any]]:
        """Handles execution and ensures database status updates under all exit scenarios."""
        sid = agent_session.agent_session_id
        final_status = AgentStatus.COMPLETED
        truncated = False
        final_synthesis = ""

        try:
            # Retrieve graph steps from adapter
            async for event in self._agent.run(
                agent_session=agent_session,
                prompt=prompt,
                scope=scope,
            ):
                event_type = event.get("event")
                # Intercept final outputs or synthesis to store metadata
                if event_type == "output":
                    truncated = event["data"].get("truncated", False)
                    final_synthesis = event["data"].get("content", "")
                elif event_type == "done":
                    truncated = event["data"].get("truncated", False)

                yield event

        except asyncio.CancelledError:
            logger.warning("RunAgentUseCase: Execution task cancelled for session %s", sid)
            final_status = AgentStatus.INTERRUPTED
            raise
        except Exception as exc:
            logger.error("RunAgentUseCase: Graph execution failed for session %s: %s", sid, exc)
            final_status = AgentStatus.FAILED
            yield {
                "event": "error",
                "data": {"message": f"Execution failed: {exc}", "source": "orchestrator"},
            }
            raise
        finally:
            # Guarantee agent session status write-back
            logger.info("RunAgentUseCase: Finalizing session %s with status %s", sid, final_status)
            
            # Retrieve current status from memory state
            agent_session.status = final_status
            agent_session.ended_at = datetime.now(tz=UTC)
            agent_session.metadata["truncated"] = truncated
            agent_session.metadata["final_synthesis"] = final_synthesis
            
            try:
                # Store the updated state
                await self._store.create_agent_session(agent_session)
                await self._store.update_agent_status(agent_session_id=sid, status=final_status)
            except Exception as e:
                logger.error("RunAgentUseCase: Failed to write back lifecycle state: %s", e)
