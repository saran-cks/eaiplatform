"""Vendor-neutral OpenTelemetry metrics for the security/RAG control plane.

Instruments are created lazily off the global ``MeterProvider`` (configured in
``otel.py``), so before OTel init these are cheap no-ops against the global default
provider. Recording is derived centrally by the observability adapter from the neutral
span attributes it already receives — producers never call these directly, keeping the
``ObservabilityPort`` the single seam.

Metrics are pure OTel (OTLP), independent of the trace backend: they survive a swap
from Phoenix to any other backend / a Prometheus-style collector unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import metrics

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter, Histogram

_METER_NAME = "core-api.security"

# Lazily-initialised singletons (one set per process).
_policy_decisions: Counter | None = None
_trajectory_kills: Counter | None = None
_guard_blocks: Counter | None = None
_session_risk: Histogram | None = None
_eval_scores: Histogram | None = None
_llm_tokens: Counter | None = None
_retrieved_docs: Histogram | None = None


def _meter() -> metrics.Meter:
    return metrics.get_meter(_METER_NAME)


def record_policy_decision(*, effect: str, environment: str, tool: str) -> None:
    """Count PDP decisions, dimensioned by outcome / environment / tool (DD-8)."""
    global _policy_decisions
    if _policy_decisions is None:
        _policy_decisions = _meter().create_counter(
            "pdp.decisions", description="PDP decisions by effect", unit="1"
        )
    _policy_decisions.add(1, {"effect": effect, "environment": environment, "tool": tool})


def record_trajectory(*, level: str, risk: float) -> None:
    """Record a trajectory verdict: risk distribution + KILL count (DD-11)."""
    global _trajectory_kills, _session_risk
    if _session_risk is None:
        _session_risk = _meter().create_histogram(
            "trajectory.risk", description="Cumulative session risk at decision time", unit="1"
        )
    _session_risk.record(risk, {"level": level})
    if level == "kill":
        if _trajectory_kills is None:
            _trajectory_kills = _meter().create_counter(
                "trajectory.kills",
                description="Sessions killed by the trajectory monitor",
                unit="1",
            )
        _trajectory_kills.add(1)


def record_guard_block(*, label: str) -> None:
    """Count prompt-guard blocks, dimensioned by label."""
    global _guard_blocks
    if _guard_blocks is None:
        _guard_blocks = _meter().create_counter(
            "guard.blocks", description="Queries blocked by the prompt guard", unit="1"
        )
    _guard_blocks.add(1, {"label": label})


def record_eval_score(*, name: str, score: float) -> None:
    """Record an LLM-judge / human eval score (0..1) by evaluator name."""
    global _eval_scores
    if _eval_scores is None:
        _eval_scores = _meter().create_histogram(
            "eval.score", description="Eval scores (0..1) by evaluator", unit="1"
        )
    _eval_scores.record(score, {"evaluator": name})


def record_llm_tokens(*, prompt: int, completion: int) -> None:
    """Count LLM token usage."""
    global _llm_tokens
    if _llm_tokens is None:
        _llm_tokens = _meter().create_counter(
            "llm.tokens", description="LLM token usage", unit="1"
        )
    if prompt:
        _llm_tokens.add(prompt, {"kind": "prompt"})
    if completion:
        _llm_tokens.add(completion, {"kind": "completion"})


def record_retrieved_docs(*, count: int) -> None:
    """Record how many documents a retrieval returned."""
    global _retrieved_docs
    if _retrieved_docs is None:
        _retrieved_docs = _meter().create_histogram(
            "retrieval.documents", description="Documents returned per retrieval", unit="1"
        )
    _retrieved_docs.record(count)
