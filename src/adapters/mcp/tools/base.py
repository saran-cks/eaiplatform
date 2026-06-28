"""ToolSpec — the single declaration of an MCP tool's display + policy surface.

One spec yields two things consumed elsewhere:
  * ``to_policy()`` → the ``ToolPolicy`` the PDP enforces (default-deny without it).
  * ``describe()``  → the scope-filtered ``list_tools`` view shown to a caller.

``id_arg`` names the argument carrying the resource id; the target resolver reads it to
build the canonical target (so the PDP never trusts a model-supplied label).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from core.domain.policy.types import Effect, Reversibility, ToolPolicy

# Read tools may act in any environment (reading prod is allowed); writes will narrow this.
ALL_ENVIRONMENTS: frozenset[str] = frozenset({"dev", "staging", "prod"})


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str                          # e.g. "servicenow.get_incident"
    server: str                        # e.g. "servicenow"
    description: str
    target_kind: str                   # e.g. "servicenow:incident" (== resolved target.kind)
    id_arg: str                        # argument name carrying the resource id
    effect: Effect = Effect.READ
    reversibility: Reversibility = Reversibility.REVERSIBLE
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    allowed_environments: frozenset[str] = field(default_factory=lambda: ALL_ENVIRONMENTS)
    allowed_data_sources: frozenset[str] = field(default_factory=frozenset)
    max_items: int | None = None
    requires_approval: bool = False
    input_schema: Mapping[str, object] = field(default_factory=dict)

    def to_policy(self) -> ToolPolicy:
        return ToolPolicy(
            tool_name=self.name,
            effect=self.effect,
            reversibility=self.reversibility,
            target_kind=self.target_kind,
            required_permissions=self.required_permissions,
            allowed_environments=self.allowed_environments,
            allowed_data_sources=self.allowed_data_sources,
            max_items=self.max_items,
            requires_approval=self.requires_approval,
        )

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "server": self.server,
            "description": self.description,
            "effect": self.effect.value,
            "input_schema": dict(self.input_schema),
        }
