# Chunk identity contract

The Qdrant point id and payload `chunk_id` are the **same value**, derived
deterministically so that re-ingesting an unchanged source is **idempotent** (the
upsert overwrites the same point) and a changed chunk lands on a stable id.

`chunk_id` is a **UUIDv5**, not a raw sha256 hex: it doubles as the Qdrant point id, and
Qdrant only accepts unsigned-integer or UUID point ids (a 64-char sha256 hex is rejected
as "not a valid UUID"). UUIDv5 over the canonical tuple preserves every property the hash
gave us — deterministic, no timestamps/randomness, unit-separator collision-safety — while
being a legal point id, so the same-value invariant above holds. See DD-23.

## Formula

```
chunk_id = uuidv5( namespace = uuid5(NAMESPACE_URL, "eaiplatform/contracts/chunk_id"),
                   name      = "{source}\x1f{native_id}\x1f{field_role}\x1f{seq}" )
```

`content_hash` (below, delta/dedup) remains a **sha256 hexdigest** — it is a content
fingerprint, not an id, and never touches Qdrant's point-id validation.

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
