<!-- SCOPE BANNER — read first -->
> **SCOPE — EMBEDDING SIDECAR ONLY.** Chronological build/dev log for ONLY the **model server sidecar** (`sidecars/model_server/`, query-time bge-m3 embeddings over gRPC). It does **NOT** log work on the Core API (`src/`), the Prompt Guard sidecar (`sidecars/prompt_guard/`), or the **Ingestion Worker** (`ingestion_worker/`). Plan lives in `docs/embedding-sidecar-build-plan.md`.

# Embedding Sidecar — Chronological Build & Developer Log

Append one dated entry per work session. Newest at the bottom. Keep it factual:
what was built, what was decided/changed, and any errors + how they were resolved.

Entry template:
```
## Session N: <title> — <YYYY-MM-DD>
- Built:
- Decided / changed:
- Errors & resolutions:
- Next:
```

---

## Session 1: Scaffold + working gRPC server — 2026-06-24
- **Built**: full `sidecars/model_server/` package — `config.py` (env-driven, pins HF cache local + forces CPU), `embedder.py` (bge-m3 dense + learned-sparse), async `server.py` (grpc.aio, shared embedder, thread-pool offload + semaphore, warmup, graceful shutdown), standalone `tests/test_embedder.py`, `scripts/bench.py` (p50/p95), `pyproject.toml`, `Dockerfile`, `.gitignore` (models/). Canonical proto at `proto/embedding.proto`; stubs generated into `sidecars/model_server/proto/` with a `sys.path` shim so the flat `import embedding_pb2` resolves.
- **Decided / changed**: **Phase-1 backend is FlagEmbedding `BGEM3FlagModel` (PyTorch CPU), NOT ONNX int8 yet.** Rationale: (1) it's the reference impl, so dense + sparse are guaranteed correct; (2) it doubles as the FP32 ground truth the plan already requires to validate any ONNX export against; (3) ships a correct, measurable server now. ONNX int8 is deferred to phase 2, gated on `bench.py` numbers proving it's needed — consistent with the build plan's "validate sparse head vs FP32" step.
- **Contract**: matched the existing Core API client exactly — `EmbeddingService.GetEmbedding(text) -> {dense[1024], sparse{indices, values}}`. No core-app changes needed.
- **Verified**: proto stubs + `config.py` import and round-trip a response object in the main venv; all four ML-dep modules byte-compile. NOT yet run end-to-end — FlagEmbedding/torch are sidecar-only deps (correctly absent from the core venv), and the model download is deferred to the user's standalone test run.
- **Ran locally**: isolated venv (`sidecars/model_server/.venv`, torch 2.12 / transformers 5.12 / FlagEmbedding). `pytest` PASSED — dense=1024, **sparse head confirmed present** (the main risk), model cached **locally** in `models/models--BAAI--bge-m3`. `bench.py` (PyTorch CPU). **Thread-tuning** on a 12-core box: intra_op=2 → p50 830ms; **intra_op=4 → p50 469ms / p95 594ms (best)**; intra_op=12 → p50 581ms (regresses — coordination/bandwidth bound). Set default `EMBED_INTRA_OP_THREADS=4`. Still above the ~250ms target → ONNX int8 (phase 2) stacks on top.
- **Errors & resolutions**: generated `embedding_pb2_grpc.py` uses a flat `import embedding_pb2` → resolved with a `sys.path.insert` shim in `proto/__init__.py` rather than editing generated code.
- **Next**: (1) `uv pip install` sidecar deps into a venv; (2) run `pytest sidecars/model_server/tests -s` (downloads bge-m3 into `models/`, asserts dense dim + sparse head); (3) `python -m sidecars.model_server.scripts.bench` for CPU latency; (4) only then Dockerize + wire into root compose for the end-to-end test. Phase 2: ONNX int8 export + sparse-head validation; reranker; dynamic micro-batching.

