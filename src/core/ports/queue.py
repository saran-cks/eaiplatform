"""QueuePort — async job queue (ARQ on Valkey in phase 1; SQS is a FUTURE adapter).

We enqueue and track ingestion jobs; the ingestion worker itself is a separate service.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from core.domain.entities.job import JobStatus


@runtime_checkable
class QueuePort(Protocol):
    async def enqueue(
        self, *, job_name: str, payload: Mapping[str, Any], tenant_id: str
    ) -> str:
        """Enqueue a job; returns the job_id used to poll status."""
        ...

    async def get_status(self, *, job_id: str) -> JobStatus:
        ...

    async def cancel(self, *, job_id: str) -> bool:
        ...
