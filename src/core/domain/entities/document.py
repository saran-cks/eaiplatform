"""Document & Source entities — the registry side of ingested knowledge.

Ingestion itself is a separate fat worker; here these mirror the doc registry rows so
retrieval/observability can reference provenance of chunks.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SourceKind(StrEnum):
    CONFLUENCE = "confluence"
    SERVICENOW = "servicenow"
    GITHUB = "github"
    ZENDESK = "zendesk"
    UPLOAD = "upload"
    OTHER = "other"


class Source(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    kind: SourceKind = SourceKind.OTHER
    uri: str | None = None
    label: str | None = None


class Document(BaseModel):
    document_id: str
    tenant_id: str
    source: Source
    title: str | None = None
    permissions: frozenset[str] = Field(default_factory=frozenset)
    chunk_count: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)
    indexed_at: datetime | None = None
