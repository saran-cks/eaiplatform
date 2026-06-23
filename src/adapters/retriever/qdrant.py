"""Qdrant adapter implementing RetrieverPort.

Features hybrid search using dense vectors and sparse token indices via prefetch
fused together using Reciprocal Rank Fusion (RRF), payload filter enforcement, and
automated collection initialization.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import logging
from typing import Any
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from config.settings import Settings
from core.ports.retriever import RetrieverPort
from core.domain.entities.chunk import RetrievedChunk
from core.domain.value_objects.embedding_vector import EmbeddingVector
from core.domain.value_objects.permission_scope import PermissionScope
from core.domain.value_objects.retrieval_result import RetrievalResult
from adapters.retriever.model_server.embed_client import ModelServerEmbedClient
from adapters.retriever.model_server.rerank_client import ModelServerRerankClient

logger = logging.getLogger(__name__)


class QdrantRetrieverAdapter(RetrieverPort):
    """Retriever adapter using Qdrant vector database and gRPC sidecars."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._collection = settings.qdrant_collection
        
        # Initialize sidecar clients
        self._embed_client = ModelServerEmbedClient(settings)
        self._rerank_client = ModelServerRerankClient(settings)

        # Initialize Qdrant client using standard parameters
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_http_port,
            grpc_port=settings.qdrant_grpc_port,
            prefer_grpc=settings.qdrant_use_grpc,
            api_key=settings.qdrant_api_key or None,
        )
        
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()
        logger.info("QdrantRetrieverAdapter initialized pointing to collection: %s", self._collection)

    async def _bootstrap_collection(self) -> None:
        """Create the collection with dense and sparse index settings if missing."""
        if self._bootstrapped:
            return
        async with self._bootstrap_lock:
            if self._bootstrapped:
                return
            try:
                exists = await self._client.collection_exists(self._collection)
                if not exists:
                    logger.info("Collection '%s' not found. Bootstrapping collection schema...", self._collection)
                    await self._client.create_collection(
                        collection_name=self._collection,
                        vectors_config={
                            "dense": models.VectorParams(
                                size=self._settings.embed_dim,
                                distance=models.Distance.COSINE,
                            )
                        },
                        sparse_vectors_config={
                            "sparse": models.SparseVectorParams(
                                index=models.SparseIndexParams(
                                    on_disk=True,
                                )
                            )
                        },
                    )
                    # Create payload indexes for fast filtering
                    await self._client.create_payload_index(
                        collection_name=self._collection,
                        field_name="tenant_id",
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                    await self._client.create_payload_index(
                        collection_name=self._collection,
                        field_name="permissions",
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                    logger.info("Collection '%s' bootstrapped successfully.", self._collection)
                self._bootstrapped = True
            except Exception as e:
                logger.error("Failed to bootstrap Qdrant collection: %s", e)
                raise

    async def embed(self, text: str) -> EmbeddingVector:
        """gRPC -> bge-m3 embedding sidecar."""
        return await self._embed_client.embed(text)

    async def search(
        self,
        *,
        query: EmbeddingVector,
        scope: PermissionScope,
        top_k: int,
        filters: Mapping[str, Any] | None = None,
    ) -> RetrievalResult:
        """Enforces PermissionScope filtering and executes native Reciprocal Rank Fusion."""
        await self._bootstrap_collection()

        # Build search-time filter using scope (tenant_id and permissions check)
        must_conditions: list[models.Condition] = [
            models.FieldCondition(
                key="tenant_id",
                match=models.MatchValue(value=scope.tenant_id),
            )
        ]

        # Permissions constraint: document must have at least one allowed role matching user permissions
        if scope.permissions:
            must_conditions.append(
                models.FieldCondition(
                    key="permissions",
                    match=models.MatchAny(any=list(scope.permissions)),
                )
            )
        else:
            # Force empty fallback so no data matches permissions
            must_conditions.append(
                models.FieldCondition(
                    key="permissions",
                    match=models.MatchValue(value="__no_permissions_assigned__"),
                )
            )

        # Merge additional custom filters (e.g. source, status) if passed
        if filters:
            for k, v in filters.items():
                must_conditions.append(
                    models.FieldCondition(
                        key=k,
                        match=models.MatchValue(value=v),
                    )
                )

        qdrant_filter = models.Filter(must=must_conditions)

        # Build dense + sparse prefetches for RRF
        prefetches = [
            models.Prefetch(
                query=list(query.dense),
                using="dense",
                limit=top_k * 2,
                filter=qdrant_filter,
            )
        ]

        if query.sparse is not None:
            prefetches.append(
                models.Prefetch(
                    query=models.SparseVector(
                        indices=list(query.sparse.indices),
                        values=list(query.sparse.values),
                    ),
                    using="sparse",
                    limit=top_k * 2,
                    filter=qdrant_filter,
                )
            )

        try:
            # Perform RRF fusion query
            results = await self._client.query_points(
                collection_name=self._collection,
                prefetch=prefetches,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
            )
        except Exception as e:
            logger.error("Qdrant query execution failed: %s", e)
            raise

        # Map Qdrant points to RetrievedChunk entities
        retrieved_chunks = []
        for point in results.points:
            payload = point.payload or {}
            retrieved_chunks.append(
                RetrievedChunk(
                    chunk_id=str(point.id),
                    document_id=payload.get("document_id", ""),
                    tenant_id=payload.get("tenant_id", ""),
                    text=payload.get("text", ""),
                    permissions=frozenset(payload.get("permissions", [])),
                    metadata=payload.get("metadata", {}),
                    score=point.score,
                )
            )

        return RetrievalResult(
            chunks=tuple(retrieved_chunks),
            fusion="rrf",
            reranked=False,
        )

    async def rerank(
        self,
        *,
        query_text: str,
        chunks: Sequence[RetrievedChunk],
        scope: PermissionScope,
        top_k: int,
    ) -> RetrievalResult:
        """Call rerank stub (cross-encoder deferred in phase 1)."""
        return await self._rerank_client.rerank(
            query_text=query_text,
            chunks=chunks,
            scope=scope,
            top_k=top_k,
        )

    async def close(self) -> None:
        """Close client sessions on shutdown."""
        await self._embed_client.close()
        # AsyncQdrantClient closes automatically but close() can be called if needed
        # (qdrant AsyncQdrantClient doesn't strictly have close in older versions, but in recent versions it handles connection shutdown nicely)
        logger.info("QdrantRetrieverAdapter closed.")
