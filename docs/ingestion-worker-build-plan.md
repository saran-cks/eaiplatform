<!-- SCOPE BANNER — read first -->
> **SCOPE — INGESTION WORKER ONLY.** This document covers ONLY the standalone
> **ingestion worker** (`ingestion_worker/`) — a separate fat container that acquires,
> gates, parses, guards, chunks, embeds, and dual-writes knowledge into Qdrant + Postgres.
> It is **fully decoupled** from the Core API (`src/`) and the model sidecars: **no shared
> code**, the only coupling is data at rest, pinned in [`contracts/`](../contracts/) and
> cross-enforced by tests on both sides. Chronological progress: `ingestion-worker-dev-log.md`.

# Ingestion Worker — Build Plan

## What it is
A standalone Python container that turns source systems into permission-scoped,
security-screened, retrievable chunks. Throughput-oriented, not latency-oriented — a big
batch ingest must never starve the Core API's live query path, which is why the worker
runs its **own** bge-m3 embedder rather than sharing the query sidecar.

## Pipeline (design diagram, condensed)
```
trigger → Job Planner → Queue → Acquisition (connector plugins, incremental)
  → S3 immutable staging → Security Gate (magic-byte / size / clamd, BEFORE open)
  → Parse/Extract (typed, OCR) → Normalize (Document model)
  → Content Guard (abuse-drop + PII-redact + per-chunk injection-stamp)
  → Chunk Strategy Router (text / code / ticket / pdf) → Enrich → Delta/Dedup
  → Embed (worker-own bge-m3) → Idempotent dual-write (Qdrant + Postgres)
  ⤷ rejects → Quarantine / Dead-letter ; metrics/spans → Phoenix
```

## Coupling surface (the only thing shared)
The schema of the data at rest — see [`contracts/`](../contracts/):
`qdrant_chunk_payload.schema.json`, `qdrant_collection.json`,
`postgres_ingestion.schema.sql`, `chunk_identity.md`. Both services validate against these
in their test suites; drift on either side goes red.

---

## Status

### ✅ Phase 0 — Contracts + cross-enforcement *(done — commit `e00115a`)*
Canonical schema artifacts + dependency-free contract tests on both sides. Core-API `Chunk`
gained the DD-13 fields; retriever reads them; Qdrant bootstrap indexes them.

### ✅ Phase 1 — Worker skeleton *(done — commit `b4dbaa2`)*
Own domain models (`RawItem → Document → Chunk`), a **port per external box**, and the
`IngestionPipeline` orchestrator. Runs end-to-end on fakes.

### ✅ Phase 2 — Pure stages *(done — commit `b4dbaa2`)*
Security gate (static checks), content-guard orchestration (Fork #2: both guards at
ingest), source-aware chunkers, enrich (canonical `chunk_id`), delta/dedup, idempotent
dual-write coordination. **10 tests, all on fakes, no live services.**

> Everything below is **BLOCKING** — it needs live systems / creds / native deps, so it
> was deliberately deferred. Each item fills an **existing port**, so it slots in without
> touching the orchestrator or the pure stages. Live verification: `smoke-tests.md` **ST-2**.

---

### ⛔ Phase 3 — Security, content, and persistence adapters
The real implementations behind the gate/guard/sink ports. This is the "ingest securely"
core — do it before connectors.

| Port | Adapter to build | Blocker / needs | Notes |
|------|------------------|-----------------|-------|
| `AvScannerPort` | clamd client | a running **clamav** daemon (freshclam 3–6h refresh) | INSTREAM scan of raw bytes; the static magic-byte/size checks are already pure in `security_gate.py`. |
| `ContentGuardPort` | Prompt Guard 2 + Llama Guard + Presidio | **Prompt Guard sidecar** (reuse the existing one), a **Llama Guard** endpoint, `presidio-analyzer` | `screen_injection` reuses the sidecar we already built; `screen_abuse` = Llama Guard; `redact_pii` = Presidio + regex. |
| `ParserPort` | typed parsers | `pypdf`/`python-docx`/`openpyxl`; **OCR** (Tesseract local or Textract/AWS) for scanned PDFs | docx/txt→text, pdf→text-layer (+OCR fallback +tables), csv/xlsx→rows+schema, code→raw+lang, json→fields. |
| `VectorSinkPort` | Qdrant writer | a **Qdrant** instance | upsert points (id = `chunk_id`) with named `dense`+`sparse` vectors + payload; delete by id. |
| `RegistryPort` | Postgres (asyncpg) | shared **RDS Postgres** | doc_registry / chunk_registry / quarantine per `postgres_ingestion.schema.sql`; powers delta + tombstones. |
| `EmbedderPort` | worker-own bge-m3 | model weights (FlagEmbedding/transformers), RAM | dense + sparse, batched (`INGEST_EMBED_BATCH`); dim **must == 1024** (collection contract). |
| `StagingPort` | S3 immutable staging | **S3** (or minio); IAM | write-once raw + manifest for replay/audit. |

**Dual-write hardening (Fork #4):** Qdrant + Postgres are not transactional. `chunk_id`
idempotency makes retry safe, but add a **durable outbox / reconciliation** so a crash
between the two writes self-heals (today the orchestrator notes this as a known gap).

### ⛔ Phase 4 — Connectors (incremental acquisition)
`AcquisitionPort` adapters, each owning its own cursor/delta. **Blocking on live creds**;
build against recorded fixtures first.
- ServiceNow / Zendesk — JSON, `sys_updated_on` cursor.
- GitHub App — repo tree, commit-SHA diff.
- SharePoint / Confluence — delta token.
- S3 (IAM) — ETag / version.

### ⛔ Phase 5 — Orchestration, triggers, observability
- **Job Planner** — plan jobs per source, per-source cursors, fan-out.
- **Queue** — ARQ (SQS-ready), one job per source batch; the worker process(es) consume it.
- **Trigger** — EventBridge cron and/or `POST /ingest/run`.
- **Phoenix** — OTel spans + metrics; quarantine alerts.

---

## Folder layout (current)
```
ingestion_worker/
├── domain/        # enums, document (RawItem/Document/TextBlock), chunk (+to_payload)
├── identity.py    # canonical chunk_id + content_hash
├── ports/         # acquisition, staging, av_scanner, parser, content_guard,
│                  #   embedder, registry, sink  (one per external box)
├── pipeline/      # security_gate, content-guard orchestration (in orchestrator),
│   ├── chunkers/  #   base, text, ticket, code, pdf, router
│   ├── enrich.py  dedup.py  orchestrator.py  report.py
├── config.py      # env-driven worker config
├── pyproject.toml # own deps + pytest (decoupled)
└── tests/         # fakes + end-to-end pipeline + producer contract  (10 tests)
```
Adapters land under a new `adapters/` package, bound to ports by a worker-local DI/wiring
module (Phase 3+).
