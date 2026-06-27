-- Ingestion-owned Postgres tables (shared RDS instance with core-api).
--
-- PRODUCER/OWNER: ingestion_worker (writes + migrates).
-- CONSUMER: core-api may READ doc_registry for provenance display; it never writes here.
--
-- This file is the canonical column contract. Both services' contract tests assert
-- their models match these column names + types. Renaming/retyping a column is breaking.

-- One row per ingested source document (the parent of N chunks).
CREATE TABLE IF NOT EXISTS doc_registry (
    document_id   TEXT        NOT NULL,
    tenant_id     TEXT        NOT NULL,
    source        TEXT        NOT NULL,   -- connector id, e.g. 'servicenow'
    native_id     TEXT        NOT NULL,   -- source's own id
    source_type   TEXT        NOT NULL,   -- 'text' | 'code' | 'ticket' | 'pdf' | ...
    permissions   TEXT[]      NOT NULL DEFAULT '{}',
    lang          TEXT,
    chunk_count   INTEGER     NOT NULL DEFAULT 0,
    content_hash  TEXT        NOT NULL,   -- document-level hash for fast skip
    ingested_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (document_id)
);

-- One row per chunk; the delta/dedup registry. content_hash drives skip/update.
CREATE TABLE IF NOT EXISTS chunk_registry (
    chunk_id      TEXT        NOT NULL,   -- == Qdrant point id (chunk_identity.md)
    document_id   TEXT        NOT NULL REFERENCES doc_registry(document_id) ON DELETE CASCADE,
    tenant_id     TEXT        NOT NULL,
    field_role    TEXT        NOT NULL,
    seq           INTEGER     NOT NULL,
    content_hash  TEXT        NOT NULL,   -- per-chunk hash; compared on re-ingest
    screened      BOOLEAN     NOT NULL DEFAULT FALSE,
    injection_risk DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    updated_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (chunk_id)
);

CREATE INDEX IF NOT EXISTS chunk_registry_document_id_idx ON chunk_registry (document_id);

-- Quarantine / dead-letter for items rejected by the security or content gates.
CREATE TABLE IF NOT EXISTS ingestion_quarantine (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY,
    tenant_id     TEXT,
    source        TEXT        NOT NULL,
    native_id     TEXT,
    stage         TEXT        NOT NULL,   -- 'security_gate' | 'content_guard' | ...
    reason        TEXT        NOT NULL,   -- 'infected' | 'malformed' | 'unsafe' | ...
    detail        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    quarantined_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id)
);
