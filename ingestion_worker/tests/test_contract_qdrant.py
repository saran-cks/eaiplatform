"""Ingestion-worker (PRODUCER) side of the Qdrant payload cross-enforcement contract.

Asserts that what the worker actually writes — `Chunk.to_payload()` — validates against
repo-root contracts/qdrant_chunk_payload.schema.json. Mirror of the core-api consumer
test; if the worker's writer drifts from the contract, this goes red.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestion_worker.domain.chunk import Chunk
from ingestion_worker.identity import chunk_id, content_hash
from ingestion_worker.tests._contract_validator import validate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "contracts" / "qdrant_chunk_payload.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _sample_chunk() -> Chunk:
    text = "The refund window is 30 days."
    return Chunk(
        chunk_id=chunk_id(source="servicenow", native_id="KB0001", field_role="resolution", seq=0),
        document_id="servicenow:KB0001",
        tenant_id="tenant-1",
        text=text,
        permissions=frozenset({"support", "public"}),
        screened=True,
        injection_risk=0.0012,
        provenance={"source": "servicenow", "native_id": "KB0001", "source_type": "ticket"},
        content_hash=content_hash(text),
        field_role="resolution",
        lang="en",
        metadata={"heading": "Refunds"},
    )


def test_to_payload_matches_contract(schema: dict):
    assert validate(_sample_chunk().to_payload(), schema) == []


def test_payload_has_all_required_fields(schema: dict):
    payload = _sample_chunk().to_payload()
    for field in schema["required"]:
        assert field in payload, f"writer omitted required contract field '{field}'"


def test_permissions_serialized_as_json_array(schema: dict):
    """frozenset has no JSON representation — the writer must emit a list."""
    payload = _sample_chunk().to_payload()
    assert isinstance(payload["permissions"], list)


def test_injection_risk_in_range(schema: dict):
    payload = _sample_chunk().to_payload()
    assert 0.0 <= payload["injection_risk"] <= 1.0
