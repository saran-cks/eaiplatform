"""Agent ↔ MCP chokepoint wiring — the runtime caller of DD-8 + DD-11.

These prove the agent runtime is the *first runtime caller* of the PDP chokepoint:
  * in-scope workers fetch real data through the connector (transport reached),
  * an under-scoped worker is denied by the PDP and degrades gracefully (run still finishes),
  * a trajectory KILL tears the whole session down: a `killed` event is emitted, the kill is
    recorded for the reaper, and RunAgentUseCase persists status=KILLED,
  * the agent_reaper drains the kill registry and force-terminates the session (DD-11 backstop).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.agent.langgraph_runner import LangGraphRunner
from adapters.mcp.catalog import build_catalog
from adapters.mcp.connector import PdpGuardedMCPConnector
from adapters.mcp.target_resolver import McpTargetResolver
from core.domain.agent_control import AgentKillRegistry
from core.domain.entities.session import AgentSession, AgentStatus
from core.domain.policy.trajectory import RiskThresholds
from core.domain.value_objects.guard_verdict import GuardVerdict
from core.domain.value_objects.permission_scope import PermissionScope
from core.use_cases.agent.run_agent import RunAgentUseCase
from core.use_cases.policy.policy_decision_point import PolicyDecisionPoint
from core.use_cases.policy.trajectory_monitor import TrajectoryMonitor
from daemon.tasks import _agent_reaper


class SpyTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call_tool(
        self, *, server: str, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.calls.append((server, name, dict(arguments)))
        return {"server": server, "tool": name, "result": f"[real {name}]", "ok": True}

    async def close(self) -> None:
        return None


class FakeLLM:
    """Minimal LLMPort stand-in: streams a single synthesis token."""

    async def stream(self, *, messages: Any, system: str) -> AsyncIterator[str]:
        yield "synthesis-ok"


def _connector(*, monitor: TrajectoryMonitor | None = None, env: str = "prod"):
    catalog = build_catalog()
    resolver = McpTargetResolver(catalog=catalog, environment=env)
    pdp = PolicyDecisionPoint(registry=catalog.policy_registry(), target_resolver=resolver)
    transport = SpyTransport()
    conn = PdpGuardedMCPConnector(
        catalog=catalog, pdp=pdp, monitor=monitor or TrajectoryMonitor(), transport=transport
    )
    return conn, transport


def _runner(connector, kill_registry: AgentKillRegistry | None = None) -> LangGraphRunner:
    settings = MagicMock()
    settings.agent_max_iterations = 12
    settings.agent_max_concurrency = 4
    return LangGraphRunner(settings, FakeLLM(), mcp=connector, kill_registry=kill_registry)


def _scope(*perms: str) -> PermissionScope:
    return PermissionScope(tenant_id="t1", subject_id="u1", permissions=frozenset(perms))


def _session() -> AgentSession:
    return AgentSession(agent_session_id="a1", session_id="s1", tenant_id="t1", subject_id="u1")


async def _drain(runner: LangGraphRunner, prompt: str, scope: PermissionScope):
    return [e async for e in runner.run(agent_session=_session(), prompt=prompt, scope=scope)]


# --- in-scope workers reach the real transport --------------------------------------


@pytest.mark.asyncio
async def test_in_scope_workers_fetch_through_chokepoint():
    conn, transport = _connector()
    runner = _runner(conn)

    scope = _scope("github:read", "servicenow:read")
    await _drain(runner, "inspect the code and the ticket", scope)

    invoked = {name for _, name, _ in transport.calls}
    assert invoked == {"github.get_file", "servicenow.get_incident"}


# --- under-scoped worker is PDP-denied but the run still completes -------------------


@pytest.mark.asyncio
async def test_underscoped_worker_is_denied_and_run_survives():
    conn, transport = _connector()
    runner = _runner(conn)

    # No permissions → the PDP denies the code fetch; the worker degrades, no transport call.
    events = await _drain(runner, "inspect the code", _scope())

    assert transport.calls == []
    assert any(e["event"] == "output" for e in events)  # synthesizer still ran
    assert not any(e["event"] == "killed" for e in events)


# --- a trajectory KILL tears the whole session down ---------------------------------


@pytest.mark.asyncio
async def test_trajectory_kill_emits_killed_event_and_records_for_reaper():
    monitor = TrajectoryMonitor(
        thresholds=RiskThresholds(throttle=0.01, require_approval=0.02, kill=0.03)
    )
    conn, transport = _connector(monitor=monitor, env="prod")
    registry = AgentKillRegistry()
    runner = _runner(conn, kill_registry=registry)

    # The runner-level generator emits `killed` then re-raises (RunAgentUseCase swallows it).
    from core.domain.policy.types import TrajectoryKill

    events: list[Any] = []
    with pytest.raises(TrajectoryKill):
        async for e in runner.run(agent_session=_session(), prompt="inspect the code",
                                  scope=_scope("github:read")):
            events.append(e)

    assert any(e["event"] == "killed" for e in events)
    assert "a1" in registry  # recorded for the agent_reaper to force-terminate
    assert transport.calls == []  # KILL vetoed before the transport


@pytest.mark.asyncio
async def test_run_agent_persists_killed_status():
    monitor = TrajectoryMonitor(
        thresholds=RiskThresholds(throttle=0.01, require_approval=0.02, kill=0.03)
    )
    conn, _ = _connector(monitor=monitor, env="prod")
    registry = AgentKillRegistry()
    runner = _runner(conn, kill_registry=registry)

    store = AsyncMock()
    guard = AsyncMock()
    guard.screen.return_value = GuardVerdict.allow()
    uc = RunAgentUseCase(store=store, agent=runner, guard=guard)

    pipeline = await uc.execute(
        session_id="s1",
        agent_session_id="a1",
        prompt="inspect the code",
        scope=_scope("github:read"),
    )
    events = [e async for e in pipeline]  # must NOT raise — KILL is a clean terminal

    assert any(e["event"] == "killed" for e in events)
    store.update_agent_status.assert_called_once_with(
        agent_session_id="a1", status=AgentStatus.KILLED
    )


# --- the reaper drains the registry and force-terminates ----------------------------


@pytest.mark.asyncio
async def test_agent_reaper_terminates_killed_sessions():
    registry = AgentKillRegistry()
    registry.record("a1", "risk 0.50 crossed KILL")
    agent = AsyncMock()

    task = asyncio.create_task(_agent_reaper(0, agent=agent, kill_registry=registry))
    await asyncio.sleep(0.02)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    agent.terminate.assert_awaited_with(agent_session_id="a1")
    assert "a1" not in registry  # drained
