"""RetrievalResult — the immutable output of a scope-filtered hybrid search.

Carries the ordered chunks plus provenance: which fusion was applied and whether a
reranker ran (phase 1: ``reranked`` is always False — reranker deferred).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.domain.entities.chunk import RetrievedChunk


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunks: tuple[RetrievedChunk, ...]
    fusion: str = "rrf"
    reranked: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return len(self.chunks) == 0

    @property
    def top_score(self) -> float | None:
        return self.chunks[0].score if self.chunks else None

    @property
    def score_spread(self) -> float | None:
        """Gap between best and worst retrieved score; drives the optional rerank decision."""
        if len(self.chunks) < 2:
            return None
        scores = [c.score for c in self.chunks]
        return max(scores) - min(scores)
