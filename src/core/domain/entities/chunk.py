"""Chunk entities.

``Chunk`` is a unit of indexed knowledge living in Qdrant (text + permission payload).
``RetrievedChunk`` augments it with search-time scores. Permissions on the chunk are the
payload-level scoping the retriever filters against — enforced pre-LLM.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    tenant_id: str
    text: str
    permissions: frozenset[str] = Field(default_factory=frozenset)
    metadata: dict[str, object] = Field(default_factory=dict)

    # DD-13 ingest-time screening signals (written by the ingestion-worker; see
    # contracts/qdrant_chunk_payload.schema.json). Absent on legacy points => unscreened.
    screened: bool = False
    injection_risk: float = 0.0
    # Contract top-level enrichment (optional; defaults keep legacy points valid).
    provenance: dict[str, object] = Field(default_factory=dict)
    lang: str = ""
    content_hash: str = ""
    field_role: str = ""


class RetrievedChunk(Chunk):
    """A chunk returned by hybrid search, carrying fusion and optional rerank scores."""

    score: float = 0.0
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
