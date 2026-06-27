"""Shared chunking primitives.

A ``ChunkDraft`` is a pre-enrichment chunk: just text + where it came from. Enrichment
(ids, hashes, screening) happens later, so the chunkers stay pure and trivially testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Soft target size for a packed chunk (characters). Kept conservative for retrieval recall.
DEFAULT_MAX_CHARS = 1000

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    text: str
    field_role: str
    seq: int
    is_table: bool = False
    meta: dict[str, object] = field(default_factory=dict)


def split_sentences(text: str) -> list[str]:
    """Naive sentence split on terminal punctuation + whitespace. Pure, language-agnostic."""
    return [s.strip() for s in _SENTENCE_BOUNDARY.split(text.strip()) if s.strip()]


def pack_with_overlap(
    sentences: list[str], *, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = 1
) -> list[str]:
    """Greedily pack sentences into chunks up to ``max_chars``, carrying ``overlap``
    trailing sentences into the next chunk to preserve cross-boundary context."""
    if not sentences:
        return []
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for sent in sentences:
        if current and size + len(sent) + 1 > max_chars:
            chunks.append(" ".join(current))
            current = current[-overlap:] if overlap else []
            size = sum(len(s) + 1 for s in current)
        current.append(sent)
        size += len(sent) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks
