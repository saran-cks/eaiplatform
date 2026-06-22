"""CachePort — Valkey access across three never-mixed namespaces.

Namespaces (key prefixes) are owned by callers/use-cases, not this port:
``response:{hash}`` (1h), ``chunk:{chunk_id}`` (24h), ``session:{session_id}`` (2h sliding).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CachePort(Protocol):
    async def get(self, key: str) -> str | None:
        ...

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        ...

    async def touch(self, key: str, *, ttl: int) -> bool:
        """Refresh TTL without rewriting the value (sliding session windows)."""
        ...

    async def evict(self, key: str) -> None:
        ...

    async def evict_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob pattern; returns count removed."""
        ...
