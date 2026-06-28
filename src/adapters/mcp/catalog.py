"""ToolCatalog — the registry of available MCP tools and their policies.

Single source the connector reads for three things:
  * ``policy_registry()`` — the PDP's ``PolicyRegistry`` (a tool absent here is default-denied).
  * ``list_for_scope()``  — the scope-filtered ``list_tools`` view.
  * ``get()`` / ``server_for()`` — resolution by tool name.

Adding a tool = adding a ``ToolSpec`` to a ``tools/*`` module; both the policy and the
listing follow automatically, so they cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable

from adapters.mcp.tools import confluence, github, servicenow, zendesk
from adapters.mcp.tools.base import ToolSpec
from core.domain.policy.types import PolicyRegistry
from core.domain.value_objects.permission_scope import PermissionScope


class ToolCatalog:
    def __init__(self, specs: Iterable[ToolSpec]) -> None:
        self._by_name: dict[str, ToolSpec] = {s.name: s for s in specs}

    def get(self, name: str) -> ToolSpec | None:
        return self._by_name.get(name)

    def all(self) -> tuple[ToolSpec, ...]:
        return tuple(self._by_name.values())

    def server_for(self, name: str) -> str | None:
        spec = self._by_name.get(name)
        return spec.server if spec else None

    def policy_registry(self) -> PolicyRegistry:
        return PolicyRegistry(spec.to_policy() for spec in self._by_name.values())

    def list_for_scope(self, scope: PermissionScope) -> list[dict[str, object]]:
        """Only tools whose required permissions the scope fully holds are visible."""
        return [
            spec.describe()
            for spec in self._by_name.values()
            if scope.has_all(*spec.required_permissions)
        ]


def build_catalog() -> ToolCatalog:
    """Assemble the catalog from every source-system tool module."""
    specs: list[ToolSpec] = []
    for module in (servicenow, confluence, github, zendesk):
        specs.extend(module.SPECS)
    return ToolCatalog(specs)
