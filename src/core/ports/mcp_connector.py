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
    ) -> Mapping[str, Any]:
        """Invoke a tool after scope validation; returns the tool result payload."""
        ...

    async def disconnect(self, *, server: str, tenant_id: str) -> None:
        ...
