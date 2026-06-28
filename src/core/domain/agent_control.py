"""AgentKillRegistry — in-process ledger of agent sessions the trajectory monitor killed.

DD-11's KILL verdict surfaces as a ``TrajectoryKill`` at the MCP chokepoint. The agent
runner records the offending session here; the ``agent_reaper`` daemon drains it and
force-terminates the session as a backstop — guaranteeing the run is dead even if exception
propagation was interrupted (client disconnect, swallowed task, etc.). The registry is the
single hand-off point between the adapter that detects the kill and the daemon that reaps it.

In-process only; a Redis-backed store replaces this for multi-worker deployments (FUTURE).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KillRecord:
    agent_session_id: str
    reason: str


class AgentKillRegistry:
    """A tiny mutable set of pending kills, recorded by the runner and drained by the reaper."""

    def __init__(self) -> None:
        self._pending: dict[str, str] = {}

    def record(self, agent_session_id: str, reason: str) -> None:
        """Mark a session for reaping (last reason wins if recorded twice)."""
        self._pending[agent_session_id] = reason

    def drain(self) -> list[KillRecord]:
        """Return all pending kills and clear them (the reaper owns them after this)."""
        records = [KillRecord(sid, reason) for sid, reason in self._pending.items()]
        self._pending.clear()
        return records

    def __contains__(self, agent_session_id: object) -> bool:
        return agent_session_id in self._pending
