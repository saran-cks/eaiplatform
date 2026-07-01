"""NoOpObservability — the safe default when observability is disabled.

Mirrors ``NullGuardAdapter``: a real, explicit implementation of ``ObservabilityPort``
that does nothing, so producers can always call the port unconditionally without
``if obs is not None`` guards. Every method is a cheap no-op; ``span`` yields an
inert ``ObsSpan`` whose mutators are ignored.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from core.ports.observability import ObservabilityPort, SpanKind


class _NoOpSpan:
    """An ObsSpan that swallows every enrichment call."""

    __slots__ = ()

    @property
    def span_id(self) -> str | None:
        return None

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        pass

    def record_exception(self, exc: BaseException) -> None:
        pass

    def set_error(self, message: str) -> None:
        pass


_SPAN = _NoOpSpan()


class NoOpObservability(ObservabilityPort):
    """Does nothing, safely. Bound when ``OTEL_ENABLED`` is false."""

    @asynccontextmanager
    async def span(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.CHAIN,
        attributes: Mapping[str, Any] | None = None,
    ):
        yield _SPAN

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
        pass

    async def curate_dataset(
        self, *, tenant_id: str, dataset: str, examples: Sequence[Mapping[str, Any]]
    ) -> None:
        pass

    async def get_traces(
        self, *, tenant_id: str, limit: int = 50, session_id: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        return []

    async def get_evals(
        self, *, tenant_id: str, limit: int = 50
    ) -> Sequence[Mapping[str, Any]]:
        return []

    async def get_datasets(self, *, tenant_id: str) -> Sequence[Mapping[str, Any]]:
        return []

    async def drift_check(self, *, tenant_id: str | None = None) -> Mapping[str, Any]:
        return {"status": "disabled"}

    async def close(self) -> None:
        pass
