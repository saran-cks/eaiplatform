"""OTel-backed span emission for the Phoenix adapter.

Wraps a live OpenTelemetry span behind the neutral ``ObsSpan`` so producers enrich spans
without touching the OTel API. The context manager:
  * opens a span named ``name`` with the OpenInference kind + translated attributes,
  * propagates ``session.id`` / ``user.id`` to every child span via ``using_attributes``
    (so Phoenix groups the whole request into one Session),
  * records exceptions and sets ERROR status on failure,
  * derives a few neutral OTel metrics from the same attributes on exit.

Everything is fail-soft: if anything in the tracing path raises, the caller's work still
runs — observability must never break the request path.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from adapters.observability.phoenix import semconv
from core.ports.observability import ObsAttr, SpanKind
from observability import metrics

logger = logging.getLogger(__name__)

# Optional: session/user context propagation to child spans. Lightweight dep
# (openinference-instrumentation); degrade to a no-op contextmanager if absent.
try:  # pragma: no cover - exercised only when the dep is installed
    from openinference.instrumentation import using_attributes
except Exception:  # pragma: no cover
    from contextlib import contextmanager

    @contextmanager
    def using_attributes(**_kwargs: Any):  # type: ignore[misc]
        yield


class _OtelSpan:
    """Neutral ``ObsSpan`` over a live OTel span.

    Accumulates the neutral attributes it is given (at creation and mid-span) into
    ``neutral`` so the adapter can derive metrics / drift from the *final* attribute
    set on exit — e.g. token counts and embedding vectors only known after the call.
    """

    __slots__ = ("_span", "neutral")

    def __init__(self, span: Span, neutral: dict[str, Any]) -> None:
        self._span = span
        self.neutral = neutral

    @property
    def span_id(self) -> str | None:
        ctx = self._span.get_span_context()
        if ctx is None or not ctx.is_valid:
            return None
        return format(ctx.span_id, "016x")

    def set_attribute(self, key: str, value: Any) -> None:
        if value is None:
            return
        self.neutral[key] = value
        try:
            for k, v in semconv.translate_attrs({key: value}).items():
                self._span.set_attribute(k, v)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("span.set_attribute failed (%s): %s", key, exc)

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        self.neutral.update(attributes)
        try:
            for k, v in semconv.translate_attrs(attributes).items():
                self._span.set_attribute(k, v)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("span.set_attributes failed: %s", exc)

    def record_exception(self, exc: BaseException) -> None:
        self._span.record_exception(exc)

    def set_error(self, message: str) -> None:
        self._span.set_status(Status(StatusCode.ERROR, message))


@asynccontextmanager
async def otel_span(
    tracer: trace.Tracer,
    name: str,
    *,
    kind: SpanKind,
    attributes: Mapping[str, Any] | None,
):
    """Open a kind-tagged OpenInference span; yield a neutral ``ObsSpan``."""
    attrs = dict(attributes or {})
    session_id = attrs.get(ObsAttr.SESSION_ID)
    user_id = attrs.get(ObsAttr.USER_ID)
    try:
        oi_attrs = semconv.to_openinference(kind, attrs)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("attribute translation failed for span %s: %s", name, exc)
        oi_attrs = {}

    with using_attributes(
        session_id=str(session_id) if session_id else None,
        user_id=str(user_id) if user_id else None,
    ):
        with tracer.start_as_current_span(name, attributes=oi_attrs) as span:
            obs = _OtelSpan(span, dict(attrs))
            try:
                yield obs
            except BaseException as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                _derive_metrics(obs.neutral)
                raise
            _derive_metrics(obs.neutral)


def _derive_metrics(attrs: Mapping[str, Any]) -> None:
    """Emit neutral OTel metrics from the span's neutral attributes (best-effort)."""
    try:
        if ObsAttr.POLICY_DECISION in attrs:
            metrics.record_policy_decision(
                effect=str(attrs.get(ObsAttr.POLICY_DECISION)),
                environment=str(attrs.get(ObsAttr.POLICY_ENVIRONMENT, "unknown")),
                tool=str(attrs.get(ObsAttr.TOOL_NAME, "unknown")),
            )
        if ObsAttr.RISK_SCORE in attrs:
            metrics.record_trajectory(
                level=str(attrs.get(ObsAttr.RISK_LEVEL, "ok")),
                risk=float(attrs.get(ObsAttr.RISK_SCORE, 0.0)),
            )
        if attrs.get(ObsAttr.GUARD_BLOCKED):
            metrics.record_guard_block(label=str(attrs.get(ObsAttr.GUARD_LABEL, "unknown")))
        if ObsAttr.LLM_TOKENS_INPUT in attrs or ObsAttr.LLM_TOKENS_OUTPUT in attrs:
            metrics.record_llm_tokens(
                prompt=int(attrs.get(ObsAttr.LLM_TOKENS_INPUT, 0) or 0),
                completion=int(attrs.get(ObsAttr.LLM_TOKENS_OUTPUT, 0) or 0),
            )
        docs = attrs.get(ObsAttr.RETRIEVAL_DOCUMENTS)
        if isinstance(docs, (list, tuple)):
            metrics.record_retrieved_docs(count=len(docs))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("metric derivation failed: %s", exc)
