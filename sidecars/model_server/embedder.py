"""bge-m3 embedder — dense + learned-sparse from a single forward pass.

Two interchangeable backends behind one ``encode()``, selected by ``EMBED_BACKEND``:
- ``"flag"`` (default): FlagEmbedding ``BGEM3FlagModel`` (PyTorch CPU). Reference
  impl / FP32 ground truth. Always correct; ~469ms p50 on CPU.
- ``"onnx"``: int8 ONNX via onnxruntime (CPU). Needs ``models/bge-m3-int8.onnx``
  (build it with ``scripts/export_quantize.py`` — see ``scripts/EXPORT_RUNBOOK.md``).
  Same dense+sparse wire contract, faster on CPU.

Both return ``(dense[1024], sparse_indices, sparse_values)`` for one query.
"""
from __future__ import annotations

import logging

from .config import config  # noqa: F401 — sets HF cache + CPU on import

logger = logging.getLogger(__name__)

DENSE_DIM = 1024


def sparse_weights_to_dict(token_weights, input_ids, special_ids) -> dict[int, float]:
    """Per-token-id MAX weight, dropping special tokens and non-positive weights.

    Mirrors FlagEmbedding's ``_process_token_weights``. Shared by the ONNX backend
    and the export-validation script so the two cannot drift. Accepts any iterables
    (python lists, numpy, torch scalars) — values are coerced with float()/int().
    """
    result: dict[int, float] = {}
    for w, tok in zip(token_weights, input_ids):
        w, tok = float(w), int(tok)
        if tok in special_ids or w <= 0.0:
            continue
        if w > result.get(tok, 0.0):
            result[tok] = w
    return result


class _FlagBackend:
    """FlagEmbedding BGEM3FlagModel (PyTorch CPU). FP32 reference."""

    def __init__(self) -> None:
        import torch
        from FlagEmbedding import BGEM3FlagModel

        torch.set_num_threads(config.intra_op_threads)
        logger.info("Loading %s (FlagEmbedding, cache=%s, fp16=%s)",
                    config.model_name, config.models_dir, config.use_fp16)
        self._model = BGEM3FlagModel(config.model_name, use_fp16=config.use_fp16)
        logger.info("FlagEmbedding model loaded.")

    def encode(self, text: str) -> tuple[list[float], list[int], list[float]]:
        out = self._model.encode(
            [text], batch_size=1, max_length=config.max_seq_len,
            return_dense=True, return_sparse=True, return_colbert_vecs=False,
        )
        dense = out["dense_vecs"][0].tolist()
        lexical = out["lexical_weights"][0]            # dict: token_id (str) -> weight
        indices = [int(tok) for tok in lexical]
        values = [float(w) for w in lexical.values()]
        return dense, indices, values


class _OnnxBackend:
    """int8 ONNX (onnxruntime CPU). Outputs: dense (B,1024), token_weights (B,seq)."""

    def __init__(self) -> None:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        if not config.onnx_model_path.exists():
            raise FileNotFoundError(
                f"int8 ONNX not found at {config.onnx_model_path}. Build it with "
                "scripts/export_quantize.py (see scripts/EXPORT_RUNBOOK.md), or run "
                "with EMBED_BACKEND=flag."
            )
        so = ort.SessionOptions()
        so.intra_op_num_threads = config.intra_op_threads   # benched sweet spot
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        logger.info("Loading int8 ONNX %s (intra_op=%d)",
                    config.onnx_model_path, config.intra_op_threads)
        self._sess = ort.InferenceSession(
            str(config.onnx_model_path), sess_options=so,
            providers=["CPUExecutionProvider"],
        )
        self._tok = AutoTokenizer.from_pretrained(config.model_name)
        self._special = {self._tok.cls_token_id, self._tok.eos_token_id,
                         self._tok.pad_token_id, self._tok.unk_token_id}
        logger.info("ONNX session ready.")

    def encode(self, text: str) -> tuple[list[float], list[int], list[float]]:
        enc = self._tok([text], return_tensors="np", padding=True,
                        truncation=True, max_length=config.max_seq_len)
        dense, token_weights = self._sess.run(
            None, {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]},
        )
        sparse = sparse_weights_to_dict(token_weights[0], enc["input_ids"][0], self._special)
        return dense[0].tolist(), list(sparse.keys()), list(sparse.values())


class Embedder:
    """Backend dispatcher. ``encode`` is CPU-bound and releases the GIL, so the
    server calls it from a thread pool; a single shared instance is safe."""

    def __init__(self) -> None:
        backend = config.backend.lower()
        logger.info("Embedder backend=%s", backend)
        if backend == "onnx":
            self._backend: _FlagBackend | _OnnxBackend = _OnnxBackend()
        elif backend == "flag":
            self._backend = _FlagBackend()
        else:
            raise ValueError(
                f"unknown EMBED_BACKEND={config.backend!r} (use 'flag' or 'onnx')"
            )

    def encode(self, text: str) -> tuple[list[float], list[int], list[float]]:
        """Return (dense[1024], sparse_indices, sparse_values) for one query."""
        return self._backend.encode(text)

    def warmup(self) -> None:
        self.encode("warmup")
