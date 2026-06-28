"""SessionRiskStorePort — persist DD-11 cumulative session risk across replicas.

The ``TrajectoryMonitor`` accumulates per-session risk in-process. That is correct for a
single worker but defeated by a multi-worker deployment (risk doesn't add up across
processes) and lost on restart — so the slow attack could just spread its calls. This port
lets the monitor hydrate/persist ``SessionRiskState`` from a shared backend (Valkey) so the
accumulation survives restarts and is shared across workers.

Implementations should be **fail-soft** at the call site: a backend outage degrades to
in-process accumulation (a weaker control), never an exception that breaks the action path.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.domain.policy.trajectory import SessionRiskState


@runtime_checkable
class SessionRiskStorePort(Protocol):
    async def load(self, session_id: str) -> SessionRiskState | None:
        """Return the persisted state for a session, or None if there is none."""
        ...

    async def save(self, session_id: str, state: SessionRiskState) -> None:
        """Persist (overwrite) the state for a session, refreshing its TTL."""
        ...

    async def delete(self, session_id: str) -> None:
        """Drop a session's state (called on session end / kill)."""
        ...
