"""MCP connector wiring tests — the chokepoint actually enforces DD-8 + DD-11.

These exercise the *real* PDP, trajectory monitor, catalog, and resolver (only the
external transport is a spy), proving the connector:
  * lists tools filtered by scope,
  * lets an in-scope read through to the transport (PDP ALLOW, risk OK),
  * blocks an unknown tool and an under-scoped call BEFORE the transport (default-deny),
  * feeds every decision to the monitor (a denied call accrues "probing" risk),
  * honours a KILL trajectory verdict even when the PDP itself allows the action.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from adapters.mcp.catalog import build_catalog
from adapters.mcp.connector import PdpGuardedMCPConnector
from adapters.mcp.target_resolver import McpTargetResolver
from core.domain.policy.trajectory import RiskThresholds
from core.domain.policy.types import PolicyViolation, TrajectoryKill
from core.domain.value_objects.permission_scope import PermissionScope
from core.use_cases.policy.policy_decision_point import PolicyDecisionPoint
from core.use_cases.policy.trajectory_monitor import TrajectoryMonitor


class SpyTransport:
    """Records raw tool invocations so tests can assert the transport was/wasn't reached."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(
        self, *, server: str, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.calls.append((server, name, dict(arguments)))
        return {"server": server, "tool": name, "ok": True}

    async def close(self) -> None:
        return None


def _connector(*, monitor: TrajectoryMonitor | None = None, env: str = "prod"):
    catalog = build_catalog()
    resolver = McpTargetResolver(catalog=catalog, environment=env)
    pdp = PolicyDecisionPoint(registry=catalog.policy_registry(), target_resolver=resolver)
    monitor = monitor or TrajectoryMonitor()
    transport = SpyTransport()
    conn = PdpGuardedMCPConnector(
        catalog=catalog, pdp=pdp, monitor=monitor, transport=transport
    )
    return conn, transport, monitor


def _scope(*perms: str, subject: str | None = "u1") -> PermissionScope:
    return PermissionScope(tenant_id="t1", subject_id=subject, permissions=frozenset(perms))


# --- list_tools is scope-filtered ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_filtered_by_scope():
    conn, _, _ = _connector()

    only_sn = await conn.list_tools(scope=_scope("servicenow:read"))
    assert {t["name"] for t in only_sn} == {"servicenow.get_incident"}

    everything = await conn.list_tools(
        scope=_scope("servicenow:read", "github:read", "confluence:read", "zendesk:read")
    )
    assert len(everything) == 4

    assert await conn.list_tools(scope=_scope()) == []


# --- happy path: PDP ALLOW reaches the transport ------------------------------------


@pytest.mark.asyncio
async def test_in_scope_read_is_allowed_and_invokes_transport():
    conn, transport, monitor = _connector()

    result = await conn.call_tool(
        name="servicenow.get_incident",
        arguments={"number": "INC0012345"},
        scope=_scope("servicenow:read"),
        session_id="s1",
    )

    assert result["tool"] == "servicenow.get_incident"
    assert transport.calls == [
        ("servicenow", "servicenow.get_incident", {"number": "INC0012345"})
    ]
    assert monitor.risk("s1") < RiskThresholds().throttle  # a single read stays OK


# --- default-deny: nothing reaches the transport ------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_is_denied_before_transport():
    conn, transport, _ = _connector()

    with pytest.raises(PolicyViolation):
        await conn.call_tool(
            name="servicenow.delete_everything",
            arguments={"number": "INC1"},
            scope=_scope("servicenow:read"),
            session_id="s1",
        )
    assert transport.calls == []


@pytest.mark.asyncio
async def test_missing_permission_is_denied_before_transport():
    conn, transport, _ = _connector()

    with pytest.raises(PolicyViolation):
        await conn.call_tool(
            name="servicenow.get_incident",
            arguments={"number": "INC1"},
            scope=_scope("github:read"),  # wrong permission
            session_id="s1",
        )
    assert transport.calls == []


@pytest.mark.asyncio
async def test_unresolvable_target_is_denied_before_transport():
    """Missing the id argument ⇒ target can't be canonically resolved ⇒ default-deny."""
    conn, transport, _ = _connector()

    with pytest.raises(PolicyViolation):
        await conn.call_tool(
            name="servicenow.get_incident",
            arguments={},  # no "number"
            scope=_scope("servicenow:read"),
            session_id="s1",
        )
    assert transport.calls == []


# --- DD-11 wiring: the monitor sees every decision ----------------------------------


@pytest.mark.asyncio
async def test_denied_call_accrues_probing_risk():
    conn, _, monitor = _connector()
    assert monitor.risk("s1") == 0.0

    with pytest.raises(PolicyViolation):
        await conn.call_tool(
            name="servicenow.get_incident",
            arguments={"number": "INC1"},
            scope=_scope("github:read"),
            session_id="s1",
        )

    # The PDP-deny was fed to the monitor as a "probing" signal — risk moved off zero.
    assert monitor.risk("s1") > 0.0


@pytest.mark.asyncio
async def test_kill_verdict_vetoes_even_a_pdp_allowed_action():
    # Thresholds so low that even one sensitive (prod) read crosses KILL.
    monitor = TrajectoryMonitor(
        thresholds=RiskThresholds(throttle=0.01, require_approval=0.02, kill=0.03)
    )
    conn, transport, _ = _connector(monitor=monitor, env="prod")

    with pytest.raises(TrajectoryKill):
        await conn.call_tool(
            name="servicenow.get_incident",
            arguments={"number": "INC1"},
            scope=_scope("servicenow:read"),  # PDP would ALLOW this
            session_id="s1",
        )
    # Monitor's KILL veto stopped execution before the transport.
    assert transport.calls == []


@pytest.mark.asyncio
async def test_session_id_falls_back_to_subject():
    conn, _, monitor = _connector()

    await conn.call_tool(
        name="servicenow.get_incident",
        arguments={"number": "INC1"},
        scope=_scope("servicenow:read", subject="u9"),
        # no session_id → keyed by subject_id
    )
    assert monitor.risk("u9") > 0.0


# --- catalog ↔ policy stay in lockstep ----------------------------------------------


def test_catalog_policy_registry_matches_specs():
    registry = build_catalog().policy_registry()

    policy = registry.get("servicenow.get_incident")
    assert policy is not None
    assert "servicenow:read" in policy.required_permissions
    assert policy.target_kind == "servicenow:incident"

    assert registry.get("does.not.exist") is None  # absence ⇒ default-deny
