"""PolicyDecisionPoint tests (DD-8…DD-12) — every rule, both directions.

The PDP is the deterministic wall a fully-poisoned agent hits. These assert it is
default-deny, that its allow never depends on the model being honest (canonical target,
no spoof), that flows/bounds/delegation are enforced, and — critically — that taint
(DD-9) only ever adds friction and never rescues a deny.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from core.domain.policy.types import (
    ActionRequest,
    CanonicalTarget,
    DecisionEffect,
    Effect,
    PolicyRegistry,
    Reversibility,
    ToolPolicy,
)
from core.domain.value_objects.permission_scope import PermissionScope
from core.use_cases.policy.policy_decision_point import PolicyDecisionPoint


class FakeResolver:
    """Returns a fixed canonical target (or None). Stands in for the adapter-bound resolver."""

    def __init__(self, target: CanonicalTarget | None) -> None:
        self._target = target

    async def resolve(
        self, *, tool_name: str, arguments: Mapping[str, object], scope: PermissionScope
    ) -> CanonicalTarget | None:
        return self._target


# --- standard fixtures -----------------------------------------------------
WRITE_TOOL = ToolPolicy(
    tool_name="servicenow.close_ticket",
    effect=Effect.WRITE,
    reversibility=Reversibility.REVERSIBLE,
    target_kind="servicenow:ticket",
    required_permissions=frozenset({"servicenow:write"}),
    allowed_environments=frozenset({"prod"}),
    allowed_data_sources=frozenset({"first_party"}),
    max_items=5,
)
READ_TOOL = ToolPolicy(
    tool_name="servicenow.get_ticket",
    effect=Effect.READ,
    reversibility=Reversibility.REVERSIBLE,
    target_kind="servicenow:ticket",
    required_permissions=frozenset({"servicenow:read"}),
    allowed_environments=frozenset({"prod", "dev"}),
)
DELETE_TOOL = ToolPolicy(
    tool_name="github.delete_branch",
    effect=Effect.DELETE,
    reversibility=Reversibility.IRREVERSIBLE,
    target_kind="github:branch",
    required_permissions=frozenset({"github:write"}),
    allowed_environments=frozenset({"prod"}),
    allowed_data_sources=frozenset({"first_party"}),
    max_items=1,
)

TICKET_TARGET = CanonicalTarget(kind="servicenow:ticket", resource_id="INC42", environment="prod")
BRANCH_TARGET = CanonicalTarget(kind="github:branch", resource_id="main", environment="prod")

SCOPE = PermissionScope(
    tenant_id="t1",
    permissions=frozenset({"servicenow:write", "servicenow:read", "github:write"}),
)


def _pdp(policies, target) -> PolicyDecisionPoint:
    return PolicyDecisionPoint(
        registry=PolicyRegistry(policies), target_resolver=FakeResolver(target)
    )


def _write_request(**overrides) -> ActionRequest:
    base: dict = {
        "tool_name": "servicenow.close_ticket",
        "scope": SCOPE,
        "item_count": 1,
        "data_sources": frozenset({"first_party"}),
    }
    base.update(overrides)
    return ActionRequest(**base)


# --- default-deny backbone -------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_tool_is_default_denied():
    pdp = _pdp([], TICKET_TARGET)  # empty registry
    decision = await pdp.decide(_write_request())
    assert decision.effect is DecisionEffect.DENY
    assert "no policy" in decision.reason


@pytest.mark.asyncio
async def test_missing_permission_denied():
    weak = PermissionScope(tenant_id="t1", permissions=frozenset({"servicenow:read"}))
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request(scope=weak))
    assert decision.effect is DecisionEffect.DENY


# --- delegation attenuation ------------------------------------------------
@pytest.mark.asyncio
async def test_delegation_widening_denied():
    parent = PermissionScope(tenant_id="t1", permissions=frozenset({"servicenow:read"}))
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request(parent_scope=parent))
    assert decision.effect is DecisionEffect.DENY
    assert "widens" in decision.reason


@pytest.mark.asyncio
async def test_delegation_narrowing_allowed():
    parent = PermissionScope(tenant_id="t1", permissions=SCOPE.permissions | {"extra"})
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request(parent_scope=parent))
    assert decision.effect is DecisionEffect.ALLOW


# --- canonical target ------------------------------------------------------
@pytest.mark.asyncio
async def test_unresolved_target_denied():
    pdp = _pdp([WRITE_TOOL], None)
    decision = await pdp.decide(_write_request())
    assert decision.effect is DecisionEffect.DENY


@pytest.mark.asyncio
async def test_model_supplied_target_spoof_denied():
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request(model_supplied_target="INC9999"))
    assert decision.effect is DecisionEffect.DENY
    assert "match" in decision.reason


@pytest.mark.asyncio
async def test_wrong_target_kind_denied():
    pdp = _pdp([WRITE_TOOL], BRANCH_TARGET)  # branch target for a ticket tool
    decision = await pdp.decide(_write_request())
    assert decision.effect is DecisionEffect.DENY


@pytest.mark.asyncio
async def test_environment_not_allowed_denied():
    dev_target = CanonicalTarget(kind="servicenow:ticket", resource_id="INC42", environment="dev")
    pdp = _pdp([WRITE_TOOL], dev_target)  # write tool is prod-only
    decision = await pdp.decide(_write_request())
    assert decision.effect is DecisionEffect.DENY


# --- flow gating + bounded params ------------------------------------------
@pytest.mark.asyncio
async def test_disallowed_flow_denied():
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request(data_sources=frozenset({"external_tool"})))
    assert decision.effect is DecisionEffect.DENY
    assert "flow" in decision.reason


@pytest.mark.asyncio
async def test_blast_radius_bound_denied():
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request(item_count=500))
    assert decision.effect is DecisionEffect.DENY
    assert "exceeds" in decision.reason


# --- happy paths -----------------------------------------------------------
@pytest.mark.asyncio
async def test_reversible_write_allowed_with_capability_obligation():
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request())
    assert decision.effect is DecisionEffect.ALLOW
    assert "mint_capability" in decision.obligations
    assert decision.target == TICKET_TARGET


@pytest.mark.asyncio
async def test_read_allowed_without_obligation_and_ignores_flow():
    pdp = _pdp([READ_TOOL], TICKET_TARGET)
    req = ActionRequest(
        tool_name="servicenow.get_ticket",
        scope=SCOPE,
        data_sources=frozenset({"external_tool"}),  # irrelevant for a read
    )
    decision = await pdp.decide(req)
    assert decision.effect is DecisionEffect.ALLOW
    assert decision.obligations == frozenset()


# --- reversibility / approval (DD-12) --------------------------------------
@pytest.mark.asyncio
async def test_irreversible_requires_approval():
    req = ActionRequest(
        tool_name="github.delete_branch", scope=SCOPE, data_sources=frozenset({"first_party"})
    )
    pdp = _pdp([DELETE_TOOL], BRANCH_TARGET)
    decision = await pdp.decide(req)
    assert decision.effect is DecisionEffect.REQUIRE_APPROVAL


@pytest.mark.asyncio
async def test_irreversible_with_approval_token_allowed():
    req = ActionRequest(
        tool_name="github.delete_branch",
        scope=SCOPE,
        data_sources=frozenset({"first_party"}),
        approval_token="signed-human-approval",
    )
    pdp = _pdp([DELETE_TOOL], BRANCH_TARGET)
    decision = await pdp.decide(req)
    assert decision.effect is DecisionEffect.ALLOW


# --- taint is a signal, never load-bearing (DD-9) --------------------------
@pytest.mark.asyncio
async def test_high_taint_escalates_allow_to_require_approval():
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    clean = await pdp.decide(_write_request(taint_level=0.0))
    tainted = await pdp.decide(_write_request(taint_level=0.9))
    assert clean.effect is DecisionEffect.ALLOW
    assert tainted.effect is DecisionEffect.REQUIRE_APPROVAL  # friction only


@pytest.mark.asyncio
async def test_high_taint_with_approval_still_allowed():
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    decision = await pdp.decide(_write_request(taint_level=0.9, approval_token="ok"))
    assert decision.effect is DecisionEffect.ALLOW


@pytest.mark.asyncio
async def test_taint_never_turns_a_deny_into_an_allow():
    """DD-9 enforcement: removing/adding taint must not flip a DENY. A request that is
    denied on a hard rule stays denied at every taint level."""
    weak = PermissionScope(tenant_id="t1", permissions=frozenset({"servicenow:read"}))
    pdp = _pdp([WRITE_TOOL], TICKET_TARGET)
    for taint in (0.0, 0.5, 1.0):
        decision = await pdp.decide(_write_request(scope=weak, taint_level=taint))
        assert decision.effect is DecisionEffect.DENY
