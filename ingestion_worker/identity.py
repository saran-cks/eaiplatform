"""Canonical chunk identity. Contract: repo-root contracts/chunk_identity.md.

The worker is the SOLE authority that mints chunk ids. The derivation is deterministic
so re-ingesting an unchanged source overwrites the same Qdrant point (idempotent) and a
changed chunk lands on a stable id.

`chunk_id` is a **UUIDv5** (not a raw sha256 hex) because it doubles as the Qdrant point
id, and Qdrant only accepts unsigned-int or UUID point ids — a 64-char sha256 hex is
rejected as "not a valid UUID" (DD-23). UUIDv5 keeps every property the sha256 gave us
(deterministic, no timestamps/randomness, unit-separator collision-safety) while being a
legal point id, so the "point id == payload chunk_id == chunk_id" invariant stays true.
"""

from __future__ import annotations

import hashlib
import uuid

# ASCII Unit Separator — cannot collide with field content.
_US = "\x1f"

# Fixed platform namespace so uuid5 is stable across processes and machines (RFC 4122 §4.3).
_CHUNK_NS = uuid.uuid5(uuid.NAMESPACE_URL, "eaiplatform/contracts/chunk_id")


def chunk_id(*, source: str, native_id: str, field_role: str, seq: int) -> str:
    """Deterministic UUIDv5 over the canonical, stable tuple. No timestamps, no randomness."""
    name = _US.join((source, native_id, field_role, str(seq)))
    return str(uuid.uuid5(_CHUNK_NS, name))


def content_hash(text: str) -> str:
    """Per-chunk content hash for delta/dedup against the registry."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
