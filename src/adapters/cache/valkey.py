"""Valkey cache adapter implementation.

Uses redis.asyncio as the underlying client. Fully compliant with CachePort.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from config.settings import Settings
from core.ports.cache import CachePort

logger = logging.getLogger(__name__)


class ValkeyAdapter(CachePort):
    """Valkey/Redis cache adapter implementing CachePort."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.valkey_url
        self._client = aioredis.from_url(
            self._url,
            decode_responses=True,
        )
        logger.info("ValkeyAdapter initialized with endpoint: %s", self._url)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        await self._client.set(key, value, ex=ttl)

    async def touch(self, key: str, *, ttl: int) -> bool:
        res = await self._client.expire(key, ttl)
        return bool(res)

    async def evict(self, key: str) -> None:
        await self._client.delete(key)

    async def evict_pattern(self, pattern: str) -> int:
        keys = await self._client.keys(pattern)
        if not keys:
            return 0
        # Delete expects unpacking of arguments
        res = await self._client.delete(*keys)
        return int(res)

    async def ping(self) -> bool:
        """Helper connection test method (not in protocol but useful for readiness checks)."""
        try:
            return bool(await self._client.ping())
        except Exception as e:
            logger.warning("Valkey ping failed: %s", e)
            return False
