"""PDF chunker — layout/section-aware: prose blocks are sentence-packed; table blocks
are emitted as standalone chunks (serialized separately) so a table isn't shredded
across chunk boundaries."""

from __future__ import annotations

from ingestion_worker.domain.document import Document
from ingestion_worker.pipeline.chunkers.base import (
    DEFAULT_MAX_CHARS,
    ChunkDraft,
    pack_with_overlap,
    split_sentences,
)


def chunk_pdf(document: Document, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    seq = 0
    for block in document.blocks:
        if block.is_table:
            if block.text.strip():
                drafts.append(
                    ChunkDraft(
                        text=block.text, field_role="table", seq=seq, is_table=True, meta=block.meta
                    )
                )
                seq += 1
            continue
        for piece in pack_with_overlap(split_sentences(block.text), max_chars=max_chars):
            drafts.append(
                ChunkDraft(
                    text=piece, field_role=block.field_role or "body", seq=seq, meta=block.meta
                )
            )
            seq += 1
    return drafts
