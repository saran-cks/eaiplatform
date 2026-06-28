"""PhoenixObservabilityAdapter — the production ``ObservabilityPort`` implementation.

Composes three concerns behind the neutral port:
  * **Tracing** — OpenInference spans over the existing OTel provider (``tracing.otel_span``),
    grouped into Phoenix Sessions via ``session.id``.
  * **Evals / datasets / read-side** — the lightweight ``arize-phoenix-client`` AsyncClient
    talking REST to the self-hosted Phoenix server (no embedded server, no pandas).
  * **Drift** — a Valkey-backed running-centroid signal (``EmbeddingDriftTracker``).

Every method is fail-soft: a Phoenix outage or a missing client package degrades to a
no-op / empty result and is logged — it never breaks the request path. The OTLP span
exporter (configured in ``observability/otel.py``) keeps buffering spans regardless, so
traces are not lost when only the read/eval HTTP API is unavailable.

The Phoenix *project* is selected by the OTLP ``service.name`` the exporter already sends,
so the read-side ``project_identifier`` is simply ``otel_service_name``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from adapters.observability.phoenix.drift import EmbeddingDriftTracker
from adapters.observability.phoenix.tracing import otel_span
from core.ports.observability import ObsAttr, ObservabilityPort, SpanKind

if TYPE_CHECKING:
    from config.settings import Settings
    from core.ports.cache import CachePort

logger = logging.getLogger(__name__)


class PhoenixObservabilityAdapter(ObservabilityPort):
    def __init__(self, settings: Settings, *, cache: CachePort | None = None) -> None:
        self._settings = settings
        self._tracer = trace.get_tracer("core-api")
        self._project = settings.otel_service_name
        self._base_url = settings.phoenix_http_endpoint
        self._api_key = settings.phoenix_api_key or None
        self._drift = EmbeddingDriftTracker(cache) if cache is not None else None
        self._client: Any | None = None
        self._client_failed = False

    # --- lazy phoenix client -------------------------------------------------
    def _phoenix(self) -> Any | None:
        """Lazily build the async Phoenix client; ``None`` if unavailable (fail-soft)."""
        if self._client is not None or self._client_failed:
            return self._client
        try:
            from phoenix.client import AsyncClient

            self._client = AsyncClient(base_url=self._base_url, api_key=self._api_key)
        except Exception as exc:
            self._client_failed = True
            logger.warning("Phoenix client unavailable (read/eval API disabled): %s", exc)
        return self._client

    # --- write side: spans ---------------------------------------------------
    @asynccontextmanager
    async def span(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.CHAIN,
        attributes: Mapping[str, Any] | None = None,
    ):
        async with otel_span(self._tracer, name, kind=kind, attributes=attributes) as s:
            yield s
        # Feed drift from the FINAL neutral attribute set (vectors are often set mid-span).
        await self._maybe_observe_drift(getattr(s, "neutral", attributes))

    async def _maybe_observe_drift(self, attributes: Mapping[str, Any] | None) -> None:
        if self._drift is None or not attributes:
            return
        vector = attributes.get(ObsAttr.EMBEDDING_VECTOR)
        if vector:
            tenant = str(attributes.get(ObsAttr.TENANT_ID, "default"))
            await self._drift.observe(tenant, vector)

    # --- write side: evals ---------------------------------------------------
    async def record_eval(
        self,
        *,
        span_id: str,
        name: str,
        label: str | None = None,
        score: float | None = None,
        explanation: str | None = None,
        annotator_kind: str = "LLM",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        client = self._phoenix()
        if client is None or not span_id:
            return
        try:
            await client.spans.add_span_annotation(
                span_id=span_id,
                annotation_name=name,
                annotator_kind=annotator_kind,
                label=label,
                score=score,
                explanation=explanation,
                metadata=dict(metadata) if metadata else None,
            )
        except Exception as exc:
            logger.warning("record_eval failed (span=%s name=%s): %s", span_id, name, exc)

    async def curate_dataset(
        self, *, dataset: str, examples: Sequence[Mapping[str, Any]]
    ) -> None:
        client = self._phoenix()
        if client is None or not examples:
            return
        # The phoenix client wants inputs/outputs/metadata as parallel iterables of mappings.
        # Convention: each example's "output"/"metadata" are split out; remaining keys are inputs.
        inputs: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []
        metadata: list[dict[str, Any]] = []
        for raw in examples:
            e = dict(raw)
            out = e.pop("output", None)
            meta = e.pop("metadata", None)
            inputs.append(e)
            outputs.append({"output": out} if out is not None else {})
            metadata.append(meta if isinstance(meta, dict) else {})
        try:
            await client.datasets.add_examples_to_dataset(
                dataset=dataset, inputs=inputs, outputs=outputs, metadata=metadata
            )
        except Exception:
            try:  # dataset likely doesn't exist yet → create it
                await client.datasets.create_dataset(
                    name=dataset, inputs=inputs, outputs=outputs, metadata=metadata
                )
            except Exception as exc:
                logger.warning("curate_dataset failed (%s): %s", dataset, exc)

    # --- read side -----------------------------------------------------------
    async def get_traces(
        self, *, limit: int = 50, session_id: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        client = self._phoenix()
        if client is None:
            return []
        try:
            spans = await client.spans.get_spans(
                project_identifier=self._project, limit=limit
            )
        except Exception as exc:
            logger.warning("get_traces failed: %s", exc)
            return []
        if session_id:
            spans = [s for s in spans if _attr(s, "session.id") == session_id]
        return list(spans)

    async def get_evals(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        client = self._phoenix()
        if client is None:
            return []
        try:
            spans = await client.spans.get_spans(
                project_identifier=self._project, limit=limit
            )
            span_ids = [sid for s in spans if (sid := _span_id(s))]
            if not span_ids:
                return []
            return list(
                await client.spans.get_span_annotations(
                    project_identifier=self._project, span_ids=span_ids
                )
            )
        except Exception as exc:
            logger.warning("get_evals failed: %s", exc)
            return []

    async def get_datasets(self) -> Sequence[Mapping[str, Any]]:
        client = self._phoenix()
        if client is None:
            return []
        try:
            return list(await client.datasets.list())
        except Exception as exc:
            logger.warning("get_datasets failed: %s", exc)
            return []

    async def drift_check(self, *, tenant_id: str | None = None) -> Mapping[str, Any]:
        if self._drift is None:
            return {"status": "disabled"}
        return await self._drift.compute(tenant_id)

    async def close(self) -> None:
        client = self._client
        if client is None:
            return
        for closer in ("aclose", "close"):
            fn = getattr(client, closer, None)
            if fn is None:
                continue
            try:
                result = fn()
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Phoenix client close failed: %s", exc)
            return


def _attr(span: Mapping[str, Any], key: str) -> Any:
    attrs = span.get("attributes")
    if isinstance(attrs, Mapping):
        return attrs.get(key)
    return None


def _span_id(span: Mapping[str, Any]) -> str | None:
    ctx = span.get("context")
    if isinstance(ctx, Mapping):
        sid = ctx.get("span_id")
        return str(sid) if sid else None
    return None
