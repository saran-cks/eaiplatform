"""MCPConnectorPort — connect to MCP servers and invoke tools, scope-checked.

External systems (ServiceNow, Confluence, GitHub, Zendesk) connect via MCP. Tools are
read-only in phase 1; write actions are FUTURE. The caller passes a PermissionScope and
the connector/registry filters tools and validates invocation against it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from core.domain.value_objects.permission_scope import PermissionScope


@runtime_checkable
class MCPConnectorPort(Protocol):
    async def connect(self, *, server: str, tenant_id: str) -> None:
        """Establish/refresh a session to a named MCP server for a tenant."""
        ...

    async def list_tools(self, *, scope: PermissionScope) -> Sequence[Mapping[str, Any]]:
        """List tools the scope is permitted to see (name, description, schema)."""
        ...

    async def call_tool(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
        scope: PermissionScope,
        session_id: str | None = None,
    ) -> Mapping[str, Any]:
        """Invoke a tool after the action-policy chokepoint clears it; return its result.

        ``session_id`` keys the cumulative-session-risk monitor (DD-11); when omitted the
        connector falls back to the scope's subject/tenant. A denied action raises
        ``PolicyViolation`` and a KILL-level trajectory raises ``TrajectoryKill`` — the
        external transport is reached only on an ALLOW.
        """
        ...

    async def disconnect(self, *, server: str, tenant_id: str) -> None:
        ...

    async def close(self) -> None:
        """Release transport resources at application shutdown."""
        ...
