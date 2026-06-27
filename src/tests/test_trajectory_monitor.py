"""TrajectoryMonitor tests (DD-11) — cumulative session risk over a sequence.

The headline is ``test_thousand_small_cuts_trips_monitor_though_each_passes_pdp``: the
DD-11 enforcement check. Every action is individually ALLOWED by the PDP (DD-8), yet the
monitor escalates to KILL — proving the two controls are complementary, not redundant.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from core.domain.policy.trajectory import ActionEvent, RiskLevel
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
from core.use_cases.policy.trajectory_monitor import TrajectoryMonitor


def _event(
    effect: Effect = Effect.WRITE,
    *,
    environment: str = "prod",
    decision: DecisionEffect = DecisionEffect.ALLOW,
    reversibility: Reversibility = Reversibility.REVERSIBLE,
    data_sources: frozenset[str] = frozenset({"first_party"}),
    required_permissions: frozenset[str] = frozenset(),
) -> ActionEvent:
    return ActionEvent(
        effect=effect,
        reversibility=reversibility,
        environment=environment,
        decision=decision,
        data_sources=data_sources,
        required_permissions=required_permissions,
    )


def test_benign_reads_stay_ok():
    """Reads of non-sensitive data (no first-party/prod provenance) carry no risk.
    (Bulk reads of *sensitive* data are a mild signal by design — covered elsewhere.)"""
    mon = TrajectoryMonitor()
    verdict = None
    for _ in range(50):
        verdict = mon.observe(
            "s1", _event(Effect.READ, environment="dev", data_sources=frozenset())
        )
    assert verdict is not None and verdict.level is RiskLevel.OK


def test_single_prod_write_is_ok():
    mon = TrajectoryMonitor()
    verdict = mon.observe("s1", _event(Effect.WRITE, environment="prod"))
    assert verdict.level is RiskLevel.OK  # one action is the PDP's job, not the monitor's


def test_mutating_drift_accumulates_to_kill():
    mon = TrajectoryMonitor()
    last = None
    saw_drift = False
    for _ in range(30):
        last = mon.observe("s1", _event(Effect.WRITE, environment="prod"))
        saw_drift = saw_drift or "mutating_drift" in last.signals
    assert last is not None and last.level is RiskLevel.KILL
    assert saw_drift


def test_read_then_exfiltrate_is_flagged_and_escalates():
    mon = TrajectoryMonitor()
    mon.observe("s1", _event(Effect.READ, environment="prod"))  # sensitive read
    verdict = mon.observe(
        "s1", _event(Effect.WRITE, environment="prod", data_sources=frozenset({"external_tool"}))
    )
    assert "read_then_exfiltrate" in verdict.signals
    assert verdict.level in (RiskLevel.REQUIRE_APPROVAL, RiskLevel.KILL)


def test_elevation_gradient_is_flagged():
    mon = TrajectoryMonitor()
    verdicts = [
        mon.observe("s1", _event(Effect.WRITE, environment="dev")),
        mon.observe("s1", _event(Effect.WRITE, environment="staging")),
        mon.observe("s1", _event(Effect.WRITE, environment="prod")),
    ]
    assert any("elevation_gradient" in v.signals for v in verdicts)
    assert verdicts[-1].level is not RiskLevel.OK


def test_probing_on_denied_actions_raises_risk():
    mon = TrajectoryMonitor()
    last = None
    for _ in range(3):
        last = mon.observe(
            "s1", _event(Effect.READ, environment="dev", decision=DecisionEffect.DENY)
        )
    assert last is not None
    assert "probing" in last.signals
    assert last.risk > 0.0


def test_sessions_are_isolated():
    mon = TrajectoryMonitor()
    for _ in range(30):
        mon.observe("hot", _event(Effect.WRITE, environment="prod"))
    cool = mon.observe("cool", _event(Effect.READ, environment="dev"))
    assert cool.level is RiskLevel.OK
    assert mon.risk("hot") > mon.risk("cool")


def test_reset_clears_session():
    mon = TrajectoryMonitor()
    for _ in range(30):
        mon.observe("s1", _event(Effect.WRITE, environment="prod"))
    assert mon.risk("s1") > 0
    mon.reset("s1")
    assert mon.risk("s1") == 0.0


# --- DD-11 enforcement check ----------------------------------------------
class _ProdResolver:
    async def resolve(
        self, *, tool_name: str, arguments: Mapping[str, object], scope: PermissionScope
    ) -> CanonicalTarget:
        return CanonicalTarget(kind="k", resource_id="r1", environment="prod")


def test_thousand_small_cuts_trips_monitor_though_each_passes_pdp():
    """Every individual write is ALLOWED by the PDP, yet the cumulative trajectory is KILL."""
    tool = ToolPolicy(
        tool_name="t.write",
        effect=Effect.WRITE,
        reversibility=Reversibility.REVERSIBLE,
        target_kind="k",
        required_permissions=frozenset({"w"}),
        allowed_environments=frozenset({"prod"}),
        allowed_data_sources=frozenset({"first_party"}),
        max_items=5,
    )
    pdp = PolicyDecisionPoint(registry=PolicyRegistry([tool]), target_resolver=_ProdResolver())
    monitor = TrajectoryMonitor()
    scope = PermissionScope(tenant_id="t1", permissions=frozenset({"w"}))
    request = ActionRequest(
        tool_name="t.write", scope=scope, item_count=1, data_sources=frozenset({"first_party"})
    )

    verdict = None
    for _ in range(30):
        decision = asyncio.run(pdp.decide(request))
        assert decision.effect is DecisionEffect.ALLOW  # PDP clears every single action
        event = _event(
            Effect.WRITE,
            environment=decision.target.environment,
            decision=decision.effect,
        )
        verdict = monitor.observe("campaign", event)

    assert verdict is not None and verdict.level is RiskLevel.KILL
