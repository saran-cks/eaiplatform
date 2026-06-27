"""Delta / Dedup — compare freshly built chunks against the registry snapshot.

Pure function of (current chunks, prior {chunk_id: content_hash}). Classifies each chunk
as new/changed (upsert), unchanged (skip), and finds registry chunk_ids absent from the
current set (deleted-at-source -> tombstone)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ingestion_worker.domain.chunk import Chunk


@dataclass(frozen=True, slots=True)
class DeltaPlan:
    to_upsert: list[Chunk] = field(default_factory=list)   # new or content-changed
    unchanged: list[str] = field(default_factory=list)     # chunk_ids to skip
    to_delete: list[str] = field(default_factory=list)     # chunk_ids no longer present


def diff(chunks: Sequence[Chunk], prior_hashes: Mapping[str, str]) -> DeltaPlan:
    current_ids = {c.chunk_id for c in chunks}
    plan = DeltaPlan()
    for c in chunks:
        if prior_hashes.get(c.chunk_id) == c.content_hash:
            plan.unchanged.append(c.chunk_id)
        else:
            plan.to_upsert.append(c)
    plan.to_delete.extend(cid for cid in prior_hashes if cid not in current_ids)
    return plan
