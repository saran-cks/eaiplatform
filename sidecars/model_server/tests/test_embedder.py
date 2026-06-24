"""Standalone embedder test — no Docker, no gRPC.

First run downloads bge-m3 into sidecars/model_server/models/ (local cache
only). Run from repo root:  pytest sidecars/model_server/tests -s
"""
from __future__ import annotations

from sidecars.model_server.embedder import DENSE_DIM, Embedder


def test_encode_dense_and_sparse() -> None:
    emb = Embedder()
    dense, indices, values = emb.encode("How do I reset a failed deployment?")

    # dense: fixed 1024-d float vector
    assert len(dense) == DENSE_DIM
    assert all(isinstance(x, float) for x in dense[:5])

    # learned-sparse head must produce aligned, non-negative weights
    assert len(indices) > 0
    assert len(indices) == len(values)
    assert all(v >= 0.0 for v in values)
