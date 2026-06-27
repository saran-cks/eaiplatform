"""Unit tests for chat RAG pipeline security boundaries.

Tests that:
1. Cache key generation includes and sorts permissions to prevent data leaks.
2. Cache is only probed and written for single-turn messages (history is empty).
3. Retrieval and embedding failures fail-closed by raising an error.
4. Cache hits correctly persist the Turn to Postgres.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.domain.entities.message import Message, Role, Turn
from core.domain.entities.session import Session
from core.domain.value_objects.guard_verdict import GuardVerdict
from core.domain.value_objects.permission_scope import PermissionScope
from core.domain.value_objects.retrieval_result import RetrievalResult
from core.use_cases.chat.send_message import SendChatMessageUseCase, _build_cache_key


def _benign_guard() -> AsyncMock:
    """A guard mock that classifies every query as benign (does not block)."""
    guard = AsyncMock()
    guard.screen.return_value = GuardVerdict.allow()
    return guard


def test_build_cache_key_includes_and_sorts_permissions():
    """Verify permissions are sorted and factored into the cache key."""
    query = "What is the secret?"
    tenant_id = "tenant-1"
    
    # Order should not matter for the resulting cache key
    key1 = _build_cache_key(query, tenant_id, frozenset(["read", "write"]))
    key2 = _build_cache_key(query, tenant_id, frozenset(["write", "read"]))
    assert key1 == key2

    # Different permissions must produce completely different keys to prevent data leakage
    key3 = _build_cache_key(query, tenant_id, frozenset(["read"]))
    assert key1 != key3


@pytest.mark.asyncio
async def test_cache_hit_persists_turn():
    """Verify that on a cache hit, the Turn is still written to the store."""
    store = AsyncMock()
    cache = AsyncMock()
    retriever = AsyncMock()
    llm = AsyncMock()

    use_case = SendChatMessageUseCase(
        store=store,
        cache=cache,
        retriever=retriever,
        llm=llm,
        guard=_benign_guard(),
        retrieval_top_k=5,
        cache_response_ttl=3600,
    )

    session = Session(session_id="session-1", tenant_id="tenant-1")
    scope = PermissionScope(tenant_id="tenant-1", permissions=frozenset(["read"]))

    # Simulate a cache hit for the query
    cache.get.return_value = "Cached answer"

    # Execute and consume generator
    tokens = []
    async for token in use_case.execute(
        session=session,
        query="Hello",
        scope=scope,
        history=[],  # Single-turn
    ):
        tokens.append(token)

    assert tokens == ["Cached answer"]
    
    # Assert Turn was persisted
    store.append_turn.assert_called_once()
    persisted_turn: Turn = store.append_turn.call_args[0][0]
    assert persisted_turn.session_id == "session-1"
    assert persisted_turn.user_message.content == "Hello"
    assert persisted_turn.assistant_message.content == "Cached answer"
    assert len(persisted_turn.retrieved_chunks) == 0

    # Cache history is evicted
    cache.evict.assert_called_once_with("session:session-1:history")


# Helper class to mock an async iterator
class MockAsyncIterator:
    def __init__(self, items):
        self.items = items
        self.idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.idx < len(self.items):
            item = self.items[self.idx]
            self.idx += 1
            return item
        else:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_multi_turn_bypasses_cache():
    """Verify that multi-turn dialogue bypasses the cache entirely to preserve context."""
    store = AsyncMock()
    cache = AsyncMock()
    # Cache get returns None (cache miss)
    cache.get.return_value = None
    
    retriever = AsyncMock()
    llm = MagicMock()  # Use MagicMock so we can customize stream returning an iterator

    use_case = SendChatMessageUseCase(
        store=store,
        cache=cache,
        retriever=retriever,
        llm=llm,
        guard=_benign_guard(),
        retrieval_top_k=3,
        cache_response_ttl=3600,
    )

    session = Session(session_id="session-1", tenant_id="tenant-1")
    scope = PermissionScope(tenant_id="tenant-1", permissions=frozenset(["read"]))
    
    # Mock history (this is multi-turn)
    history = [
        Message(session_id="session-1", role=Role.USER, content="Hello"),
        Message(session_id="session-1", role=Role.ASSISTANT, content="Hi there"),
    ]

    retrieval_result = RetrievalResult(chunks=(), fusion="rrf", reranked=False)
    retriever.search.return_value = retrieval_result

    # Mock streaming output from Bedrock
    llm.stream.return_value = MockAsyncIterator(["Final ", "output"])

    # Execute
    tokens = []
    async for token in use_case.execute(
        session=session,
        query="What is my name?",
        scope=scope,
        history=history,
    ):
        tokens.append(token)

    # Cache should not be checked or updated
    cache.get.assert_not_called()
    cache.set.assert_not_called()

    # The Turn must still be persisted
    store.append_turn.assert_called_once()


@pytest.mark.asyncio
async def test_retrieval_failure_fails_closed():
    """Verify that if embedding or retriever fails, the pipeline raises an error (fails closed)."""
    store = AsyncMock()
    cache = AsyncMock()
    cache.get.return_value = None
    
    retriever = AsyncMock()
    llm = AsyncMock()

    use_case = SendChatMessageUseCase(
        store=store,
        cache=cache,
        retriever=retriever,
        llm=llm,
        guard=_benign_guard(),
        retrieval_top_k=5,
        cache_response_ttl=3600,
    )

    session = Session(session_id="session-1", tenant_id="tenant-1")
    scope = PermissionScope(tenant_id="tenant-1", permissions=frozenset(["read"]))

    # Simulate retriever error
    retriever.embed.side_effect = Exception("Qdrant connection timeout")

    with pytest.raises(RuntimeError, match="Embedding service unavailable"):
        async for _ in use_case.execute(
            session=session,
            query="Hello",
            scope=scope,
            history=[],
        ):
            pass

