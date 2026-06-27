"""Session management use case.

Handles creating, hydrating, and listing chat sessions. These are thin
orchestration helpers used by the chat and agent routes.
"""

from __future__ import annotations

import json
import logging

from core.domain.entities.message import Message
from core.domain.entities.session import Session
from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.cache import CachePort
from core.ports.store import StorePort

logger = logging.getLogger(__name__)


class ManageSessionUseCase:
    """Session CRUD and history hydration use case."""

    def __init__(self, store: StorePort, cache: CachePort) -> None:
        self._store = store
        self._cache = cache

    async def get_or_create_session(
        self,
        *,
        session_id: str,
        scope: PermissionScope,
        title: str | None = None,
    ) -> Session:
        """Return the existing session or create a new one.

        Uses ``session:{session_id}`` Valkey key as a fast-path existence check.
        Falls back to Postgres for the authoritative record.
        """
        # Fast-path: check session cache
        cached_raw = await self._cache.get(f"session:{session_id}")
        if cached_raw:
            try:
                data = json.loads(cached_raw)
                return Session.model_validate(data)
            except Exception as exc:
                logger.warning("Corrupted session cache for %s: %s", session_id, exc)

        # Postgres lookup
        session = await self._store.get_session(
            session_id=session_id,
            tenant_id=scope.tenant_id,
        )

        if session is None:
            # Create a brand-new session
            session = Session(
                session_id=session_id,
                tenant_id=scope.tenant_id,
                subject_id=scope.subject_id,
                title=title,
            )
            session = await self._store.create_session(session)
            logger.info("Created new session %s for tenant %s", session_id, scope.tenant_id)

        return session

    async def hydrate_history(
        self,
        *,
        session_id: str,
        scope: PermissionScope,
        limit: int = 20,
    ) -> list[Message]:
        """Load recent message history for a session.

        Checks Valkey first (``session:{session_id}:history``); on miss,
        loads from Postgres and caches the result.
        """
        cache_key = f"session:{session_id}:history"
        cached_raw = await self._cache.get(cache_key)
        if cached_raw:
            try:
                raw_list: list[dict] = json.loads(cached_raw)
                return [Message.model_validate(m) for m in raw_list]
            except Exception as exc:
                logger.warning("Corrupted history cache for %s: %s", session_id, exc)

        messages = await self._store.get_messages(
            session_id=session_id,
            tenant_id=scope.tenant_id,
            limit=limit,
        )
        # Cache the history for 2-hour sliding window
        if messages:
            raw = json.dumps([m.model_dump(mode="json") for m in messages])
            await self._cache.set(cache_key, raw, ttl=7200)

        return messages

    async def refresh_session_cache(
        self,
        *,
        session: Session,
        session_ttl: int,
    ) -> None:
        """Update the session cache with the latest session state (sliding TTL)."""
        await self._cache.set(
            f"session:{session.session_id}",
            session.model_dump_json(),
            ttl=session_ttl,
        )
