# Cross-service contracts

The **core-api** (`src/`) and the **ingestion-worker** (`ingestion_worker/`) are
**separate deployables in separate containers with no shared code**. They are coupled
*only* through data at rest in three shared backing services:

- **Qdrant** — the ingestion-worker is the **producer** of chunk points; the core-api
  retriever is the **consumer**.
- **Postgres (RDS)** — shared `doc_registry` / chunk-hash / quarantine tables.
- **Phoenix** — observability only; spans, no hard data contract.

Because there is no shared Python package to keep them honest, the schema of that
shared data **is** the API between the two services. These files are the canonical,
language-neutral definition of that schema. **Both sides have a contract test that
validates their own read/write model against the files here.** If either service
renames or retypes a field the other depends on, that side's contract test goes red —
that is the "cross-enforcement" guarantee.

## Files

| File | Defines | Producer | Consumer |
|------|---------|----------|----------|
| `qdrant_chunk_payload.schema.json` | JSON Schema of a Qdrant point payload | ingestion-worker | core-api retriever |
| `qdrant_collection.json` | Collection name, vector config, payload indexes | (bootstrap) | both |
| `postgres_ingestion.schema.sql` | Ingestion-owned Postgres tables | ingestion-worker | core-api (reads doc_registry) |
| `chunk_identity.md` | The canonical `chunk_id` derivation | ingestion-worker | both |

## Versioning / change rules

- **Additive is safe.** A producer may add new payload fields; `additionalProperties`
  is `true`, so consumers ignore what they don't know.
- **Rename or retype of a listed field is BREAKING.** Bump the `v<N>` in the schema
  title, update both sides in lockstep, and keep the contract tests green.
- The DD-13 security fields (`screened`, `injection_risk`) are **required** — every
  chunk the worker writes must carry them; the retriever relies on them existing.
