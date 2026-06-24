"""bge-m3 embedder — dense + learned-sparse from a single forward pass.

Phase-1 backend is FlagEmbedding's reference ``BGEM3FlagModel`` (correct dense
vectors + lexical/sparse weights, CPU-capable). It also serves as the FP32
ground truth for a later ONNX int8 export — see
docs/embedding-sidecar-build-plan.md.
"""
from __future__ import annotations

import logging

from .config import config  # noqa: F401 — sets HF cache + CPU on import

import torch
from FlagEmbedding import BGEM3FlagModel

logger = logging.getLogger(__name__)

DENSE_DIM = 1024


class Embedder:
    """Wrapper around bge-m3. ``encode`` is CPU-bound and releases the GIL, so
    the server calls it from a thread pool; a single shared instance is safe."""

    def __init__(self) -> None:
        torch.set_num_threads(config.intra_op_threads)
        logger.info(
            "Loading %s (cache=%s, fp16=%s)",
            config.model_name, config.models_dir, config.use_fp16,
        )
        self._model = BGEM3FlagModel(config.model_name, use_fp16=config.use_fp16)
        logger.info("Model loaded.")

    def encode(self, text: str) -> tuple[list[float], list[int], list[float]]:
        """Return (dense[1024], sparse_indices, sparse_values) for one query."""
        out = self._model.encode(
            [text],
            batch_size=1,
            max_length=config.max_seq_len,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = out["dense_vecs"][0].tolist()
        lexical = out["lexical_weights"][0]  # dict: token_id (str) -> weight (float)
        indices = [int(tok) for tok in lexical]
        values = [float(w) for w in lexical.values()]
        return dense, indices, values

    def warmup(self) -> None:
        self.encode("warmup")
