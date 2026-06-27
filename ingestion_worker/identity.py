"""Canonical chunk identity. Contract: repo-root contracts/chunk_identity.md.

The worker is the SOLE authority that mints chunk ids. The derivation is deterministic
so re-ingesting an unchanged source overwrites the same Qdrant point (idempotent) and a
changed chunk lands on a stable id.
"""

from __future__ import annotations

import hashlib

# ASCII Unit Separator — cannot collide with field content.
_US = "\x1f"


def chunk_id(*, source: str, native_id: str, field_role: str, seq: int) -> str:
    """sha256 over the canonical, stable tuple. No timestamps, no randomness."""
    raw = _US.join((source, native_id, field_role, str(seq)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    """Per-chunk content hash for delta/dedup against the registry."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
