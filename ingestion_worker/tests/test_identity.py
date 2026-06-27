"""chunk_id / content_hash tests — the idempotency contract (contracts/chunk_identity.md).

Determinism is what makes re-ingest idempotent (same point overwritten) and the unit
separator is what stops field-boundary collisions. Both are load-bearing for the
delta/dedup + dual-write logic, so they get a direct test, not just pipeline coverage.
"""

from __future__ import annotations

from ingestion_worker.identity import chunk_id, content_hash


def test_chunk_id_is_deterministic():
    a = chunk_id(source="servicenow", native_id="INC1", field_role="resolution", seq=0)
    b = chunk_id(source="servicenow", native_id="INC1", field_role="resolution", seq=0)
    assert a == b


def test_chunk_id_varies_with_every_component():
    base = dict(source="servicenow", native_id="INC1", field_role="resolution", seq=0)
    variants = [
        {**base, "source": "zendesk"},
        {**base, "native_id": "INC2"},
        {**base, "field_role": "description"},
        {**base, "seq": 1},
    ]
    ids = {chunk_id(**base)} | {chunk_id(**v) for v in variants}
    assert len(ids) == len(variants) + 1  # all distinct


def test_unit_separator_prevents_boundary_collisions():
    """('ab','c') must not collide with ('a','bc') — the separator guarantees this."""
    left = chunk_id(source="ab", native_id="c", field_role="body", seq=0)
    right = chunk_id(source="a", native_id="bc", field_role="body", seq=0)
    assert left != right


def test_content_hash_is_deterministic_and_content_sensitive():
    assert content_hash("hello") == content_hash("hello")
    assert content_hash("hello") != content_hash("hello ")
