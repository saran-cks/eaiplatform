<!-- SCOPE BANNER — read first -->
> **SCOPE — INGESTION WORKER ONLY.** Chronological dev log for the standalone
> **ingestion worker** (`ingestion_worker/`) — a separate fat container, fully decoupled
> from the core-api and the model sidecars. Its **only** shared surface is data at rest in
> **Qdrant + Postgres** (+ Phoenix spans), pinned by repo-root `contracts/` and
> cross-enforced by tests on both sides. Core-API work is logged in
> `docs/core-api-dev-log.md`.

# Ingestion Worker — Build & Developer Log

## Session 1: Phases 0–2 (contract + skeleton + pure stages, non-blocking) — 2026-06-27

Built the worker end-to-end against **fakes** — every external system sits behind a port,
so the whole pipeline runs offline with no live services. Real adapters (connectors,
clamd, S3, OCR, the embedder, Qdrant/Postgres sinks) are deferred (blocking on creds/
daemons) and slot behind the existing ports later.

### Phase 0 — Contracts + cross-enforcement (committed separately, `contracts/`)
- The two containers share **no code**; the coupling is the persistence schema. Canonical,
  language-neutral artifacts in `contracts/`: `qdrant_chunk_payload.schema.json`,
  `qdrant_collection.json`, `postgres_ingestion.schema.sql`, `chunk_identity.md`.
- **Consumer-driven contract tests on both sides** validate against the same JSON Schema
  via a tiny dependency-free checker (no `jsonschema` dep — both decoupled services run it
  offline). Core-api: `src/tests/test_contract_qdrant.py`. Worker:
  `ingestion_worker/tests/test_contract_qdrant.py` (validates `Chunk.to_payload()`).
- Core-api `Chunk` gained the DD-13 fields (`screened`, `injection_risk`, `provenance`,
  `lang`, `content_hash`, `field_role`); retriever reads them; Qdrant bootstrap now indexes
  `screened` + `injection_risk`.

### Phase 1 — Worker skeleton (own domain + ports + orchestrator)
- Own models: `RawItem -> Document(blocks) -> Chunk` (frozen dataclasses); `Chunk.to_payload`
  is the producer's contract surface. `EmbeddedChunk` pairs a chunk with its vectors.
- One **port per external box**: Acquisition, Staging, AvScanner, Parser, ContentGuard,
  Embedder, Registry (Postgres), VectorSink (Qdrant).
- `IngestionPipeline` orchestrates: stage → security gate → parse → content guard →
  chunk router → per-chunk injection screen → enrich → delta/dedup → embed → dual-write.

### Phase 2 — Pure stages
- **Security gate** (pre-parse): magic-byte type check (trust bytes not extension), size
  bound, then clamd via port. Failure → quarantine, file never parsed.
- **Content guard (Fork #2 — both guards at ingest)**: abuse screen (Llama Guard → drop
  unsafe doc) + PII redaction (Presidio) at block level, then **per-chunk injection screen
  (Prompt Guard 2)** that stamps `injection_risk`/`screened` on every chunk. Injection is a
  **signal, not a gate**: high-risk chunks are stored stamped, not dropped (only abuse drops).
- **Chunk Strategy Router** by `source_type`: text/docx (heading sections, sentence-overlap
  packing), ticket (field-aware — description/resolution/notes as separate chunks), code
  (regex def/class split, kept intact; tree-sitter later), pdf (prose packed, tables
  standalone).
- **Enrich**: mints canonical `chunk_id = sha256(source⟂native_id⟂field_role⟂seq)` +
  `content_hash`, attaches provenance/permissions/lang.
- **Delta/Dedup**: pure diff of current chunks vs registry hash snapshot →
  upsert / skip-unchanged / tombstone-deleted.
- **Idempotent dual-write**: vectors→Qdrant then rows→Postgres; chunk_id idempotency makes
  retry safe. (Durable outbox/reconciliation for the non-atomic gap = Phase 3.)

### Verification
- `python -m pytest ingestion_worker/tests` → **10 passed** (field-aware chunking, injection
  stamped-not-dropped + PII redacted in one pass, abuse quarantine, infected-bytes rejected
  before parse, re-ingest no-op, deleted-field tombstone, producer contract).
- Core-api side unaffected: `pytest src/tests` → **29 passed**. Worker package ruff-clean.

### Deferred (blocking — need live systems)
Phases 3–5 are the blocking roadmap, detailed per-adapter in
**`docs/ingestion-worker-build-plan.md`**: Phase 3 (clamd / Llama Guard+Presidio / parsers
+OCR / Qdrant+Postgres sinks / worker-own bge-m3 / S3 staging + dual-write hardening),
Phase 4 (connectors), Phase 5 (Job Planner / ARQ queue / EventBridge trigger / Phoenix).
All slot behind existing ports. Live verification checklist: `docs/smoke-tests.md` ST-2.
