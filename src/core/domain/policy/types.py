"""Policy domain types (DD-8…DD-12).

These model the *control plane*: the authority an action needs, independent of anything
the model said. The LLM proposes an ``ActionRequest``; the PDP returns a ``Decision``.
Conviction in the data plane can never appear here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from core.domain.value_objects.permission_scope import PermissionScope


class Effect(StrEnum):
    """The kind of effect a tool has on an external system."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"


class Reversibility(StrEnum):
    """DD-12: the axis for human-in-the-loop is reversibility, not vague 'sensitivity'."""

    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class DecisionEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class CanonicalTarget:
    """The REAL target, resolved adapter-bound by the PDP — never a model-supplied label."""

    kind: str             # e.g. "servicenow:ticket"
    resource_id: str      # concrete resolved id
    environment: str = "prod"  # "prod" | "staging" | "dev"


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """The per-tool policy contract. A write-capable tool with no policy is default-denied.

    Bounded parameters (``max_items``) and flow gating (``allowed_data_sources``) are the
    pressure-tested hardening over a naïve allow/deny-on-action-class.
    """

    tool_name: str
    effect: Effect
    reversibility: Reversibility
    target_kind: str
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    # Environments this tool may act on. Prod is excluded unless explicitly listed.
    allowed_environments: frozenset[str] = field(default_factory=lambda: frozenset({"dev"}))
    # Flow gating: which data-source-trust labels may feed this sink (write/delete only).
    allowed_data_sources: frozenset[str] = field(default_factory=frozenset)
    # Bounded parameter: max blast radius per call. None => unbounded (discouraged for writes).
    max_items: int | None = None
    # Explicit approval requirement (irreversibility also forces approval).
    requires_approval: bool = False


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """What the agent PROPOSES. Nothing here is trusted on the model's say-so."""

    tool_name: str
    scope: PermissionScope
    arguments: Mapping[str, object] = field(default_factory=dict)
    item_count: int = 1
    # Provenance labels of the data feeding this action's parameters (for flow gating).
    data_sources: frozenset[str] = field(default_factory=frozenset)
    approval_token: str | None = None
    # Delegation (DD-8): the effective scope may only NARROW vs the delegating parent.
    parent_scope: PermissionScope | None = None
    # DD-9: a signal only. Never load-bearing for a DENY; may only add approval friction.
    taint_level: float = 0.0
    # What the model CLAIMED the target is — used only to detect spoofing vs the resolved one.
    model_supplied_target: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    effect: DecisionEffect
    reason: str
    target: CanonicalTarget | None = None
    obligations: frozenset[str] = field(default_factory=frozenset)

    @property
    def allowed(self) -> bool:
        return self.effect is DecisionEffect.ALLOW


class PolicyRegistry:
    """Lookup of tool_name -> ToolPolicy. Absence is meaningful: default-deny."""

    def __init__(self, policies: Iterable[ToolPolicy] = ()) -> None:
        self._by_name: dict[str, ToolPolicy] = {p.tool_name: p for p in policies}

    def get(self, tool_name: str) -> ToolPolicy | None:
        return self._by_name.get(tool_name)

    def register(self, policy: ToolPolicy) -> None:
        self._by_name[policy.tool_name] = policy
