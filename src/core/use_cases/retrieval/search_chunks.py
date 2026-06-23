"""Search chunks use case.

Orchestrates embedding generation, hybrid search, and permission constraints.
"""

from __future__ import annotations

from config.settings import Settings
from core.ports.retriever import RetrieverPort
from core.domain.value_objects.permission_scope import PermissionScope
from core.domain.value_objects.retrieval_result import RetrievalResult


class SearchChunksUseCase:
    """Orchestrates query vector embedding and scope-filtered hybrid retrieval."""

    def __init__(self, retriever: RetrieverPort) -> None:
        self._retriever = retriever

    async def execute(
        self,
        *,
        query_text: str,
        scope: PermissionScope,
        limit: int = 5,
    ) -> RetrievalResult:
        # Generate dense & sparse vectors
        vector = await self._retriever.embed(query_text)

        # Retrieve documents matching vectors and PermissionScope limits
        results = await self._retriever.search(
            query=vector,
            scope=scope,
            top_k=limit,
        )

        return results
