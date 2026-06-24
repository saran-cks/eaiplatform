<!-- SCOPE BANNER — read first -->
> **SCOPE — EMBEDDING SIDECAR ONLY.** This document covers ONLY the always-on **model server sidecar** (`sidecars/model_server/`) that serves **query-time** embeddings (and, later, reranking) to the Core API over gRPC. It does **NOT** cover the Core API (`src/`), the Prompt Guard sidecar (`sidecars/prompt_guard/`), or the **Ingestion Worker** (`ingestion_worker/`) — the ingestion worker runs its **own** bge-m3 separately and shares nothing with this sidecar. The only thing this sidecar talks to is the Core API, over the gRPC contract in `proto/`.

# Embedding Sidecar — Build Plan

## What it is
A standalone **async gRPC server** wrapping **bge-m3**. It takes short user queries and returns **dense (1024-d) + learned-sparse (lexical) weights** from a single forward pass. CPU-only — **no GPU** (one short query per request at interactive QPS is a CPU workload, not a throughput workload). Reranker (bge-reranker-v2-m3) is a later, optional add behind the same server.

## Why CPU is the right call
- Query embedding = one short text per request. The GPU is only justified for bulk throughput, which belongs to the ingestion worker.
- bge-m3 → ONNX (dynamic **int8**) gives ~1.5–4× CPU speedup over PyTorch eager. A single short query lands well inside our budget (target < ~250 ms; the LLM stream dominates end-to-end latency anyway).
- CPU Fargate replicas (~$35–70/mo each) scale horizontally with QPS — far cheaper than an always-on GPU.

## Folder layout (`sidecars/model_server/`)
```
sidecars/model_server/
├── server.py          # grpc.aio server: serve(), graceful shutdown, warmup
├── embedder.py        # bge-m3 ONNX session: encode(query) -> {dense, sparse}
├── reranker.py        # FUTURE — bge-reranker-v2-m3 (deferred)
├── config.py          # env: model path, thread counts, max_seq_len, workers
├── models/            # exported/quantized .onnx weights (GITIGNORED — never global)
├── scripts/
│   ├── export_quantize.py   # one-time: optimum export -> dynamic int8 -> validate
│   └── bench.py             # local latency/throughput check
├── tests/
│   └── test_embedder.py     # standalone: load, encode, assert shapes + sparse head
├── pyproject.toml     # own deps (onnxruntime, optimum, FlagEmbedding, grpcio) — NOT in core app
└── Dockerfile
```
**Proto contract lives in `proto/` (single source of truth)** and is generated into both this sidecar and the Core API adapter — never hand-copied.

## Model handling — local only
- Force the HuggingFace cache **inside the sidecar folder**: set `HF_HOME=sidecars/model_server/models` (and `cache_dir=`) in every script/test. Weights never touch the global venv or `~/.cache`. `models/` is gitignored.
- Prefer a **pre-converted ONNX** bge-m3 (e.g. an `optimum`-exported variant that emits dense + sparse + ColBERT). We use **dense + sparse only**; ColBERT output is ignored for phase 1.
- **Validate the sparse head survives export + quantization** — most off-the-shelf bge-m3 ONNX exports only emit dense. The export script must assert the sparse (lexical-weights) output exists and matches the FP32 reference within tolerance, or we lose the exact signal we picked bge-m3 for. Sparse weights are mapped to token ids via FlagEmbedding's sparse token-weight processor.

## How we quantize (CPU)
- **Dynamic int8 quantization** (`onnxruntime.quantization.quantize_dynamic`) — weights → int8, activations quantized on the fly. Best fit for transformers, needs **no calibration dataset**, minimal accuracy loss.
- One-time `scripts/export_quantize.py`: optimum ONNX export → `quantize_dynamic` → validate dense + sparse vs FP32 (cosine ≥ ~0.999) → save to `models/`.
- Keep an FP32 copy for the validation diff; ship only the int8 model.

## How we handle concurrency
- **`grpc.aio` async server** with one **shared `InferenceSession`** (ONNX Runtime `Run()` is thread-safe for concurrent calls).
- ONNX inference is CPU-bound and **releases the GIL**, so each request offloads its `Run()` to a **thread pool** (`run_in_executor`) — the asyncio loop never blocks.
- **Bound concurrency with a semaphore** (= worker count) and tune threads to avoid oversubscription: `workers × intra_op_num_threads ≈ physical cores`, `inter_op_num_threads = 1`. (Note: int8 speedup shrinks as core count rises, so a few workers with small intra_op beats one worker hogging all cores.)
- **FUTURE (phase 2): dynamic micro-batching** — coalesce concurrent single-query requests inside a ~5 ms window into one batched `Run()` for higher throughput under load. Deferred; single-query path ships first.

## How we optimize for best-available
- ORT graph optimization `ORT_ENABLE_ALL` + dynamic int8.
- **Warm up** the session on startup (one dummy encode) so the first real request isn't slow.
- Cap query `max_seq_len` (queries are short, e.g. ≤512) to cut compute.
- Reuse the session + preallocated buffers; no per-request model load.
- Thread tuning above; pin nothing in dev, set affinity only if we measure a win.
- `bench.py` records p50/p95 latency and QPS locally so every change is measured, not guessed.

## Build & test order (Docker stays CLOSED until the last step)
1. `pyproject.toml` + folder scaffold; pin onnxruntime/optimum/FlagEmbedding/grpcio.
2. `scripts/export_quantize.py` → produce + validate the int8 ONNX into `models/` (local cache).
3. `embedder.py` → `encode()` returning `{dense, sparse}`; **standalone `tests/test_embedder.py` passes** (load, encode, assert dense dim + non-empty sparse weights). **← all of this is plain Python, no Docker.**
4. `server.py` → grpc.aio server + warmup + graceful shutdown; smoke test with a local gRPC client.
5. `bench.py` → confirm p95 latency / QPS targets on CPU.
6. **Only now**: `Dockerfile`, wire into root `docker-compose.yml`, bring Docker back up **once** for the end-to-end test (Core API container → gRPC → this sidecar).

## Checklist
- [ ] Scaffold `sidecars/model_server/` + `pyproject.toml` (own deps)
- [ ] `proto/` embed service definition + codegen into sidecar & core adapter
- [ ] `scripts/export_quantize.py` — export + dynamic int8 + **sparse-head validation**, local `models/` cache
- [ ] `config.py` — env (model path, threads, workers, max_seq_len)
- [ ] `embedder.py` — `encode()` dense + sparse from one pass
- [ ] `tests/test_embedder.py` — standalone, passes with Docker closed
- [ ] `server.py` — grpc.aio, shared session, executor offload, semaphore, warmup
- [ ] `scripts/bench.py` — p50/p95 + QPS
- [ ] `Dockerfile` + compose wiring (last)
- [ ] End-to-end test: Core API → gRPC → sidecar (Docker up once)
- [ ] FUTURE: reranker, dynamic micro-batching

## Open decisions to confirm
- Pre-converted ONNX vs export ourselves (depends on whether a trusted variant emits the **sparse** head).
- Replica count + thread split (set after `bench.py` numbers).
