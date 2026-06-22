"""RetrieverPort — embed, hybrid search (scope-filtered), and optional rerank.

Phase 1 path: ``embed`` → ``search`` (dense+sparse, RRF). ``rerank`` is part of the
contract but its adapter + pipeline branch are deferred (config flip RERANK_ENABLED).
The PermissionScope is supplied by the caller and becomes the Qdrant payload filter —
the adapter must never widen or derive it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from core.domain.entities.chunk import RetrievedChunk
from core.domain.value_objects.embedding_vector import EmbeddingVector
from core.domain.value_objects.permission_scope import PermissionScope
from core.domain.value_objects.retrieval_result import RetrievalResult


@runtime_checkable
class RetrieverPort(Protocol):
    async def embed(self, text: str) -> EmbeddingVector:
        """gRPC → bge-m3: dense + (optional) sparse vectors for the query."""
        ...

    async def search(
        self,
        *,
        query: EmbeddingVector,
        scope: PermissionScope,
        top_k: int,
        filters: Mapping[str, Any] | None = None,
    ) -> RetrievalResult:
        """Hybrid dense+sparse search with RRF fusion, filtered by scope at payload level."""
        ...

    async def rerank(
        self,
        *,
        query_text: str,
        chunks: Sequence[RetrievedChunk],
        scope: PermissionScope,
        top_k: int,
    ) -> RetrievalResult:
        """Optional cross-encoder rerank (bge-reranker-v2-m3). Deferred in phase 1."""
        ...
