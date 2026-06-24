<!-- SCOPE BANNER — read first -->
> **SCOPE — CROSS-CUTTING.** This is the running design-decision log for the **whole project** (Core API + sidecars + ingestion worker + frontend). It records *why* we chose things, so we stay consistent across sessions and deployables. Newest decisions at the bottom. Per-deployable build plans/logs live in their own `docs/*-build-plan.md` / `*-dev-log.md`.

# Design Decisions (running log)

## DD-1 — Embedding sidecar runs on CPU, not GPU
The model server is **always-on** and serves **one short query per request** at interactive QPS — a *latency* workload, not a *throughput* one. GPU is only justified for bulk throughput, which belongs to the ingestion worker (off-hours, ephemeral GPU). Query sidecar = CPU + (later) ONNX int8. Cheap CPU replicas scale horizontally with QPS.

## DD-2 — bge-m3 backend: FlagEmbedding first, ONNX int8 later
Phase-1 uses FlagEmbedding's reference `BGEM3FlagModel` (PyTorch CPU) because it's correct (dense + learned-sparse guaranteed) and doubles as the **FP32 ground truth** to validate a future ONNX int8 export against. ONNX int8 is deferred until benchmarks prove it's needed. Local CPU bench (12-core box): intra_op=2 → p50 830ms; **intra_op=4 → p50 469ms (sweet spot)**; intra_op=12 → 581ms (regresses). Default set to `EMBED_INTRA_OP_THREADS=4`. Still above the ~250ms target → ONNX int8 is the next lever.

## DD-3 — Embedding/inference stays in Python (not Rust/Go)
The bottleneck is the native ONNX/torch forward pass — identical in any language. A Rust/Go rewrite only replaces the thin request wrapper (microseconds vs ~100s of ms inference) while forcing us to reimplement bge-m3's sparse post-processing. The GIL concern is moot: inference releases the GIL, so the thread-pool offload already gives true parallelism. Revisit only at very high QPS for p99.

## DD-4 — Messy user queries: rewrite-before-embed, not embed-as-is
bge-m3 handles typos/casing/punctuation/multilingual for free (do **not** lowercase/scrub — it's cased; over-cleaning strips signal). But it can't condense rambling or resolve cross-turn references ("why is *it* failing?"). So a **cheap LLM (Haiku) query-rewrite** turns the messy/multi-turn input into a clean **standalone** search query, and *that* gets embedded. Two distinct texts:
- **rewritten query → embedding/retrieval** (clean, intent-focused, context-resolved)
- **raw query → answer LLM** (preserve the user's actual words/tone)

Skip the rewrite when it can't help (first turn + already-clean/standalone query); only rewrite on multi-turn or long/rambling input.

## DD-5 — Two-tier response cache
- **L1 — raw-normalized key**, checked **first**, before any LLM call. Instant/free; catches exact repeats.
- **L2 — rewritten-query key**, checked only after L1 miss (rewrite already paid to embed). Catches different phrasings of the same intent; shareable across users with the same tenant + scope because the rewrite is standalone.

Pay the rewrite only on an L1 miss. Fill L2 only with the **standalone** rewritten form (never anything carrying session-specific references), or the next user's context gets a wrong answer.

## DD-6 — Agent semantic retrieval reuses the SAME embedding sidecar
Endpoint separation (chat vs agent) is about *orchestration flow*, not about avoiding embeddings. If an agent needs **semantic** Qdrant data it MUST embed via the same sidecar (`RetrieverPort`), exposed as a scope-checked agent **tool** that reuses the chat retrieval use-case — never a second embedding model. Only **exact/filter lookups** (by `tenant_id`/`permissions`/`ticket_id`/`doc_id`) skip embedding (Qdrant payload filter / Postgres). The real-time-status agent (1a) bypasses Qdrant entirely and hits live systems via MCP. **Not built yet — implement when agent tools land** (also noted in the agent flow section of `core-api-architecture.md`).
