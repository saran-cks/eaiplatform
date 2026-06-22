"""AgentPort — ReAct agent lifecycle and tool dispatch.

The LlamaIndex AgentRunner adapter implements this. Tools are MCP-backed and registered
filtered by PermissionScope at session creation. Code generation output is streamed for
Monaco display; sandbox execution is FUTURE. Events are emitted as a stream for SSE.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable

from core.domain.entities.session import AgentSession
from core.domain.value_objects.permission_scope import PermissionScope


@runtime_checkable
class AgentPort(Protocol):
    def run(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        scope: PermissionScope,
    ) -> AsyncIterator[Mapping[str, Any]]:
        """Run the ReAct loop; yields step events (thought/tool/observation/output) for SSE."""
        ...

    async def register_tool(self, *, agent_session_id: str, tool_name: str) -> None:
        """Register an MCP tool with a live agent (already scope-checked by the caller)."""
        ...

    async def interrupt(self, *, agent_session_id: str) -> None:
        """Cooperatively stop a running agent; results in status=interrupted."""
        ...

    async def terminate(self, *, agent_session_id: str) -> None:
        """Hard-stop and release resources (used by the agent reaper daemon)."""
        ...
