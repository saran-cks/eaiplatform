"""SessionRiskStore — DD-11 risk persists across workers / restarts (and fails soft).

Covers the serialization round-trip, the Valkey-backed store over a fake CachePort, the
cross-instance accumulation that is the whole point (two monitors sharing one backend keep
adding up), and the fail-soft guarantee (a backend outage degrades to in-process, never an
exception on the action path).
"""

from __future__ import annotations

import asyncio

import pytest

from adapters.policy.session_risk_store import ValkeySessionRiskStore
from core.domain.policy.trajectory import (
    ActionEvent,
    Effect,
    Reversibility,
    SessionRiskState,
)
from core.domain.policy.types import DecisionEffect
from core.use_cases.policy.trajectory_monitor import TrajectoryMonitor


class FakeCache:
    """In-memory CachePort double."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        self.data[key] = value

    async def touch(self, key: str, *, ttl: int) -> bool:
        return key in self.data

    async def evict(self, key: str) -> None:
        self.data.pop(key, None)

    async def evict_pattern(self, pattern: str) -> int:
        return 0


class FailingCache(FakeCache):
    async def get(self, key: str) -> str | None:
        raise RuntimeError("valkey down")

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        raise RuntimeError("valkey down")


class YieldingCache(FakeCache):
    """A CachePort double that hands control back to the loop on every get/set, so
    coroutines awaiting it actually interleave — without this, gathered observe_async
    calls would run to completion one-by-one and never exercise the read-modify-write race."""

    async def get(self, key: str) -> str | None:
        await asyncio.sleep(0)
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        await asyncio.sleep(0)
        self.data[key] = value


def _write_prod() -> ActionEvent:
    return ActionEvent(
        effect=Effect.WRITE,
        reversibility=Reversibility.REVERSIBLE,
        environment="prod",
        decision=DecisionEffect.ALLOW,
        required_permissions=frozenset({"x:write"}),
    )


# --- serialization round-trip -------------------------------------------------------


def test_session_risk_state_round_trips():
    state = SessionRiskState()
    state.record(_write_prod(), 0.24)
    state.record(_write_prod(), 0.24)

    restored = SessionRiskState.from_dict(state.to_dict())

    assert restored.risk == pytest.approx(state.risk)
    assert restored.count == state.count
    assert restored.seen_permissions == state.seen_permissions
    assert list(restored.recent_effects) == list(state.recent_effects)
    assert restored.max_env_level == state.max_env_level


# --- Valkey-backed store over a fake cache ------------------------------------------


@pytest.mark.asyncio
async def test_valkey_store_save_load_delete():
    store = ValkeySessionRiskStore(FakeCache(), ttl=60)

    assert await store.load("s1") is None  # nothing yet

    state = SessionRiskState()
    state.record(_write_prod(), 0.24)
    await store.save("s1", state)

    loaded = await store.load("s1")
    assert loaded is not None
    assert loaded.risk == pytest.approx(0.24)

    await store.delete("s1")
    assert await store.load("s1") is None


# --- the point: risk accumulates across monitor instances (≈ workers) ---------------


@pytest.mark.asyncio
async def test_risk_accumulates_across_workers():
    cache = FakeCache()  # one shared backend
    worker_a = TrajectoryMonitor(store=ValkeySessionRiskStore(cache, ttl=60))
    worker_b = TrajectoryMonitor(store=ValkeySessionRiskStore(cache, ttl=60))

    v1 = await worker_a.observe_async("sess", _write_prod())
    # Worker B has a cold in-process cache, but hydrates "sess" from the shared store first.
    v2 = await worker_b.observe_async("sess", _write_prod())

    assert v2.risk > v1.risk  # B saw A's contribution — not a fresh 0-based session
    # A different session on B starts clean (no cross-session bleed).
    v_other = await worker_b.observe_async("other", _write_prod())
    assert v_other.risk == pytest.approx(v1.risk)


# --- concurrency: parallel same-session calls must not lose an update (DD-16) -------


@pytest.mark.asyncio
async def test_concurrent_same_session_does_not_lose_updates():
    """The agent runtime fans workers out in parallel within ONE session (langgraph_runner
    Map-Reduce: code_worker + ticket_worker hit the same connector with the same session_id).
    Two observe_async calls racing on one shared monitor + backend must accumulate BOTH
    increments — last-writer-wins would silently under-count risk and weaken KILL detection.

    The session is seeded first: the lost update happens on the *clobber* path
    (``self._sessions[sid] = loaded``), which only runs once the store already holds a value —
    from empty, the shared in-process dict masks the race and hides the bug."""
    # Baseline: three events applied strictly sequentially on an identical setup.
    seq = TrajectoryMonitor(store=ValkeySessionRiskStore(YieldingCache(), ttl=60))
    for _ in range(3):
        v_seq = await seq.observe_async("s", _write_prod())

    # Same three events: one to seed (so the store is non-empty), then two racing.
    monitor = TrajectoryMonitor(store=ValkeySessionRiskStore(YieldingCache(), ttl=60))
    await monitor.observe_async("s", _write_prod())
    v1, v2 = await asyncio.gather(
        monitor.observe_async("s", _write_prod()),
        monitor.observe_async("s", _write_prod()),
    )

    # The later writer sees the earlier one's contribution → totals match the sequential run.
    assert max(v1.risk, v2.risk) == pytest.approx(v_seq.risk)
    assert monitor.risk("s") == pytest.approx(v_seq.risk)


@pytest.mark.asyncio
async def test_distinct_sessions_do_not_serialize():
    """The lock is per-session: two different sessions run concurrently without blocking
    each other, and never cross-contaminate risk."""
    monitor = TrajectoryMonitor(store=ValkeySessionRiskStore(YieldingCache(), ttl=60))

    va, vb = await asyncio.gather(
        monitor.observe_async("a", _write_prod()),
        monitor.observe_async("b", _write_prod()),
    )

    assert va.risk == pytest.approx(vb.risk)  # each is a clean single-event session
    assert monitor.risk("a") == pytest.approx(va.risk)


# --- fail-soft: a backend outage never breaks the action path -----------------------


@pytest.mark.asyncio
async def test_store_failure_degrades_to_in_process():
    monitor = TrajectoryMonitor(store=ValkeySessionRiskStore(FailingCache(), ttl=60))

    verdict = await monitor.observe_async("s1", _write_prod())  # must not raise

    assert verdict.risk > 0.0
    assert monitor.risk("s1") > 0.0  # accumulated in-process despite the dead backend
