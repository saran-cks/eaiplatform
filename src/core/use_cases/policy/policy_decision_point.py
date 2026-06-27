"""PolicyDecisionPoint — the deterministic, default-deny action chokepoint (DD-8).

Every agent-initiated effect on an external system routes through ``decide()`` BEFORE
execution. The PDP is correct under "the agent is the attacker": its allow decision never
depends on the model being honest, nor on taint (DD-9). The LLM proposes; the PDP decides.

Rule order (first failure wins; default-deny throughout):
  1. unknown tool / no policy        -> DENY
  2. scope lacks required permission -> DENY
  3. delegation widens scope         -> DENY        (scope may only narrow)
  4. target unresolved               -> DENY
  5. model-supplied target spoof     -> DENY        (claim != adapter-resolved)
  6. target kind / environment       -> DENY
  7. disallowed read->write flow     -> DENY        (flow gating)
  8. blast radius exceeds bound      -> DENY        (bounded params)
  9. needs approval, no token        -> REQUIRE_APPROVAL   (irreversible | explicit | taint)
 10. otherwise                       -> ALLOW (+ mint_capability obligation for writes, DD-10)

Taint (DD-9) only ever *adds* approval friction; it can never turn a DENY into an ALLOW.
Removing the taint input leaves every DENY a DENY — verified by tests.
"""

from __future__ import annotations

import logging

from core.domain.policy.types import (
    ActionRequest,
    Decision,
    DecisionEffect,
    Effect,
    PolicyRegistry,
    Reversibility,
)
from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.target_resolver import TargetResolverPort

logger = logging.getLogger(__name__)

# Taint at/above this only raises approval friction on writes — never a hard deny (DD-9).
TAINT_FRICTION_THRESHOLD = 0.5

_MUTATING = (Effect.WRITE, Effect.DELETE)


def _deny(reason: str) -> Decision:
    return Decision(effect=DecisionEffect.DENY, reason=reason)


def _scope_narrows(child: PermissionScope, parent: PermissionScope) -> bool:
    """True iff ``child`` is an attenuation of ``parent`` (same tenant, perms a subset)."""
    return child.tenant_id == parent.tenant_id and child.permissions <= parent.permissions


class PolicyDecisionPoint:
    def __init__(
        self, *, registry: PolicyRegistry, target_resolver: TargetResolverPort
    ) -> None:
        self._registry = registry
        self._resolver = target_resolver

    async def decide(self, request: ActionRequest) -> Decision:
        # 1. default-deny: a tool with no registered policy cannot act.
        policy = self._registry.get(request.tool_name)
        if policy is None:
            return _deny(f"no policy registered for tool '{request.tool_name}'")

        # 2. the scope must hold every permission the tool requires.
        if not request.scope.has_all(*policy.required_permissions):
            return _deny("scope lacks required permission(s)")

        # 3. delegation may only narrow authority, never widen it (confused-deputy guard).
        if request.parent_scope is not None and not _scope_narrows(
            request.scope, request.parent_scope
        ):
            return _deny("delegated scope widens authority")

        # 4-6. resolve the REAL target; never trust the model's label.
        target = await self._resolver.resolve(
            tool_name=request.tool_name,
            arguments=request.arguments,
            scope=request.scope,
        )
        if target is None:
            return _deny("target could not be canonically resolved")
        if (
            request.model_supplied_target is not None
            and request.model_supplied_target != target.resource_id
        ):
            return _deny("model-supplied target does not match resolved target")
        if target.kind != policy.target_kind:
            return _deny(f"target kind '{target.kind}' != policy '{policy.target_kind}'")
        if target.environment not in policy.allowed_environments:
            return _deny(f"environment '{target.environment}' not permitted for this tool")

        # 7. flow gating: every data source feeding a mutating action must be allowed to.
        if policy.effect in _MUTATING and not request.data_sources <= policy.allowed_data_sources:
            return _deny("data source not permitted to flow into this sink")

        # 8. bounded parameters: cap blast radius.
        if policy.max_items is not None and request.item_count > policy.max_items:
            return _deny(f"item_count {request.item_count} exceeds bound {policy.max_items}")

        # 9. approval: irreversibility, explicit flag, or taint friction (writes only).
        taint_friction = (
            request.taint_level >= TAINT_FRICTION_THRESHOLD and policy.effect in _MUTATING
        )
        needs_approval = (
            policy.requires_approval
            or policy.reversibility is Reversibility.IRREVERSIBLE
            or taint_friction
        )
        if needs_approval and not (request.approval_token or "").strip():
            reason = "taint friction" if taint_friction else "irreversible/sensitive action"
            return Decision(
                effect=DecisionEffect.REQUIRE_APPROVAL,
                reason=f"approval required ({reason})",
                target=target,
            )

        # 10. allow. Mutating actions carry a capability-mint obligation (DD-10).
        obligations = frozenset({"mint_capability"}) if policy.effect in _MUTATING else frozenset()
        return Decision(
            effect=DecisionEffect.ALLOW,
            reason="policy satisfied",
            target=target,
            obligations=obligations,
        )
