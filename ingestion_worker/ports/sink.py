"""VectorSinkPort — the Qdrant side of the idempotent dual-write."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ingestion_worker.domain.chunk import EmbeddedChunk


@runtime_checkable
class VectorSinkPort(Protocol):
    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Upsert points (id = chunk_id) with vectors + payload. Idempotent by id."""
        ...

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        """Delete points by id (tombstone on delete-at-source)."""
        ...
