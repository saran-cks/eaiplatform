"""EmbeddingVector — dense + optional sparse representation from bge-m3.

Immutable. Sparse component supports Qdrant hybrid search; absent when sparse is
disabled. Tuples (not lists) keep it hashable and safe to cache.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SparseVector:
    indices: tuple[int, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.indices) != len(self.values):
            raise ValueError("sparse indices and values must be the same length")

    @property
    def nnz(self) -> int:
        return len(self.indices)


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    dense: tuple[float, ...]
    sparse: SparseVector | None = None
    model: str = ""

    @property
    def dim(self) -> int:
        return len(self.dense)

    @property
    def is_hybrid(self) -> bool:
        return self.sparse is not None
