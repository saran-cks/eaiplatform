"""The worker's Chunk — the unit written to Qdrant.

``to_payload()`` is the producer side of the cross-service contract: it MUST emit a dict
that validates against repo-root ``contracts/qdrant_chunk_payload.schema.json``. The
worker's contract test asserts exactly that, so the core-api retriever can always read
what we write.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    document_id: str
    tenant_id: str
    text: str
    permissions: frozenset[str]
    # DD-13 ingest-screening signals — always set by the time a chunk is built.
    screened: bool
    injection_risk: float
    provenance: dict[str, object]
    content_hash: str
    field_role: str
    lang: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        """Qdrant point payload. Contract: contracts/qdrant_chunk_payload.schema.json."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "tenant_id": self.tenant_id,
            "text": self.text,
            # JSON has no set type; the retriever reads this back into a frozenset.
            "permissions": sorted(self.permissions),
            "screened": self.screened,
            "injection_risk": self.injection_risk,
            "provenance": self.provenance,
            "lang": self.lang,
            "content_hash": self.content_hash,
            "field_role": self.field_role,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk paired with its vectors, ready for the Qdrant dual-write."""

    chunk: Chunk
    dense: tuple[float, ...]
    sparse_indices: tuple[int, ...] = ()
    sparse_values: tuple[float, ...] = ()
