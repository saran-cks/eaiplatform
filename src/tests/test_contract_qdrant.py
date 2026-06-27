"""Core-api (CONSUMER) side of the Qdrant chunk-payload cross-enforcement contract.

Asserts that the core-api `Chunk` model can faithfully consume any payload the
ingestion-worker produces per `contracts/qdrant_chunk_payload.schema.json`, and that
the canonical sample validates against the schema. The worker has a mirror test on the
producer side; if either drifts from the contract, its test goes red.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.domain.entities.chunk import Chunk
from tests._contract_validator import validate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "contracts" / "qdrant_chunk_payload.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _canonical_payload() -> dict:
    """A representative payload exactly as the worker is contracted to write it."""
    return {
        "chunk_id": "a1b2c3",
        "document_id": "doc-1",
        "tenant_id": "tenant-1",
        "text": "The refund window is 30 days.",
        "permissions": ["support", "public"],
        "screened": True,
        "injection_risk": 0.0012,
        "provenance": {
            "source": "servicenow",
            "native_id": "KB0001",
            "source_type": "ticket",
            "ingested_at": "2026-06-27T00:00:00Z",
        },
        "lang": "en",
        "content_hash": "deadbeef",
        "field_role": "resolution",
        "metadata": {"heading": "Refunds"},
    }


def test_canonical_payload_is_schema_valid(schema: dict):
    assert validate(_canonical_payload(), schema) == []


def test_missing_required_security_field_is_rejected(schema: dict):
    """The DD-13 signals are REQUIRED — dropping one must fail the contract."""
    bad = _canonical_payload()
    del bad["injection_risk"]
    errors = validate(bad, schema)
    assert any("injection_risk" in e for e in errors)


def test_wrong_type_is_rejected(schema: dict):
    bad = _canonical_payload()
    bad["screened"] = "yes"  # must be boolean
    errors = validate(bad, schema)
    assert any("screened" in e for e in errors)


def test_injection_risk_out_of_range_is_rejected(schema: dict):
    bad = _canonical_payload()
    bad["injection_risk"] = 1.5  # P(...) must be in [0, 1]
    errors = validate(bad, schema)
    assert any("injection_risk" in e for e in errors)


def test_consumer_model_covers_every_required_field(schema: dict):
    """The core-api Chunk must have an attribute for every REQUIRED contract field,
    otherwise the retriever would silently drop data the worker guarantees."""
    for field in schema["required"]:
        assert field in Chunk.model_fields, f"Chunk is missing required contract field '{field}'"


def test_consumer_round_trips_a_contract_payload():
    """A contract-valid payload maps cleanly onto Chunk with the security signals intact."""
    p = _canonical_payload()
    chunk = Chunk(
        chunk_id=p["chunk_id"],
        document_id=p["document_id"],
        tenant_id=p["tenant_id"],
        text=p["text"],
        permissions=frozenset(p["permissions"]),
        metadata=p["metadata"],
        screened=p["screened"],
        injection_risk=p["injection_risk"],
        provenance=p["provenance"],
        lang=p["lang"],
        content_hash=p["content_hash"],
        field_role=p["field_role"],
    )
    assert chunk.screened is True
    assert chunk.injection_risk == pytest.approx(0.0012)
    assert chunk.provenance["source"] == "servicenow"


def test_legacy_chunk_defaults_to_unscreened():
    """A point written before DD-13 (no security fields) reads back as unscreened."""
    chunk = Chunk(chunk_id="x", document_id="d", tenant_id="t", text="hi")
    assert chunk.screened is False
    assert chunk.injection_risk == 0.0
