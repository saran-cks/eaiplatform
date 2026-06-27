"""RegistryPort — the Postgres side of the dual-write (doc/chunk registry + quarantine).

Contract: repo-root contracts/postgres_ingestion.schema.sql. The registry is what makes
delta/dedup possible (prior per-chunk hashes) and what records tombstones + quarantine.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    tenant_id: str
    field_role: str
    seq: int
    content_hash: str
    screened: bool
    injection_risk: float


@runtime_checkable
class RegistryPort(Protocol):
    async def get_doc_chunk_hashes(self, document_id: str) -> dict[str, str]:
        """Return {chunk_id: content_hash} currently stored for a document (for delta)."""
        ...

    async def record_chunks(self, records: Sequence[ChunkRecord]) -> None:
        """Upsert chunk-registry rows (and their parent doc_registry row)."""
        ...

    async def delete_chunks(self, chunk_ids: Sequence[str]) -> None:
        """Remove chunk-registry rows (tombstone on delete-at-source)."""
        ...

    async def record_quarantine(
        self, *, tenant_id: str | None, source: str, native_id: str | None, stage: str, reason: str
    ) -> None:
        """Append a quarantine / dead-letter row for a rejected item."""
        ...
