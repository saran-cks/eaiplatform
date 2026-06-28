"""Trajectory / cumulative-session-risk domain types (DD-11).

The PDP (DD-8) is stateless: it clears each action in isolation, so it cannot see a
*chain* of individually-allowed actions drifting toward harm (slow poisoning, gradual
privilege elevation, read-then-exfiltrate). The trajectory monitor is the independent,
**stateful** complement that scores the sequence and accumulates session-level risk.

These are pure value objects + the per-session accumulator; the monitor service lives in
``core/use_cases/policy/trajectory_monitor.py``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from core.domain.policy.types import DecisionEffect, Effect, Reversibility

# Trust labels considered first-party / internal. Anything else feeding a write is "external".
FIRST_PARTY_LABELS: frozenset[str] = frozenset({"first_party", "user"})

# Ordinal sensitivity of environments, for the elevation-gradient signal.
ENV_LEVEL: dict[str, int] = {"dev": 0, "staging": 1, "prod": 2}

# How many recent actions define the window for the mutating-drift signal.
DRIFT_WINDOW = 5

_MUTATING = (Effect.WRITE, Effect.DELETE)


class RiskLevel(StrEnum):
    """The escalating response as cumulative session risk climbs."""

    OK = "ok"                          # continue
    THROTTLE = "throttle"              # slow down / add friction
    REQUIRE_APPROVAL = "require_approval"  # force human re-approval (DD-12)
    KILL = "kill"                      # terminate the session (agent_reaper)


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """One decided action, as recorded by the runtime AFTER the PDP returns."""

    effect: Effect
    reversibility: Reversibility
    environment: str
    decision: DecisionEffect                          # what the PDP returned
    data_sources: frozenset[str] = field(default_factory=frozenset)
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    target_kind: str = ""

    @property
    def is_mutating(self) -> bool:
        return self.effect in _MUTATING

    @property
    def has_external_source(self) -> bool:
        return bool(self.data_sources - FIRST_PARTY_LABELS)


@dataclass(frozen=True, slots=True)
class RiskWeights:
    """Per-signal risk increments. Tunable; tests assert behaviour, not exact scores."""

    read: float = 0.0
    read_sensitive: float = 0.05
    write: float = 0.12
    delete: float = 0.25
    irreversible: float = 0.2
    env_bonus_prod: float = 0.12
    env_bonus_staging: float = 0.04
    probing: float = 0.2               # PDP returned deny / require_approval
    exfiltrate: float = 1.5            # prior sensitive read + now external mutating write
    elevation: float = 0.4            # mutating action in a higher env than seen before
    privilege_growth: float = 0.15    # mutating action needs a not-seen-before permission
    drift: float = 0.15               # mutating action inside a mutating-dense recent window


@dataclass(frozen=True, slots=True)
class RiskThresholds:
    throttle: float = 0.5
    require_approval: float = 1.5
    kill: float = 3.0

    def level_for(self, risk: float) -> RiskLevel:
        if risk >= self.kill:
            return RiskLevel.KILL
        if risk >= self.require_approval:
            return RiskLevel.REQUIRE_APPROVAL
        if risk >= self.throttle:
            return RiskLevel.THROTTLE
        return RiskLevel.OK


@dataclass(frozen=True, slots=True)
class TrajectoryVerdict:
    level: RiskLevel
    risk: float
    signals: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.level is RiskLevel.OK


@dataclass(slots=True)
class SessionRiskState:
    """Mutable per-session accumulator. Serializable, so a future Redis-backed
    SessionRiskStore port can persist it across replicas."""

    risk: float = 0.0
    count: int = 0
    saw_sensitive_read: bool = False
    max_env_level: int = -1
    seen_permissions: set[str] = field(default_factory=set)
    recent_effects: deque[Effect] = field(default_factory=lambda: deque(maxlen=DRIFT_WINDOW))

    def record(self, event: ActionEvent, increment: float) -> None:
        self.risk += increment
        self.count += 1
        if event.effect is Effect.READ and (
            event.environment == "prod" or bool(event.data_sources & FIRST_PARTY_LABELS)
        ):
            self.saw_sensitive_read = True
        self.max_env_level = max(self.max_env_level, ENV_LEVEL.get(event.environment, 0))
        self.seen_permissions |= set(event.required_permissions)
        self.recent_effects.append(event.effect)

    # --- serialization (for the SessionRiskStore port — cross-replica persistence) ---
    def to_dict(self) -> dict[str, object]:
        return {
            "risk": self.risk,
            "count": self.count,
            "saw_sensitive_read": self.saw_sensitive_read,
            "max_env_level": self.max_env_level,
            "seen_permissions": sorted(self.seen_permissions),
            "recent_effects": [e.value for e in self.recent_effects],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SessionRiskState:
        state = cls(
            risk=float(data.get("risk", 0.0)),  # type: ignore[arg-type]
            count=int(data.get("count", 0)),  # type: ignore[arg-type]
            saw_sensitive_read=bool(data.get("saw_sensitive_read", False)),
            max_env_level=int(data.get("max_env_level", -1)),  # type: ignore[arg-type]
            seen_permissions=set(data.get("seen_permissions", [])),  # type: ignore[arg-type]
        )
        state.recent_effects = deque(
            (Effect(e) for e in data.get("recent_effects", [])),  # type: ignore[union-attr]
            maxlen=DRIFT_WINDOW,
        )
        return state
