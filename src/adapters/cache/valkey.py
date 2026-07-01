"""Valkey cache adapter implementation.

Uses redis.asyncio as the underlying client. Fully compliant with CachePort.

**Fail-soft (DD-24).** The cache is an optimization/coherence layer, never a system of
record: every namespace has an authoritative fallback (`response:`/`chunk:` recompute,
`session:` hydrates from Postgres, `risk:` degrades to the monitor's in-process
accumulator). So a Valkey outage must degrade to a *miss*, never raise onto the request
path. Every method swallows backend errors here — reads return the miss sentinel
(`None`/`False`/`0`), writes/evicts become no-ops — so the ~15 call sites can't drift and
none of them needs its own try/except. This is the cache's posture alongside DD-17
(observability fail-soft) and opposite DD-22 (guard fail-closed): the cache guards latency
and availability, not a security boundary, so soft-failing it is the safe direction.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from config.settings import Settings
from core.ports.cache import CachePort

logger = logging.getLogger(__name__)


class ValkeyAdapter(CachePort):
    """Valkey/Redis cache adapter implementing CachePort (fail-soft — see module docstring)."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.valkey_url
        self._client = aioredis.from_url(
            self._url,
            decode_responses=True,
        )
        logger.info("ValkeyAdapter initialized with endpoint: %s", self._url)

    async def get(self, key: str) -> str | None:
        try:
            return await self._client.get(key)
        except RedisError as exc:
            logger.warning("Valkey get failed for %s; treating as miss: %s", key, exc)
            return None

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        try:
            await self._client.set(key, value, ex=ttl)
        except RedisError as exc:
            logger.warning("Valkey set failed for %s; skipping cache write: %s", key, exc)

    async def touch(self, key: str, *, ttl: int) -> bool:
        try:
            res = await self._client.expire(key, ttl)
            return bool(res)
        except RedisError as exc:
            logger.warning("Valkey touch failed for %s: %s", key, exc)
            return False

    async def evict(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except RedisError as exc:
            logger.warning("Valkey evict failed for %s: %s", key, exc)

    async def evict_pattern(self, pattern: str) -> int:
        try:
            keys = await self._client.keys(pattern)
            if not keys:
                return 0
            # Delete expects unpacking of arguments
            res = await self._client.delete(*keys)
            return int(res)
        except RedisError as exc:
            logger.warning("Valkey evict_pattern failed for %s: %s", pattern, exc)
            return 0

    async def ping(self) -> bool:
        """Helper connection test method (not in protocol but useful for readiness checks)."""
        try:
            return bool(await self._client.ping())
        except Exception as e:
            logger.warning("Valkey ping failed: %s", e)
            return False
