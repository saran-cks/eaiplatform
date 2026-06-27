"""The worker's intermediate domain models.

Flow of types through the pipeline:

    RawItem        -- acquisition output: raw bytes + native metadata
      -> Document  -- parsed + normalized common model {blocks, meta}
        -> Chunk   -- routed/enriched unit written to Qdrant (see chunk.py)

These are the worker's OWN models. They are not shared with the core-api; only the
final Qdrant payload (Chunk.to_payload) is contract-bound.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ingestion_worker.domain.enums import SourceType


@dataclass(frozen=True, slots=True)
class RawItem:
    """A single acquired item, before the file is ever opened/parsed."""

    source: str                       # connector id, e.g. "servicenow"
    native_id: str                    # source's own id for the record/document
    tenant_id: str
    source_type: SourceType
    permissions: frozenset[str]
    content_type: str                 # declared mime; verified by the security gate
    raw: bytes
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A logical span of a parsed document. For structured sources each field is a block."""

    text: str
    field_role: str = "body"          # "body" | "description" | "resolution" | "function:foo" | ...
    order: int = 0
    is_table: bool = False            # pdf/csv tables are serialized + chunked separately
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Document:
    """Normalized common model emitted by the parser."""

    source: str
    native_id: str
    tenant_id: str
    source_type: SourceType
    permissions: frozenset[str]
    blocks: tuple[TextBlock, ...]
    lang: str = ""
    meta: dict[str, object] = field(default_factory=dict)

    @property
    def document_id(self) -> str:
        """Stable parent id within the tenant: '{source}:{native_id}'."""
        return f"{self.source}:{self.native_id}"
