"""One-time: export bge-m3 -> ONNX (dense + sparse heads) -> dynamic int8 -> validate.

A naive transformers/optimum export emits the **dense** pooled vector only and
silently drops bge-m3's learned-sparse head. We instead trace the model's real
layers (base encoder + ``sparse_linear``) ourselves so both heads survive, then
apply weights-only dynamic int8 quantization (no calibration data needed), then
validate dense AND sparse against the FP32 FlagEmbedding reference.

Run (sidecar venv, CPU):  python -m sidecars.model_server.scripts.export_quantize
Output:  models/bge-m3-int8.onnx  (the artifact the server loads / ships to prod)
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import config  # noqa: F401 — pins HF cache local + forces CPU

import torch
import torch.nn.functional as F
from FlagEmbedding import BGEM3FlagModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("export")

OUT_FP32 = config.models_dir / "bge-m3-fp32.onnx"   # transient: validation diff only
OUT_INT8 = config.models_dir / "bge-m3-int8.onnx"   # shipped artifact
OPSET = 18

# Queries chosen to exercise the sparse head: exact tokens, casing, multilingual.
VALIDATION_QUERIES = [
    "kubernetes pod CrashLoopBackOff after deploy",
    "why is the payment service returning 502",
    "ERROR_CODE 1429 rate limit exceeded",
    "wie konfiguriere ich TLS für den ingress",
    "成都 数据库 连接超时",
]


class M3OnnxWrapper(torch.nn.Module):
    """Traces only what we serve: dense (normalized CLS) + raw sparse token weights.

    ColBERT head is intentionally excluded. The dict-ification of sparse weights
    (token-id -> max weight, dropping special tokens) stays in Python so the graph
    is quantization-friendly.
    """

    def __init__(self, inner: torch.nn.Module) -> None:
        super().__init__()
        self.base = inner.model            # XLMRobertaModel
        self.sparse_linear = inner.sparse_linear

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor):
        hidden = self.base(
            input_ids=input_ids, attention_mask=attention_mask, return_dict=True
        ).last_hidden_state
        dense = F.normalize(hidden[:, 0], dim=-1)              # (B, 1024)
        token_weights = torch.relu(self.sparse_linear(hidden)).squeeze(-1)  # (B, seq)
        return dense, token_weights


def _sparse_dict(token_weights, input_ids, special_ids: set[int]) -> dict[int, float]:
    """Token-id -> max weight, dropping special tokens and non-positive weights.
    Mirrors FlagEmbedding's _process_token_weights so we match the wire contract."""
    result: dict[int, float] = {}
    for w, tok in zip(token_weights.tolist(), input_ids.tolist()):
        if tok in special_ids or w <= 0.0:
            continue
        if w > result.get(tok, 0.0):
            result[tok] = w
    return result


def _sparse_cosine(a: dict[int, float], b: dict[int, float]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    import math
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def main() -> None:
    config.models_dir.mkdir(parents=True, exist_ok=True)
    log.info("Loading FlagEmbedding bge-m3 (FP32 reference, CPU)...")
    flag = BGEM3FlagModel(config.model_name, use_fp16=False)
    inner = flag.model
    tok = inner.tokenizer
    special_ids = {tok.cls_token_id, tok.eos_token_id, tok.pad_token_id, tok.unk_token_id}

    # Precompute the FP32 oracle + tokenized inputs NOW, so we can free the ~2.3GB
    # FlagEmbedding model BEFORE building/saving the ONNX proto. Holding both at once
    # peaks ~5GB and segfaults on a RAM-tight box.
    log.info("Precomputing FP32 oracle for %d queries...", len(VALIDATION_QUERIES))
    oracle = []  # (np_input_ids, np_attention_mask, ref_dense, ref_sparse)
    for q in VALIDATION_QUERIES:
        ref = flag.encode([q], max_length=config.max_seq_len,
                          return_dense=True, return_sparse=True, return_colbert_vecs=False)
        e = tok([q], return_tensors="np", padding=True, truncation=True, max_length=config.max_seq_len)
        oracle.append((
            e["input_ids"], e["attention_mask"],
            torch.tensor(ref["dense_vecs"][0]),
            {int(k): float(v) for k, v in ref["lexical_weights"][0].items()},
        ))

    wrapper = M3OnnxWrapper(inner).eval()

    # --- export ---
    enc = tok(["warmup query"], return_tensors="pt", padding=True, truncation=True,
              max_length=config.max_seq_len)
    log.info("Exporting ONNX (opset %d) -> %s", OPSET, OUT_FP32.name)
    with torch.no_grad():
        # f=None returns the ONNXProgram instead of saving inline. bge-m3 FP32 is
        # ~2.2GB > protobuf's 2GB cap, so we save with external_data (weights spilled
        # to a sidecar .onnx_data file) — the inline save segfaults on that size.
        onnx_program = torch.onnx.export(
            wrapper,
            (enc["input_ids"], enc["attention_mask"]),
            input_names=["input_ids", "attention_mask"],
            output_names=["dense", "token_weights"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq"},
                "attention_mask": {0: "batch", 1: "seq"},
                "dense": {0: "batch"},
                "token_weights": {0: "batch", 1: "seq"},
            },
            opset_version=OPSET,
            dynamo=True,     # torch.export-based exporter (default since torch 2.9; needs onnxscript)
            optimize=False,  # the optimizer pass builds a >2GB in-mem ModelProto and segfaults; skip it
        )

    # Free the FP32 model (~2.3GB) before serializing the proto to keep peak RAM down.
    import gc
    del flag, inner, wrapper
    gc.collect()

    onnx_program.save(str(OUT_FP32), external_data=True)
    del onnx_program
    gc.collect()

    # --- quantize (dynamic int8, weights-only, no calibration) ---
    from onnxruntime.quantization import quantize_dynamic, QuantType
    from onnxruntime.quantization.shape_inference import quant_pre_process

    pre = config.models_dir / "bge-m3-fp32.pre.onnx"
    log.info("Pre-processing + dynamic int8 quantization -> %s", OUT_INT8.name)
    quant_pre_process(str(OUT_FP32), str(pre))
    quantize_dynamic(str(pre), str(OUT_INT8), weight_type=QuantType.QInt8)
    pre.unlink(missing_ok=True)

    # --- validate int8 vs precomputed FP32 oracle ---
    import onnxruntime as ort
    sess = ort.InferenceSession(str(OUT_INT8), providers=["CPUExecutionProvider"])

    log.info("Validating %d queries (dense + sparse vs FP32)...", len(VALIDATION_QUERIES))
    worst_dense, worst_sparse = 1.0, 1.0
    for (input_ids, attn, ref_dense, ref_sparse), q in zip(oracle, VALIDATION_QUERIES):
        dense, tw = sess.run(None, {"input_ids": input_ids, "attention_mask": attn})
        onnx_dense = torch.tensor(dense[0])
        onnx_sparse = _sparse_dict(torch.tensor(tw[0]), torch.tensor(input_ids[0]), special_ids)

        d_cos = F.cosine_similarity(ref_dense, onnx_dense, dim=0).item()
        s_cos = _sparse_cosine(ref_sparse, onnx_sparse)
        worst_dense, worst_sparse = min(worst_dense, d_cos), min(worst_sparse, s_cos)
        log.info("  dense=%.5f  sparse=%.5f  | %s", d_cos, s_cos, q[:48])

    OUT_FP32.unlink(missing_ok=True)  # keep only the shipped int8 artifact
    Path(str(OUT_FP32) + "_data").unlink(missing_ok=True)  # external-data sidecar
    Path(str(OUT_FP32) + ".data").unlink(missing_ok=True)
    size_mb = OUT_INT8.stat().st_size / 1e6
    log.info("int8 artifact: %s (%.1f MB)", OUT_INT8, size_mb)
    log.info("WORST dense cosine=%.5f  WORST sparse cosine=%.5f", worst_dense, worst_sparse)
    assert worst_dense >= 0.999, f"dense regressed: {worst_dense:.5f} < 0.999"
    assert worst_sparse >= 0.99, f"sparse regressed: {worst_sparse:.5f} < 0.99"
    log.info("PASS — both heads preserved within tolerance.")


if __name__ == "__main__":
    main()
