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

---

## Session 2: coverage for the load-bearing pure logic — 2026-06-28
Direct unit tests for the stages the Phase-1 end-to-end test only exercised via the ticket
path:
- `test_identity.py` (4) — the `chunk_id` idempotency contract (`contracts/chunk_identity.md`):
  determinism (re-ingest overwrites the same point), variation across every component,
  **unit-separator collision safety** (`('ab','c')` ≠ `('a','bc')`), content-hash sensitivity.
- `test_security_gate.py` (5) — the pre-parse static checks: empty→malformed, oversize,
  **magic-byte mismatch** (trust the bytes, not the declared type), valid PDF magic passes,
  text-without-magic passes. (Only the clamd path was covered before.)
- `test_dedup.py` (4) — `diff()` delta classification: new→upsert, unchanged→skip,
  changed-content→upsert, missing→tombstone.
- **Verification**: `python -m pytest ingestion_worker/tests -q` → **23 passed** (was 10).
  Worker stays ruff-clean.

---

## Session 3: dual-write consistency — make the safety argument explicit (DD-20) — 2026-06-30
**Target**: a Kleppmann-style review flagged the Qdrant+Postgres dual-write as a classic
non-transactional anti-pattern (Qdrant ✓ / Postgres ✗ → out of sync). Assessed it, and the
finding is that the existing shape is *already* safe for retrieval but the *reasoning* wasn't
captured and the residual risk was mis-stated.
**Steps Completed**:
- Confirmed the consistency model: core-api reads **only Qdrant**; the Postgres registry is a
  *derived* dedup index. Qdrant-first write-order means the registry can only **lag**, never
  lead — a lagging registry self-heals on the next ingest via `diff()` (re-upsert is idempotent
  by `chunk_id`); the dangerous inverse (registry leads → `diff()` skips a chunk absent from
  Qdrant → silent retrieval loss) is **structurally excluded** by the order.
- Tightened the orchestrator call-site comment from "vectors first, then registry; outbox is
  Phase-3" to spell out the ordering invariant and the one residual risk.
- Added **DD-20**: Qdrant = system of record, write-order = self-healing gap, and the durable
  outbox's *primary* justification reframed as **deletion-completeness** (a partial write to a
  doc never re-ingested leaves Qdrant points a registry-driven purge/GDPR erasure would miss),
  not retrieval correctness. Updated build-plan Fork #4 to match and extended **ST-2** with the
  never-re-ingested deletion-completeness check.
**Issues Faced & Resolved**: none — docs/comment only; no code-path change, so the 23 tests are
untouched. Deliberately did **not** build the outbox (correctly deferred Phase-3) nor reach for
2PC across the two stores (no usable cross-store atomic commit; operationally heavy).
**Verification**: `python -m pytest ingestion_worker/tests -q` → **23 passed** (unchanged);
worker ruff-clean.

---

## Session 4: first Phase-3 adapter — clamd AV scanner (Plan B: sync client via `to_thread`, fail-closed) — 2026-07-01
**Target**: build the first concrete adapter behind a worker port — `AvScannerPort` → a clamd
INSTREAM scanner — and its offline test coverage, without needing a live clamav daemon.
**Steps Completed**:
- **`adapters/av_scanner/clamd.py`** (the worker's first adapter, new `adapters/` package):
  `ClamdScanner` implements `AvScannerPort.scan(bytes) -> ScanResult` by wrapping the
  **synchronous** `clamd` client's INSTREAM command in `asyncio.to_thread`. `clamd` is imported
  **lazily** inside the client factory so the module (and its mock tests) load without the
  optional dep. Reply mapping: `{'stream': ('OK', None)}`→clean, `('FOUND', sig)`→infected+sig.
- **Fail-closed** posture (DD-22): a non-verdict (daemon down, timeout, transport error, `ERROR`
  status, garbled reply) raises **`AvScannerUnavailable`** — a new **port-level** exception
  (`ports/av_scanner.py`, so a pipeline stage can catch it without importing an adapter). The
  security gate now wraps the scan call and maps that to a `GateResult(reason="scan_error")`
  quarantine instead of crashing the batch.
- **Tests** (`test_av_scanner_clamd.py`, +9): Tier 1 mocks the client via an injected factory
  (always runs, no lib/daemon) — OK/FOUND mapping, connection-error/ERROR/garbled all fail
  closed, and the gate-quarantines-on-outage integration case. Tier 2 drives the **real** `clamd`
  client against an **in-process asyncio TCP server** speaking the INSTREAM wire protocol
  (`nINSTREAM\n` + 4-byte-length chunks → `stream: OK\n` / `... FOUND\n`) — real socket + framing
  coverage; `skipif` the lib is absent.
- Declared `clamd>=1.0.2` in the worker `pyproject.toml`.
**Issues Faced & Resolved**:
- **Tier-2 tests skipped on first run** — the worker shares the **root** uv env for `uv run
  python -m pytest` (per CLAUDE.md), and `clamd` was only added to the *worker's* pyproject;
  installed it into the active env (`uv pip install clamd`) and the 3 socket tests then ran.
- **mypy `import-untyped` + `no-any-return`** — `clamd` ships no stubs. Added
  `# type: ignore[import-untyped]` on the lazy import and assigned through a typed local
  (`client: _ClamdClient = …`) so the factory doesn't return `Any`.
- **clamd wire detail** — the sync client sends `n`-prefixed commands and reads the reply with
  `readline()`, so the fake server must answer **newline-terminated** (`stream: OK\n`), not
  null-terminated; getting this right is what makes Tier 2 exercise the true path.
**Verification**: `python -m pytest ingestion_worker/tests -q` → **32 passed** (was 23; +9,
0 skipped with `clamd` installed). `ruff check` clean; `mypy` clean on the changed files.
**Deferred**: live scan against a real clamav daemon + real EICAR file stays **ST-2** (needs a
running daemon with freshclam signatures + ~1 GB RAM — a resource constraint on this box, not a
cloud/creds one). DI wiring of `ClamdScanner` into the pipeline lands with the rest of the
Phase-3 adapters (a worker-local wiring module, per the build plan).

---

## Session 5: Phase-3 `VectorSinkPort` — Qdrant writer + a latent chunk-id contract bug (DD-23) — 2026-07-01
**Target**: build the Qdrant writer behind `VectorSinkPort` and test it fully offline against
`qdrant-client`'s in-memory engine (no daemon).
**Steps Completed**:
- **`adapters/sink/qdrant.py`** — `QdrantVectorSink` implements `upsert`/`delete` on
  `AsyncQdrantClient`. Point id = `chunk_id`; named `dense` + `sparse` vectors (sparse attached
  only when the embedder produced one); payload from `Chunk.to_payload()`. Lazily bootstraps the
  shared collection to `contracts/qdrant_collection.json` (dense Cosine @ `embed_dim`, on-disk
  sparse, the 4 payload indexes) if missing. **`wait=True`** on every write per the DD-20
  addendum (single-node read-your-writes → the Qdrant-first/registry-second ordering stays
  self-healing). Constructor takes an optional injected `client` so the whole adapter runs
  offline against a `:memory:` engine.
- **Fixed a latent contract bug (DD-23).** `chunk_id` doubles as the Qdrant point id, but Qdrant
  rejects a raw sha256 hex ("not a valid UUID"). Changed `identity.chunk_id()` to a deterministic
  **UUIDv5** over the same canonical tuple; updated `contracts/chunk_identity.md`. Same-value
  invariant preserved → **no core-api retriever change**, no payload-schema change.
- **Tests** (`test_sink_qdrant.py`, +6, all on `:memory:`): bootstrap+write, idempotent overwrite
  by `chunk_id` (count stays 1, latest text wins), delete-by-id, sparse-optional, empty-batch
  no-op (no collection created), named-vector config matches the contract. Plus
  `test_identity.py::test_chunk_id_is_a_valid_uuid` (+1) locking the UUID property.
**Issues Faced & Resolved**:
- **`/tmp` path probe swallowed output** — a throwaway probe script under git-bash `/tmp` ran via
  Windows `uv run python` resolved to a *different* `C:/tmp`, so output vanished. Moved the probe
  to the session scratchpad with a full Windows path; it then reproduced the `is not a valid UUID`
  rejection cleanly — which is what drove DD-23.
- **mypy dict-invariance at the qdrant boundary** — the named-vector map (`{"dense": [...],
  "sparse": SparseVector}`) failed `PointStruct(vector=…)`'s broad invariant union. Typed the
  local as `dict[str, Any]` (an external-lib boundary), keeping the rest strict.
- **Benign local-Qdrant warning** — "Payload indexes have no effect in the local Qdrant." Expected:
  `:memory:` mode ignores payload indexes but the bootstrap calls still succeed; the real server
  honors them. Left as-is (the warning confirms the offline test exercises the real bootstrap).
**Verification**: `python -m pytest ingestion_worker/tests -q` → **39 passed** (was 32; +7).
`src/tests/test_contract_qdrant.py` → **7 passed** (identity change didn't disturb the
cross-service contract). `ruff` + `mypy` clean on the changed files.
**Deferred**: live verification against a real (ideally clustered) Qdrant — round-trip through the
core-api retriever, crash-mid-dual-write self-heal, multi-node `consistency`/`ordering` — stays
**ST-2**. DI wiring lands with the other Phase-3 adapters.
