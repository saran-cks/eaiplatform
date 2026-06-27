"""Text/docx chunker — structure-aware: each parsed heading section is packed into
sentence-boundary chunks with overlap."""

from __future__ import annotations

from ingestion_worker.domain.document import Document
from ingestion_worker.pipeline.chunkers.base import (
    DEFAULT_MAX_CHARS,
    ChunkDraft,
    pack_with_overlap,
    split_sentences,
)


def chunk_text(document: Document, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    seq = 0
    for block in document.blocks:
        packed = pack_with_overlap(split_sentences(block.text), max_chars=max_chars)
        for piece in packed:
            drafts.append(
                ChunkDraft(
                    text=piece, field_role=block.field_role or "body", seq=seq, meta=block.meta
                )
            )
            seq += 1
    return drafts
