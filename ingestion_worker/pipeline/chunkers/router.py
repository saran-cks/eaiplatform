"""Chunk Strategy Router — pick the chunker by source_type."""

from __future__ import annotations

from ingestion_worker.domain.document import Document
from ingestion_worker.domain.enums import SourceType
from ingestion_worker.pipeline.chunkers.base import ChunkDraft
from ingestion_worker.pipeline.chunkers.code import chunk_code
from ingestion_worker.pipeline.chunkers.pdf import chunk_pdf
from ingestion_worker.pipeline.chunkers.text import chunk_text
from ingestion_worker.pipeline.chunkers.ticket import chunk_ticket


def route(document: Document) -> list[ChunkDraft]:
    """Dispatch to the source-type-appropriate chunker. Defaults to the text strategy."""
    match document.source_type:
        case SourceType.CODE:
            return chunk_code(document)
        case SourceType.TICKET:
            return chunk_ticket(document)
        case SourceType.PDF:
            return chunk_pdf(document)
        case _:
            return chunk_text(document)
