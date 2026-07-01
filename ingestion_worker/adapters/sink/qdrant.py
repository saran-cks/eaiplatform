"""QdrantVectorSink — the Qdrant side of the idempotent dual-write (VectorSinkPort).

Writer-only: this worker is the SOLE writer to the shared `knowledge` collection; the
core-api retriever only reads. The point shape here MUST match what the retriever reads —
named `dense` + `sparse` vectors and the payload from `Chunk.to_payload()` — both pinned in
`contracts/` and cross-enforced by the producer contract test.

`wait=True` on every write is deliberate (DD-20 addendum): on a single node it gives the
writer read-your-writes — the upsert is ACK'd only once the point is durable *and*
searchable — which is what makes the Qdrant-first / registry-second ordering in the
orchestrator a self-healing safety property rather than a race. A batch writer can afford
the latency. `# FUTURE EXTENSION`: set read `consistency` / write `ordering` when Qdrant
goes multi-node.

The point id is `chunk_id`, a UUIDv5 (DD-23) — Qdrant rejects a raw sha256 hex id — so a
re-ingest of an unchanged chunk overwrites the same point (idempotent) and a delete-at-
source removes exactly the tombstoned ids.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from ingestion_worker.config import Config
from ingestion_worker.domain.chunk import EmbeddedChunk

# Payload fields the retriever filters on — indexed to match contracts/qdrant_collection.json.
_PAYLOAD_INDEXES: tuple[tuple[str, models.PayloadSchemaType], ...] = (
    ("tenant_id", models.PayloadSchemaType.KEYWORD),
    ("permissions", models.PayloadSchemaType.KEYWORD),
    ("screened", models.PayloadSchemaType.BOOL),
    ("injection_risk", models.PayloadSchemaType.FLOAT),
)


class QdrantVectorSink:
    """VectorSinkPort backed by Qdrant. Idempotent upsert by `chunk_id`, delete by id."""

    def __init__(self, config: Config, *, client: AsyncQdrantClient | None = None) -> None:
        self._collection = config.qdrant_collection
        self._dim = config.embed_dim
        # A caller-supplied client (e.g. an in-memory `:memory:` one) makes the whole adapter
        # testable offline against a real Qdrant engine, no daemon needed.
        self._client = client or AsyncQdrantClient(
            host=config.qdrant_host,
            grpc_port=config.qdrant_grpc_port,
            prefer_grpc=True,
        )
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        if not chunks:
            return
        await self._ensure_collection()
        points = [self._to_point(ec) for ec in chunks]
        await self._client.upsert(collection_name=self._collection, points=points, wait=True)

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return
        await self._ensure_collection()
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=list(chunk_ids)),
            wait=True,
        )

    # ------------------------------------------------------------------ #
    def _to_point(self, ec: EmbeddedChunk) -> models.PointStruct:
        # Named-vector map for a point; typed Any at the qdrant boundary (its vector-arg
        # union is broad and invariant, and dense vs sparse are different shapes).
        vector: dict[str, Any] = {"dense": list(ec.dense)}
        # Sparse is optional per point; only attach it when the embedder produced one.
        if ec.sparse_indices:
            vector["sparse"] = models.SparseVector(
                indices=list(ec.sparse_indices),
                values=list(ec.sparse_values),
            )
        return models.PointStruct(
            id=ec.chunk.chunk_id,  # UUIDv5 (DD-23); == payload chunk_id
            vector=vector,
            payload=ec.chunk.to_payload(),
        )

    async def _ensure_collection(self) -> None:
        """Create the shared collection to the pinned contract if it is missing (idempotent)."""
        if self._bootstrapped:
            return
        async with self._bootstrap_lock:
            if self._bootstrapped:
                return
            if not await self._client.collection_exists(self._collection):
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config={
                        "dense": models.VectorParams(
                            size=self._dim, distance=models.Distance.COSINE
                        )
                    },
                    sparse_vectors_config={
                        "sparse": models.SparseVectorParams(
                            index=models.SparseIndexParams(on_disk=True)
                        )
                    },
                )
                for field_name, schema in _PAYLOAD_INDEXES:
                    await self._client.create_payload_index(
                        collection_name=self._collection,
                        field_name=field_name,
                        field_schema=schema,
                    )
            self._bootstrapped = True
