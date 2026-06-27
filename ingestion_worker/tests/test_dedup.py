"""dedup.diff tests — the delta classification that drives upsert / skip / tombstone."""

from __future__ import annotations

from ingestion_worker.domain.chunk import Chunk
from ingestion_worker.pipeline.dedup import diff


def _chunk(chunk_id: str, content_hash: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, document_id="d", tenant_id="t1", text="x",
        permissions=frozenset(), screened=True, injection_risk=0.0,
        provenance={}, content_hash=content_hash, field_role="body",
    )


def test_new_chunk_is_upserted():
    plan = diff([_chunk("c1", "h1")], prior_hashes={})
    assert [c.chunk_id for c in plan.to_upsert] == ["c1"]
    assert plan.unchanged == [] and plan.to_delete == []


def test_unchanged_chunk_is_skipped():
    plan = diff([_chunk("c1", "h1")], prior_hashes={"c1": "h1"})
    assert plan.to_upsert == []
    assert plan.unchanged == ["c1"]


def test_changed_content_is_upserted():
    plan = diff([_chunk("c1", "h2")], prior_hashes={"c1": "h1"})
    assert [c.chunk_id for c in plan.to_upsert] == ["c1"]
    assert plan.unchanged == []


def test_missing_chunk_is_tombstoned():
    # c2 existed before but isn't in the current set -> deleted at source.
    plan = diff([_chunk("c1", "h1")], prior_hashes={"c1": "h1", "c2": "h2"})
    assert plan.unchanged == ["c1"]
    assert plan.to_delete == ["c2"]
