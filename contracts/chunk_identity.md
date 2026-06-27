# Chunk identity contract

The Qdrant point id and payload `chunk_id` are the **same value**, derived
deterministically so that re-ingesting an unchanged source is **idempotent** (the
upsert overwrites the same point) and a changed chunk lands on a stable id.

## Formula

```
chunk_id = sha256( "{source}\x1f{native_id}\x1f{field_role}\x1f{seq}" ).hexdigest()
```

- `source` — connector/source system identifier (e.g. `servicenow`, `github`).
- `native_id` — the source's own id for the parent record/document.
- `field_role` — logical field the chunk came from (`body` for unstructured;
  `description` / `resolution` / `notes` for tickets; `function:<name>` for code). Use
  the literal string `body` when a source has no field decomposition.
- `seq` — 0-based ordinal of the chunk within `(native_id, field_role)`.
- `\x1f` is the ASCII Unit Separator, chosen so the parts cannot collide with field
  content.

## Rules

- The worker is the **sole authority** that mints `chunk_id`. The core-api never
  derives it; it only reads it back from Qdrant.
- The same `(source, native_id, field_role, seq)` MUST always produce the same
  `chunk_id`, across processes and machines — so the hash input uses only stable,
  caller-provided strings (no timestamps, no randomness).
- Deletes at source are handled by tombstoning the `chunk_id`s of the affected
  `native_id` and removing them from Qdrant.
