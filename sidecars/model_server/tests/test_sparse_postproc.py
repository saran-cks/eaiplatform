"""Standalone unit tests for the shared sparse post-processing — no model, no Docker.

This is the logic both the ONNX serving backend and the export-validation use to
turn per-token weights into the {token_id: weight} sparse contract. Runnable on a
RAM-tight box (imports only config, which just sets cache env vars).

Run from repo root:  pytest sidecars/model_server/tests/test_sparse_postproc.py
"""
from __future__ import annotations

import pytest

from sidecars.model_server.embedder import sparse_weights_to_dict


def test_maxpool_per_token_id() -> None:
    # token id 5 appears twice (0.3, 0.8) -> keep the MAX (0.8)
    out = sparse_weights_to_dict([0.3, 0.8, 0.5], [5, 5, 7], special_ids=set())
    assert out == {5: 0.8, 7: 0.5}


def test_drops_special_tokens() -> None:
    # 0=CLS, 2=EOS are special and must be dropped regardless of weight
    out = sparse_weights_to_dict([0.9, 0.4, 0.6], [0, 7, 2], special_ids={0, 2})
    assert out == {7: 0.4}


def test_drops_nonpositive_weights() -> None:
    out = sparse_weights_to_dict([0.0, -0.1, 0.6], [10, 11, 12], special_ids=set())
    assert out == {12: 0.6}


def test_coerces_numpy_like_scalars() -> None:
    # accepts torch/numpy scalars: emulate with a tiny scalar-wrapper
    class Scalar:
        def __init__(self, v: float) -> None:
            self._v = v
        def __float__(self) -> float:
            return float(self._v)
        def __int__(self) -> int:
            return int(self._v)

    out = sparse_weights_to_dict([Scalar(0.7)], [Scalar(9)], special_ids=set())
    assert out == {9: pytest.approx(0.7)}


def test_empty_input() -> None:
    assert sparse_weights_to_dict([], [], special_ids=set()) == {}
