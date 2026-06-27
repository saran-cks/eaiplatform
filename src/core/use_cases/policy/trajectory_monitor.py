"""TrajectoryMonitor — independent, stateful cumulative-session-risk scorer (DD-11).

The runtime calls ``observe(session_id, event)`` after every PDP decision. The monitor
accumulates session-level risk from the *shape* of the action sequence — not any single
action — and returns an escalating verdict (OK → THROTTLE → REQUIRE_APPROVAL → KILL).

DD-8 stops the single catastrophic action; this stops the slow accumulation. Neither
alone is sufficient: a chain where every step is individually PDP-allowed still trips
this monitor (asserted by the "thousand small cuts" test).

Session state is in-memory here; a Redis-backed ``SessionRiskStore`` port can persist
``SessionRiskState`` across replicas later (it is a plain serializable dataclass).
"""

from __future__ import annotations

from core.domain.policy.trajectory import (
    DRIFT_WINDOW,
    ENV_LEVEL,
    ActionEvent,
    RiskThresholds,
    RiskWeights,
    SessionRiskState,
    TrajectoryVerdict,
)
from core.domain.policy.types import DecisionEffect, Effect, Reversibility

_DRIFT_DENSITY = 0.6  # fraction of the recent window that must be mutating to count as drift


class TrajectoryMonitor:
    def __init__(
        self,
        *,
        weights: RiskWeights | None = None,
        thresholds: RiskThresholds | None = None,
    ) -> None:
        self._w = weights or RiskWeights()
        self._t = thresholds or RiskThresholds()
        self._sessions: dict[str, SessionRiskState] = {}

    def observe(self, session_id: str, event: ActionEvent) -> TrajectoryVerdict:
        state = self._sessions.setdefault(session_id, SessionRiskState())
        increment, signals = self._score(state, event)
        state.record(event, increment)
        return TrajectoryVerdict(
            level=self._t.level_for(state.risk), risk=state.risk, signals=tuple(signals)
        )

    def risk(self, session_id: str) -> float:
        state = self._sessions.get(session_id)
        return state.risk if state else 0.0

    def reset(self, session_id: str) -> None:
        """Clear state on session end (called by the runtime / agent_reaper)."""
        self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    def _score(self, state: SessionRiskState, event: ActionEvent) -> tuple[float, list[str]]:
        w = self._w
        signals: list[str] = []
        inc = 0.0

        # Base increment by effect.
        if event.effect is Effect.READ:
            sensitive = event.environment == "prod" or bool(
                event.data_sources & {"first_party", "user"}
            )
            inc += w.read_sensitive if sensitive else w.read
        elif event.effect is Effect.WRITE:
            inc += w.write
        elif event.effect is Effect.DELETE:
            inc += w.delete

        # Environment + irreversibility raise the stakes of a mutating action.
        if event.is_mutating:
            if event.environment == "prod":
                inc += w.env_bonus_prod
            elif event.environment == "staging":
                inc += w.env_bonus_staging
        if event.reversibility is Reversibility.IRREVERSIBLE:
            inc += w.irreversible

        # Probing: the agent is hitting walls (PDP didn't allow) — a suspicious sequence shape.
        if event.decision is not DecisionEffect.ALLOW:
            inc += w.probing
            signals.append("probing")

        # Read-then-exfiltrate: a prior sensitive read, now a mutating write to an external sink.
        if event.is_mutating and state.saw_sensitive_read and event.has_external_source:
            inc += w.exfiltrate
            signals.append("read_then_exfiltrate")

        # Elevation gradient: a mutating action in a higher environment than seen before.
        env_level = ENV_LEVEL.get(event.environment, 0)
        if event.is_mutating and state.count > 0 and env_level > state.max_env_level:
            inc += w.elevation
            signals.append("elevation_gradient")

        # Privilege growth: a mutating action needing a permission not used earlier this session.
        new_perms = event.required_permissions - state.seen_permissions
        if event.is_mutating and state.seen_permissions and new_perms:
            inc += w.privilege_growth * len(new_perms)
            signals.append("privilege_growth")

        # Mutating drift: the recent window has become mutating-dense.
        if event.is_mutating and len(state.recent_effects) >= DRIFT_WINDOW:
            mutating_recent = sum(
                1 for e in state.recent_effects if e in (Effect.WRITE, Effect.DELETE)
            )
            if mutating_recent / len(state.recent_effects) >= _DRIFT_DENSITY:
                inc += w.drift
                signals.append("mutating_drift")

        return inc, signals
