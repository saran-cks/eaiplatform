"""ObservabilityPort — tracing, evals, drift, dataset curation (Phoenix adapter).

Write side: spans + evals + dataset curation flow to Phoenix via OTLP/HTTP.
Read side: the /observability routes query back through these methods, so Phoenix can be
swapped by replacing the adapter only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ObservabilityPort(Protocol):
    def span(
        self, name: str, *, attributes: Mapping[str, Any] | None = None
    ) -> AbstractAsyncContextManager[Any]:
        """Open a traced span as an async context manager."""
        ...

    async def record_eval(
        self,
        *,
        turn_id: str,
        name: str,
        score: float,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Ingest a retrieval-quality or LLM eval (faithfulness/relevance) for a turn."""
        ...

    async def curate_dataset(
        self, *, dataset: str, turn_ids: Sequence[str]
    ) -> None:
        """Add real traffic turns to a labeled Phoenix dataset for offline eval."""
        ...

    async def drift_check(
        self, *, tenant_id: str | None = None
    ) -> Mapping[str, Any]:
        """Query embedding drift between query-time and ingestion-time vector spaces."""
        ...

    # --- read side for /observability routes ---
    async def get_traces(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        ...

    async def get_evals(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        ...

    async def get_datasets(self) -> Sequence[Mapping[str, Any]]:
        ...
