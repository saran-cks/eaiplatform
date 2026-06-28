"""GetObservabilityDataUseCase — read-side facade backing the /observability routes.

A thin pass-through over ``ObservabilityPort`` so the API layer depends on a use-case
(not the port directly), and so any future aggregation/authorization logic has one home.
Backend-neutral: it neither knows nor cares that the implementation is Phoenix.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.ports.observability import ObservabilityPort


class GetObservabilityDataUseCase:
    def __init__(self, *, observability: ObservabilityPort) -> None:
        self._obs = observability

    async def traces(
        self, *, limit: int = 50, session_id: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        return await self._obs.get_traces(limit=limit, session_id=session_id)

    async def evals(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        return await self._obs.get_evals(limit=limit)

    async def datasets(self) -> Sequence[Mapping[str, Any]]:
        return await self._obs.get_datasets()

    async def drift(self, *, tenant_id: str | None = None) -> Mapping[str, Any]:
        return await self._obs.drift_check(tenant_id=tenant_id)
