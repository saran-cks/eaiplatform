"""Reranker client contract placeholder.

Cross-encoder reranking (bge-reranker-v2-m3) is deferred for phase 1.
"""

from __future__ import annotations

from collections.abc import Sequence

from config.settings import Settings
from core.domain.entities.chunk import RetrievedChunk
from core.domain.value_objects.permission_scope import PermissionScope
from core.domain.value_objects.retrieval_result import RetrievalResult


class ModelServerRerankClient:
    """Reranker client stub/placeholder (deferred in phase 1)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def rerank(
        self,
        *,
        query_text: str,
        chunks: Sequence[RetrievedChunk],
        scope: PermissionScope,
        top_k: int,
    ) -> RetrievalResult:
        """Stub implementation that bypasses reranking.

        FUTURE EXTENSION: Implement bge-reranker-v2-m3 gRPC client connection.
        """
        # Returns the input chunks sorted by score up to top_k limit
        sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        return RetrievalResult(
            chunks=tuple(sorted_chunks[:top_k]),
            fusion="rrf",
            reranked=False,
            metadata={"detail": "rerank_skipped_deferred"},
        )
