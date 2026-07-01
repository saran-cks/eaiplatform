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
        self, *, tenant_id: str, limit: int = 50, session_id: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        return await self._obs.get_traces(
            tenant_id=tenant_id, limit=limit, session_id=session_id
        )

    async def evals(self, *, tenant_id: str, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        return await self._obs.get_evals(tenant_id=tenant_id, limit=limit)

    async def datasets(self, *, tenant_id: str) -> Sequence[Mapping[str, Any]]:
        return await self._obs.get_datasets(tenant_id=tenant_id)

    async def drift(self, *, tenant_id: str | None = None) -> Mapping[str, Any]:
        return await self._obs.drift_check(tenant_id=tenant_id)
