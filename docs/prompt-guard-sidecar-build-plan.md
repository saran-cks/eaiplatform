<!-- SCOPE BANNER — read first -->
> **SCOPE — PROMPT GUARD SIDECAR ONLY.** This document covers ONLY the **prompt guard sidecar** (`sidecars/prompt_guard/`) — a standalone **HTTP** service that screens text for prompt-injection / jailbreaks using **Llama Prompt Guard 2 (86M)**. It is a **core-project** sidecar (like `sidecars/model_server/`), CPU-only, fully decoupled. It does **NOT** cover the Core API (`src/`), the embedding sidecar, or the **Ingestion Worker**. The only thing it talks to is the Core API, over the HTTP contract below.

# Prompt Guard Sidecar — Build Plan  *(DRAFT — for review before build)*

## What it is
A small **FastAPI HTTP** service wrapping **`meta-llama/Llama-Prompt-Guard-2-86M`** — a binary classifier (**benign vs malicious**) for prompt-injection and jailbreak detection. One short text per request, interactive QPS → **CPU-only** (86M ≈ ~350MB fp32, ~tens of ms on CPU; no GPU, no RAM problem — runs locally on the dev box). Multilingual.

## Where it sits in the whole system
- **Already half-wired (config only):** `GUARD_ENABLED`, `GUARD_GATEWAY_URL=http://guard_gateway:8001`, and the `guard_gateway` Compose service (placeholder image). **This sidecar replaces that placeholder.**
- **Screens upstream of chat/agent** — Core API calls it at the very start of `/chat/{id}/message` and `/agent/{id}/run` (architecture flow **step 1**: "Prompt Guard already screened upstream"), before cache/session/embedding. Gated by `GUARD_ENABLED`.
- **The Core-API caller is SEPARATE, deferred work** (a `GuardPort` + httpx adapter + a pre-check, scope-aware). It is NOT part of this sidecar. The **HTTP contract below is the frozen agreement** between the two — same role the `proto/` file plays for the embedding sidecar. Build the sidecar to this contract; wire the caller later.

## HTTP contract (frozen — Core API ↔ guard)
```
POST /guard      {"text": "<user prompt>"}
  200            {"label": "benign" | "malicious", "score": 0.0-1.0, "blocked": bool}
                 # score = P(malicious); blocked = score >= GUARD_THRESHOLD
GET  /health     200 {"status": "ok"}        # readiness/liveness
```
- Sidecar **classifies only**; it does NOT decide product behavior. Enforcement (refuse / 4xx / safe message) is the Core API's call based on `blocked`.
- 4xx on empty/oversized text; 200 otherwise.

## Model handling — local only (same rule as model_server)
- Force HF cache **inside the sidecar folder** (`HF_HOME=sidecars/prompt_guard/models`); weights never touch the global venv / `~/.cache`; `models/` gitignored.
- **GATED MODEL GOTCHA:** Llama Prompt Guard 2 requires accepting Meta's license on HF + an `HF_TOKEN` to download. Document in the runbook; first download needs the token (offline after).

## Concurrency / optimization
- FastAPI + uvicorn; **one shared model instance**; inference offloaded to a **thread pool** (`run_in_executor`) — releases the GIL, event loop never blocks (same pattern as model_server, lower stakes since 86M is fast).
- Cap `max_seq_len` (512); warm up on startup; reuse the model; no per-request load.
- **ONNX int8 is DEFERRED / probably unnecessary** here — 86M fp32 on CPU is already fast, and we just learned the export is a RAM-heavy yak-shave. Ship plain `transformers` fp32 first; revisit only if `bench.py` says latency matters.

## Decoupling (like model_server)
Own folder `sidecars/prompt_guard/`, own `pyproject.toml` (transformers, torch, fastapi, uvicorn, httpx-for-tests) — NOT in the core app, own `Dockerfile`, CPU-only.

## Folder layout
```
sidecars/prompt_guard/
├── app.py            # FastAPI: POST /guard, GET /health; threadpool offload; warmup
├── classifier.py     # PG2 load + classify(text) -> (label, score)
├── config.py         # env: model name, threshold, max_seq_len, port, fail-mode
├── models/           # local HF cache (GITIGNORED)
├── scripts/bench.py  # p50/p95 latency
├── tests/test_classifier.py   # standalone: benign vs known-injection sample
├── pyproject.toml
└── Dockerfile
```

## Build & test order (Docker stays CLOSED until last)
1. `pyproject.toml` + scaffold; pin transformers/torch/fastapi/uvicorn.
2. `config.py` + `classifier.py` → `classify()`; **standalone `tests/test_classifier.py` passes** (benign sample → benign; a known injection string → malicious). Plain Python, no Docker.
3. `app.py` → FastAPI `/guard` + `/health`, threadpool offload, warmup; smoke test with curl/httpx.
4. `scripts/bench.py` → p50/p95 on CPU.
5. **Only now**: `Dockerfile`, replace the `guard_gateway` placeholder image in `docker-compose.yml`, bring Docker up once for the end-to-end test.

## Open decisions — NEED YOUR REVIEW
1. **Fail-mode when sidecar is down but `GUARD_ENABLED=true`** (this is a Core-API-caller policy, but decide now): **fail-open** (allow + loud alert; favors availability) vs **fail-closed** (block; favors security). Recommendation: **fail-open + telemetry by default, configurable to fail-closed** — blocking all chat on a guard outage is severe for an enterprise app.
2. **Block threshold** (`GUARD_THRESHOLD`, score cutoff). Default **0.5**, tunable per environment.
3. **Screen scope (phase 1)**: user query **only**. Later/optional: also screen **retrieved docs / tool outputs** for *indirect* injection (PG2 supports this). Flag as FUTURE.
4. **Transport stays HTTP** (not gRPC) — matches existing config; simple req/resp edge screen. Confirm.
5. **Action on malicious** lives in Core API (refuse / safe message / 4xx), not here. Confirm sidecar stays classify-only.
