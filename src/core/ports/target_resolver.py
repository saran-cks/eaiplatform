"""TargetResolverPort — resolve the REAL, adapter-bound target of an action.

DD-8 "canonical targets": the PDP must resolve the concrete resource itself and never
trust a model-supplied label like ``target=dev-db``. The resolver is adapter-bound (it
knows the real environment/id behind the tool arguments); the PDP compares the resolved
target against the model's claim to catch spoofing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from core.domain.policy.types import CanonicalTarget
from core.domain.value_objects.permission_scope import PermissionScope


@runtime_checkable
class TargetResolverPort(Protocol):
    async def resolve(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, object],
        scope: PermissionScope,
    ) -> CanonicalTarget | None:
        """Return the canonical target, or None if it cannot be resolved (=> default-deny)."""
        ...
