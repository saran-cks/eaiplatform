"""Ticket chunker — field-aware: description / resolution / notes become SEPARATE chunks
so retrieval can surface 'how it was resolved' independently of 'what was reported'.
Short fields stay as a single chunk; long ones are sentence-packed."""

from __future__ import annotations

from ingestion_worker.domain.document import Document
from ingestion_worker.pipeline.chunkers.base import (
    DEFAULT_MAX_CHARS,
    ChunkDraft,
    pack_with_overlap,
    split_sentences,
)


def chunk_ticket(document: Document, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    seq = 0
    for block in document.blocks:
        text = block.text.strip()
        if not text:
            continue
        role = block.field_role or "body"
        if len(text) <= max_chars:
            drafts.append(ChunkDraft(text=text, field_role=role, seq=seq, meta=block.meta))
            seq += 1
        else:
            for piece in pack_with_overlap(split_sentences(text), max_chars=max_chars):
                drafts.append(ChunkDraft(text=piece, field_role=role, seq=seq, meta=block.meta))
                seq += 1
    return drafts
