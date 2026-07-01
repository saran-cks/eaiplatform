"""ValkeyAdapter fail-soft (DD-24).

The cache is an optimization/coherence layer with an authoritative fallback behind every
namespace, so a Valkey outage must degrade to a *miss*, never raise onto the request path
(the concrete bug: an unguarded ``cache.get`` in ``send_message`` 500s the chat path on a
Valkey blip). These tests pin both halves: the happy path still delegates to the client,
and every method swallows a backend ``RedisError`` and returns the miss sentinel.
"""

from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from adapters.cache.valkey import ValkeyAdapter


class _FakeRedis:
    """redis.asyncio client double: records calls, optionally raises on every op."""

    def __init__(self, *, boom: bool = False) -> None:
        self._boom = boom
        self.data: dict[str, str] = {}

    def _maybe_boom(self) -> None:
        if self._boom:
            raise RedisConnectionError("valkey unreachable")

    async def get(self, key: str) -> str | None:
        self._maybe_boom()
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._maybe_boom()
        self.data[key] = value

    async def expire(self, key: str, ttl: int) -> int:
        self._maybe_boom()
        return 1 if key in self.data else 0

    async def delete(self, *keys: str) -> int:
        self._maybe_boom()
        n = 0
        for k in keys:
            n += 1 if self.data.pop(k, None) is not None else 0
        return n

    async def keys(self, pattern: str) -> list[str]:
        self._maybe_boom()
        return list(self.data)


def _adapter(client: _FakeRedis) -> ValkeyAdapter:
    """Build the adapter without constructing a real connection pool."""
    adapter = ValkeyAdapter.__new__(ValkeyAdapter)
    adapter._client = client  # type: ignore[attr-defined]
    adapter._url = "redis://fake"  # type: ignore[attr-defined]
    return adapter


# --- happy path: still delegates to the client ---------------------------------------


async def test_get_set_roundtrip_delegates_to_client() -> None:
    client = _FakeRedis()
    adapter = _adapter(client)
    await adapter.set("response:abc", "hello", ttl=60)
    assert client.data["response:abc"] == "hello"
    assert await adapter.get("response:abc") == "hello"
    assert await adapter.get("missing") is None


async def test_touch_and_evict_delegate() -> None:
    client = _FakeRedis()
    adapter = _adapter(client)
    await adapter.set("session:1", "x")
    assert await adapter.touch("session:1", ttl=10) is True
    assert await adapter.touch("session:absent", ttl=10) is False
    await adapter.evict("session:1")
    assert "session:1" not in client.data


async def test_evict_pattern_counts_removed() -> None:
    client = _FakeRedis()
    adapter = _adapter(client)
    await adapter.set("chunk:1", "a")
    await adapter.set("chunk:2", "b")
    assert await adapter.evict_pattern("chunk:*") == 2


# --- fail-soft: a backend outage degrades to a miss, never raises ---------------------


async def test_get_returns_none_on_backend_error() -> None:
    adapter = _adapter(_FakeRedis(boom=True))
    assert await adapter.get("response:abc") is None


async def test_set_swallows_backend_error() -> None:
    adapter = _adapter(_FakeRedis(boom=True))
    # Must not raise — the response is already computed; the write is best-effort.
    await adapter.set("response:abc", "hello", ttl=60)


async def test_touch_returns_false_on_backend_error() -> None:
    adapter = _adapter(_FakeRedis(boom=True))
    assert await adapter.touch("session:1", ttl=10) is False


async def test_evict_swallows_backend_error() -> None:
    adapter = _adapter(_FakeRedis(boom=True))
    await adapter.evict("session:1")  # must not raise


async def test_evict_pattern_returns_zero_on_backend_error() -> None:
    adapter = _adapter(_FakeRedis(boom=True))
    assert await adapter.evict_pattern("chunk:*") == 0


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
