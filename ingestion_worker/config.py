"""Ingestion-worker configuration (env-driven).

Standalone from the core-api settings — the worker is its own deployable. Only the
shared-backend coordinates (Qdrant, Postgres) must agree with what the core-api uses, and
that agreement is policed by the contract tests, not by sharing this object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True, slots=True)
class Config:
    # Shared backends (must match the core-api's coordinates).
    qdrant_host: str = _env("QDRANT_HOST", "qdrant")
    qdrant_grpc_port: int = int(_env("QDRANT_GRPC_PORT", "6334"))
    qdrant_collection: str = _env("QDRANT_COLLECTION", "knowledge")
    postgres_dsn: str = _env("POSTGRES_DSN", "postgresql://localhost/eai")

    # Worker-owned embedder (its own bge-m3; dim must equal the collection's dense size).
    embed_model: str = _env("INGEST_EMBED_MODEL", "bge-m3")
    embed_dim: int = int(_env("INGEST_EMBED_DIM", "1024"))
    embed_batch_size: int = int(_env("INGEST_EMBED_BATCH", "32"))

    # Guards.
    prompt_guard_url: str = _env("INGEST_PROMPT_GUARD_URL", "http://prompt_guard:8001")
    llama_guard_url: str = _env("INGEST_LLAMA_GUARD_URL", "http://llama_guard:8002")

    # Security gate.
    max_bytes: int = int(_env("INGEST_MAX_BYTES", str(25 * 1024 * 1024)))
    clamd_host: str = _env("CLAMD_HOST", "clamav")
    clamd_port: int = int(_env("CLAMD_PORT", "3310"))

    # Immutable staging.
    staging_bucket: str = _env("INGEST_STAGING_BUCKET", "eai-ingest-staging")


config = Config()
