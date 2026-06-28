"""ValkeySessionRiskStore — DD-11 cumulative session risk persisted in Valkey.

Implements ``SessionRiskStorePort`` on top of the existing ``CachePort`` (no second Redis
client): it serializes ``SessionRiskState`` to JSON under a ``risk:{session_id}`` key with a
TTL matching the agent-session window. This is what makes the trajectory monitor correct in a
multi-worker deployment — risk accumulates in a shared backend, not per-process memory.

Concurrency note (DD-16): load→modify→save is not atomic. Within one agent session tool calls
are sequential (single worker at a time), so this is sufficient for the threat model; a Lua
CAS / atomic-increment hardening is FUTURE for genuinely concurrent same-session writers.
"""

from __future__ import annotations

import json
import logging

from core.domain.policy.trajectory import SessionRiskState
from core.ports.cache import CachePort
from core.ports.session_risk_store import SessionRiskStorePort

logger = logging.getLogger(__name__)


class ValkeySessionRiskStore(SessionRiskStorePort):
    def __init__(self, cache: CachePort, *, ttl: int, prefix: str = "risk:") -> None:
        self._cache = cache
        self._ttl = ttl
        self._prefix = prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def load(self, session_id: str) -> SessionRiskState | None:
        raw = await self._cache.get(self._key(session_id))
        if raw is None:
            return None
        return SessionRiskState.from_dict(json.loads(raw))

    async def save(self, session_id: str, state: SessionRiskState) -> None:
        await self._cache.set(
            self._key(session_id), json.dumps(state.to_dict()), ttl=self._ttl
        )

    async def delete(self, session_id: str) -> None:
        await self._cache.evict(self._key(session_id))
