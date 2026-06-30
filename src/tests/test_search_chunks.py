"""Unit tests for the /search retrieval use case (`SearchChunksUseCase`).

`/search` is a security-spine surface: per CLAUDE.md it "enforces the identical scope
as /chat". The use case itself is a thin orchestration over the retriever, so the
behaviours that matter are:

1. The query is embedded, and the resulting vector — not the raw text — is what gets
   searched.
2. The **caller's PermissionScope is passed through to the retriever unchanged** (same
   object identity): the use case must never widen, narrow, or re-derive it. The adapter
   turns it into the Qdrant payload filter; if the use case mutated it, the filter would
   be wrong.
3. The `limit` flows through to `top_k` (default 5).
4. Embedding / search failures **propagate** (fail-closed) rather than returning partial
   or empty results that could read as "no documents match your scope".
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domain.entities.chunk import RetrievedChunk
from core.domain.value_objects.embedding_vector import EmbeddingVector
from core.domain.value_objects.permission_scope import PermissionScope
from core.domain.value_objects.retrieval_result import RetrievalResult
from core.use_cases.retrieval.search_chunks import SearchChunksUseCase


def _scope() -> PermissionScope:
    return PermissionScope(
        tenant_id="tenant-1",
        permissions=frozenset(["read", "kb:hr"]),
        subject_id="user-7",
    )


def _result(*chunk_ids: str) -> RetrievalResult:
    chunks = tuple(
        RetrievedChunk(
            chunk_id=cid,
            document_id="doc-1",
            tenant_id="tenant-1",
            text=f"text {cid}",
            score=0.9,
        )
        for cid in chunk_ids
    )
    return RetrievalResult(chunks=chunks)


def _retriever(result: RetrievalResult) -> AsyncMock:
    retriever = AsyncMock()
    retriever.embed.return_value = EmbeddingVector(dense=(0.1, 0.2, 0.3))
    retriever.search.return_value = result
    return retriever


async def test_embeds_query_then_searches_with_the_vector():
    """The text is embedded once and the *vector* (not the text) is handed to search."""
    retriever = _retriever(_result("c1"))
    use_case = SearchChunksUseCase(retriever)

    await use_case.execute(query_text="quarterly numbers", scope=_scope())

    retriever.embed.assert_awaited_once_with("quarterly numbers")
    vector = retriever.embed.return_value
    assert retriever.search.await_args.kwargs["query"] is vector


async def test_scope_is_passed_through_to_the_retriever_unchanged():
    """Security spine: the exact scope object reaches the retriever — not a copy, not a
    widened/derived scope. The adapter relies on this to build the payload filter."""
    scope = _scope()
    retriever = _retriever(_result("c1"))
    use_case = SearchChunksUseCase(retriever)

    await use_case.execute(query_text="q", scope=scope)

    passed = retriever.search.await_args.kwargs["scope"]
    assert passed is scope
    # And it was not mutated in flight (frozen, but assert the contents to be explicit).
    assert passed.tenant_id == "tenant-1"
    assert passed.permissions == frozenset(["read", "kb:hr"])


async def test_default_limit_is_five_and_maps_to_top_k():
    retriever = _retriever(_result("c1"))
    use_case = SearchChunksUseCase(retriever)

    await use_case.execute(query_text="q", scope=_scope())

    assert retriever.search.await_args.kwargs["top_k"] == 5


async def test_custom_limit_flows_to_top_k():
    retriever = _retriever(_result("c1", "c2"))
    use_case = SearchChunksUseCase(retriever)

    await use_case.execute(query_text="q", scope=_scope(), limit=20)

    assert retriever.search.await_args.kwargs["top_k"] == 20


async def test_returns_the_retriever_result_unchanged():
    expected = _result("c1", "c2", "c3")
    retriever = _retriever(expected)
    use_case = SearchChunksUseCase(retriever)

    out = await use_case.execute(query_text="q", scope=_scope())

    assert out is expected


async def test_embed_failure_propagates_fail_closed():
    """An embedding outage must raise — never silently return an empty result that the
    UI would render as 'no chunks matched your permission scope'."""
    retriever = AsyncMock()
    retriever.embed.side_effect = RuntimeError("model server down")
    use_case = SearchChunksUseCase(retriever)

    with pytest.raises(RuntimeError, match="model server down"):
        await use_case.execute(query_text="q", scope=_scope())

    retriever.search.assert_not_awaited()


async def test_search_failure_propagates_fail_closed():
    retriever = _retriever(_result("c1"))
    retriever.search.side_effect = RuntimeError("qdrant unreachable")
    use_case = SearchChunksUseCase(retriever)

    with pytest.raises(RuntimeError, match="qdrant unreachable"):
        await use_case.execute(query_text="q", scope=_scope())
