"""StagingPort — immutable raw staging (S3) for replay + audit + manifest."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ingestion_worker.domain.document import RawItem


@runtime_checkable
class StagingPort(Protocol):
    async def stage(self, item: RawItem) -> str:
        """Persist raw bytes immutably; return a staging reference (e.g. s3 key / manifest id)."""
        ...
