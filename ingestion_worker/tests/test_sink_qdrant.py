"""QdrantVectorSink tests — fully offline against a real in-memory Qdrant engine.

`AsyncQdrantClient(location=":memory:")` runs Qdrant's local engine in-process — no daemon,
no network — so these exercise the *real* upsert/delete/point-id/named-vector path (and the
UUIDv5 point-id fix, DD-23), not a mock. Live verification against a clustered daemon stays
ST-2.
"""

from __future__ import annotations

from dataclasses import replace

from qdrant_client import AsyncQdrantClient

from ingestion_worker.adapters.sink.qdrant import QdrantVectorSink
from ingestion_worker.config import Config
from ingestion_worker.domain.chunk import Chunk, EmbeddedChunk
from ingestion_worker.identity import chunk_id

_DIM = 4  # tiny dense vectors keep the tests light; the real dim (1024) is config-driven.


def _config() -> Config:
    # Small dense dim + a fresh collection name; everything else is defaults.
    return replace(Config(), embed_dim=_DIM, qdrant_collection="knowledge")


def _embedded(
    *, native_id: str = "INC1", field_role: str = "body", seq: int = 0, text: str = "hello",
    dense: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4), sparse: bool = True,
) -> EmbeddedChunk:
    cid = chunk_id(source="servicenow", native_id=native_id, field_role=field_role, seq=seq)
    chunk = Chunk(
        chunk_id=cid,
        document_id=native_id,
        tenant_id="t1",
        text=text,
        permissions=frozenset({"role:agent"}),
        screened=True,
        injection_risk=0.01,
        provenance={"source": "servicenow", "native_id": native_id},
        content_hash="deadbeef",
        field_role=field_role,
    )
    return EmbeddedChunk(
        chunk=chunk,
        dense=dense,
        sparse_indices=(1, 5) if sparse else (),
        sparse_values=(0.9, 0.3) if sparse else (),
    )


async def _sink() -> tuple[QdrantVectorSink, AsyncQdrantClient]:
    client = AsyncQdrantClient(location=":memory:")
    return QdrantVectorSink(_config(), client=client), client


async def test_upsert_bootstraps_collection_and_writes_point() -> None:
    sink, client = await _sink()
    ec = _embedded()
    await sink.upsert([ec])

    assert await client.collection_exists("knowledge")
    pts = await client.retrieve("knowledge", ids=[ec.chunk.chunk_id], with_payload=True)
    assert len(pts) == 1
    # Point id IS the chunk_id (the UUIDv5) — the contract's same-value invariant (DD-23).
    assert str(pts[0].id) == ec.chunk.chunk_id
    assert pts[0].payload is not None
    assert pts[0].payload["chunk_id"] == ec.chunk.chunk_id
    assert pts[0].payload["tenant_id"] == "t1"
    assert pts[0].payload["screened"] is True


async def test_upsert_is_idempotent_by_chunk_id() -> None:
    sink, client = await _sink()
    # Same identity tuple -> same chunk_id -> re-upsert overwrites, never duplicates.
    first = _embedded(text="v1")
    second = _embedded(text="v2")
    assert first.chunk.chunk_id == second.chunk.chunk_id
    await sink.upsert([first])
    await sink.upsert([second])

    count = await client.count("knowledge")
    assert count.count == 1
    pts = await client.retrieve("knowledge", ids=[first.chunk.chunk_id], with_payload=True)
    assert pts[0].payload is not None
    assert pts[0].payload["text"] == "v2"  # latest write wins


async def test_delete_removes_points() -> None:
    sink, client = await _sink()
    ec = _embedded()
    await sink.upsert([ec])
    await sink.delete([ec.chunk.chunk_id])

    assert (await client.count("knowledge")).count == 0


async def test_sparse_vector_is_optional() -> None:
    sink, client = await _sink()
    ec = _embedded(sparse=False)
    await sink.upsert([ec])  # dense-only point must upsert cleanly
    assert (await client.count("knowledge")).count == 1


async def test_empty_upsert_and_delete_are_noops() -> None:
    sink, client = await _sink()
    await sink.upsert([])
    await sink.delete([])
    # No collection is even created for a no-op batch.
    assert not await client.collection_exists("knowledge")


async def test_named_vectors_match_the_contract() -> None:
    sink, client = await _sink()
    await sink.upsert([_embedded()])
    info = await client.get_collection("knowledge")
    assert "dense" in info.config.params.vectors  # type: ignore[operator]
    assert info.config.params.sparse_vectors is not None
    assert "sparse" in info.config.params.sparse_vectors
