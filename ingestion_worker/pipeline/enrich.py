"""Enrich — turn screened ChunkDrafts into contract-ready Chunks.

Mints the canonical chunk_id + content_hash and attaches provenance, permissions, lang,
and the DD-13 screening signals. Pure: drafts + per-draft injection risk in, Chunks out.
"""

from __future__ import annotations

from collections.abc import Sequence

from ingestion_worker.domain.chunk import Chunk
from ingestion_worker.domain.document import Document
from ingestion_worker.identity import chunk_id, content_hash
from ingestion_worker.pipeline.chunkers.base import ChunkDraft


def enrich(
    document: Document,
    drafts: Sequence[ChunkDraft],
    injection_risks: Sequence[float],
) -> list[Chunk]:
    """``injection_risks[i]`` is the Prompt Guard score for ``drafts[i]``. By this point
    abuse screening + PII redaction have already run, so ``screened=True``."""
    provenance: dict[str, object] = {
        "source": document.source,
        "native_id": document.native_id,
        "source_type": document.source_type.value,
    }
    chunks: list[Chunk] = []
    for draft, risk in zip(drafts, injection_risks, strict=True):
        meta = dict(draft.meta)
        if draft.is_table:
            meta["is_table"] = True
        chunks.append(
            Chunk(
                chunk_id=chunk_id(
                    source=document.source,
                    native_id=document.native_id,
                    field_role=draft.field_role,
                    seq=draft.seq,
                ),
                document_id=document.document_id,
                tenant_id=document.tenant_id,
                text=draft.text,
                permissions=document.permissions,
                screened=True,
                injection_risk=risk,
                provenance=provenance,
                content_hash=content_hash(draft.text),
                field_role=draft.field_role,
                lang=document.lang,
                metadata=meta,
            )
        )
    return chunks
