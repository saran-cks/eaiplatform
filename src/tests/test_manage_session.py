"""Unit tests for `ManageSessionUseCase` — session get/create + history hydration.

The logic worth pinning here is the cache/Postgres fallback and **tenant isolation**:
every store lookup must use `scope.tenant_id`, and a brand-new session must inherit the
caller's tenant/subject from the scope (never from client-supplied data). Corrupted
cache entries must degrade to the authoritative Postgres record, not blow up the request.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from core.domain.entities.message import Message, Role
from core.domain.entities.session import Session
from core.domain.value_objects.permission_scope import PermissionScope
from core.use_cases.chat.manage_session import ManageSessionUseCase


def _scope() -> PermissionScope:
    return PermissionScope(
        tenant_id="tenant-1", permissions=frozenset(["read"]), subject_id="user-7"
    )


def _session(session_id: str = "s1", tenant_id: str = "tenant-1") -> Session:
    return Session(session_id=session_id, tenant_id=tenant_id, subject_id="user-7", title="t")


# --- get_or_create_session ------------------------------------------------------------


async def test_cache_hit_returns_session_without_touching_store():
    cache = AsyncMock()
    cache.get.return_value = _session().model_dump_json()
    store = AsyncMock()
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.get_or_create_session(session_id="s1", scope=_scope())

    assert out.session_id == "s1"
    cache.get.assert_awaited_once_with("session:s1")
    store.get_session.assert_not_awaited()
    store.create_session.assert_not_awaited()


async def test_corrupted_cache_falls_back_to_store():
    cache = AsyncMock()
    cache.get.return_value = "{not valid json"
    store = AsyncMock()
    store.get_session.return_value = _session()
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.get_or_create_session(session_id="s1", scope=_scope())

    assert out.session_id == "s1"
    store.get_session.assert_awaited_once_with(session_id="s1", tenant_id="tenant-1")
    store.create_session.assert_not_awaited()


async def test_store_hit_is_returned_and_not_recreated():
    cache = AsyncMock()
    cache.get.return_value = None
    store = AsyncMock()
    store.get_session.return_value = _session()
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.get_or_create_session(session_id="s1", scope=_scope())

    assert out.session_id == "s1"
    store.create_session.assert_not_awaited()


async def test_store_miss_creates_session_from_scope():
    """A new session must take tenant_id/subject_id from the scope, not from the client."""
    cache = AsyncMock()
    cache.get.return_value = None
    store = AsyncMock()
    store.get_session.return_value = None
    store.create_session.side_effect = lambda s: s  # echo back what we persisted
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.get_or_create_session(
        session_id="new-1", scope=_scope(), title="My chat"
    )

    store.create_session.assert_awaited_once()
    created = store.create_session.await_args.args[0]
    assert created.session_id == "new-1"
    assert created.tenant_id == "tenant-1"
    assert created.subject_id == "user-7"
    assert created.title == "My chat"
    assert out is created


async def test_lookup_is_scoped_to_caller_tenant():
    """Tenant isolation: the Postgres lookup uses the scope's tenant, never a default."""
    cache = AsyncMock()
    cache.get.return_value = None
    store = AsyncMock()
    store.get_session.return_value = _session(tenant_id="tenant-9")
    scope = PermissionScope(tenant_id="tenant-9", permissions=frozenset(), subject_id="u")
    use_case = ManageSessionUseCase(store, cache)

    await use_case.get_or_create_session(session_id="s1", scope=scope)

    assert store.get_session.await_args.kwargs["tenant_id"] == "tenant-9"


# --- hydrate_history ------------------------------------------------------------------


def _msg(content: str) -> Message:
    return Message(session_id="s1", role=Role.USER, content=content)


async def test_history_cache_hit_returns_parsed_messages():
    cache = AsyncMock()
    cache.get.return_value = json.dumps([_msg("hi").model_dump(mode="json")])
    store = AsyncMock()
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.hydrate_history(session_id="s1", scope=_scope())

    assert [m.content for m in out] == ["hi"]
    cache.get.assert_awaited_once_with("session:s1:history")
    store.get_messages.assert_not_awaited()


async def test_history_miss_loads_from_store_and_caches():
    cache = AsyncMock()
    cache.get.return_value = None
    store = AsyncMock()
    store.get_messages.return_value = [_msg("a"), _msg("b")]
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.hydrate_history(session_id="s1", scope=_scope(), limit=20)

    assert [m.content for m in out] == ["a", "b"]
    store.get_messages.assert_awaited_once_with(
        session_id="s1", tenant_id="tenant-1", limit=20
    )
    # cached with the 2h sliding TTL
    cache.set.assert_awaited_once()
    assert cache.set.await_args.kwargs["ttl"] == 7200


async def test_history_empty_result_is_not_cached():
    """Don't write an empty list — that would mask a later genuine population."""
    cache = AsyncMock()
    cache.get.return_value = None
    store = AsyncMock()
    store.get_messages.return_value = []
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.hydrate_history(session_id="s1", scope=_scope())

    assert out == []
    cache.set.assert_not_awaited()


async def test_corrupted_history_cache_falls_back_to_store():
    cache = AsyncMock()
    cache.get.return_value = "{garbage"
    store = AsyncMock()
    store.get_messages.return_value = [_msg("a")]
    use_case = ManageSessionUseCase(store, cache)

    out = await use_case.hydrate_history(session_id="s1", scope=_scope())

    assert [m.content for m in out] == ["a"]
    store.get_messages.assert_awaited_once()


# --- refresh_session_cache ------------------------------------------------------------


async def test_refresh_writes_session_with_given_ttl():
    cache = AsyncMock()
    store = AsyncMock()
    use_case = ManageSessionUseCase(store, cache)

    await use_case.refresh_session_cache(session=_session(), session_ttl=7200)

    cache.set.assert_awaited_once()
    assert cache.set.await_args.args[0] == "session:s1"
    assert cache.set.await_args.kwargs["ttl"] == 7200
    # Round-trips back to a Session
    written = json.loads(cache.set.await_args.args[1])
    assert written["session_id"] == "s1"
