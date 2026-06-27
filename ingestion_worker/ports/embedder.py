"""EmbedderPort — the worker's OWN bge-m3 (dense + sparse, batched).

Deliberately separate from the core-api's query-time embedding sidecar: a big batch
ingest must never starve live query embedding. The dense dim MUST match
contracts/qdrant_collection.json (1024).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Embedding:
    dense: tuple[float, ...]
    sparse_indices: tuple[int, ...] = field(default_factory=tuple)
    sparse_values: tuple[float, ...] = field(default_factory=tuple)


@runtime_checkable
class EmbedderPort(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        """Batch-embed; result[i] corresponds to texts[i]."""
        ...
