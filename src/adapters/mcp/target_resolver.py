"""McpTargetResolver — resolves the REAL, adapter-bound target of a tool call (DD-8).

The PDP must never trust a model-supplied label like ``target=dev-db``. This resolver
derives the canonical target from the tool's own spec (``target_kind``) and the concrete
resource id carried in the arguments (``id_arg``), bound to the connector's configured
environment. An unresolvable target (missing id, unknown tool) returns ``None`` → the PDP
default-denies.
"""

from __future__ import annotations

from collections.abc import Mapping

from adapters.mcp.catalog import ToolCatalog
from core.domain.policy.types import CanonicalTarget
from core.domain.value_objects.permission_scope import PermissionScope


class McpTargetResolver:
    def __init__(self, *, catalog: ToolCatalog, environment: str) -> None:
        self._catalog = catalog
        self._environment = environment

    async def resolve(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, object],
        scope: PermissionScope,
    ) -> CanonicalTarget | None:
        spec = self._catalog.get(tool_name)
        if spec is None:
            return None
        raw_id = arguments.get(spec.id_arg)
        if raw_id is None or not str(raw_id).strip():
            return None
        return CanonicalTarget(
            kind=spec.target_kind,
            resource_id=str(raw_id),
            environment=self._environment,
        )
