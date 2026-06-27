"""SendChatMessageUseCase — the RAG orchestration pipeline.

Flow for every incoming user message:

1. Optionally probe cache (only for single-turn messages).
2. Embed the user query via ModelServerEmbedClient (gRPC → bge-m3).
3. Hybrid search against Qdrant (dense+sparse, RRF, permission-filtered).
4. Build the system prompt, inject retrieved context, call BedrockAdapter.stream().
5. Yield SSE deltas back to the HTTP layer token-by-token.
6. On stream completion, persist the full Turn to Postgres.
7. Invalidate the session history cache so the next request sees fresh history.

All I/O is async; no blocking calls on the event loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from core.domain.entities.message import Message, Role, Turn
from core.domain.entities.session import Session
from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.cache import CachePort
from core.ports.llm import LLMPort
from core.ports.retriever import RetrieverPort
from core.ports.store import StorePort

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """\
You are a knowledgeable AI assistant. Answer the user's question using ONLY the
context passages provided below. If the context does not contain enough information
to answer the question, acknowledge that clearly. Do not fabricate information.

CONTEXT:
{context}
"""


def _build_cache_key(query: str, tenant_id: str, permissions: frozenset[str]) -> str:
    """Build a cache key containing query, tenant, and the exact permission boundaries."""
    sorted_perms = ",".join(sorted(list(permissions)))
    digest = hashlib.sha256(f"{tenant_id}:{sorted_perms}:{query}".encode()).hexdigest()
    return f"query:{digest}"


class SendChatMessageUseCase:
    """Orchestrates the full RAG pipeline for a single user chat message."""

    def __init__(
        self,
        *,
        store: StorePort,
        cache: CachePort,
        retriever: RetrieverPort,
        llm: LLMPort,
        retrieval_top_k: int,
        cache_response_ttl: int,
    ) -> None:
        self._store = store
        self._cache = cache
        self._retriever = retriever
        self._llm = llm
        self._retrieval_top_k = retrieval_top_k
        self._cache_response_ttl = cache_response_ttl

    async def execute(
        self,
        *,
        session: Session,
        query: str,
        scope: PermissionScope,
        history: list[Message],
    ) -> AsyncIterator[str]:
        """Async generator that yields SSE token deltas then persists the turn.

        Callers MUST consume the entire iterator to ensure Turn persistence.
        """
        is_single_turn = len(history) == 0
        cache_key = _build_cache_key(query, scope.tenant_id, scope.permissions)

        # --- step 1: cache probe (restricted to single-turn to preserve context) ---
        if is_single_turn:
            cached_response = await self._cache.get(cache_key)
            if cached_response:
                logger.debug("Cache hit for query hash %s", cache_key)
                
                # Persist turn on cache hit to prevent history holes
                user_message = Message(
                    session_id=session.session_id,
                    role=Role.USER,
                    content=query,
                    created_at=datetime.now(tz=timezone.utc),
                )
                assistant_message = Message(
                    session_id=session.session_id,
                    role=Role.ASSISTANT,
                    content=cached_response,
                    created_at=datetime.now(tz=timezone.utc),
                )
                turn = Turn(
                    session_id=session.session_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    retrieved_chunks=[],
                    created_at=datetime.now(tz=timezone.utc),
                )
                try:
                    await self._store.append_turn(turn)
                except Exception as exc:
                    logger.error("Turn persistence failed for session %s on cache hit: %s", session.session_id, exc)

                await self._cache.evict(f"session:{session.session_id}:history")
                yield cached_response
                return

        # --- step 2: embed the query (fail-closed) ---
        try:
            query_vector = await self._retriever.embed(query)
        except Exception as exc:
            logger.error("Embedding failed for session %s: %s", session.session_id, exc)
            raise RuntimeError(f"Embedding service unavailable: {exc}") from exc

        # --- step 3: hybrid search (fail-closed) ---
        try:
            retrieval_result = await self._retriever.search(
                query=query_vector,
                scope=scope,
                top_k=self._retrieval_top_k,
            )
            retrieved_chunks = retrieval_result.chunks
        except Exception as exc:
            logger.error("Retrieval failed for session %s: %s", session.session_id, exc)
            raise RuntimeError(f"Retrieval service unavailable: {exc}") from exc

        # --- step 4: build context and system prompt ---
        if retrieved_chunks:
            context_text = "\n\n---\n\n".join(
                f"[{i + 1}] {c.text}" for i, c in enumerate(retrieved_chunks)
            )
        else:
            context_text = "(No relevant context found in knowledge base.)"

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(context=context_text)

        # Build the messages list: history + current user message
        user_message = Message(
            session_id=session.session_id,
            role=Role.USER,
            content=query,
            created_at=datetime.now(tz=timezone.utc),
        )
        all_messages = list(history) + [user_message]

        # --- step 5: stream LLM response (fail-closed propagation) ---
        collected_tokens: list[str] = []
        try:
            async for token in self._llm.stream(
                messages=all_messages,
                system=system_prompt,
            ):
                collected_tokens.append(token)
                yield token
        except Exception as exc:
            logger.error("LLM stream failed for session %s: %s", session.session_id, exc)
            raise RuntimeError(f"LLM stream failed or was interrupted: {exc}") from exc

        # --- step 6: assemble full assistant response ---
        assistant_text = "".join(collected_tokens)

        assistant_message = Message(
            session_id=session.session_id,
            role=Role.ASSISTANT,
            content=assistant_text,
            created_at=datetime.now(tz=timezone.utc),
        )

        # --- step 7: persist turn ---
        turn = Turn(
            session_id=session.session_id,
            user_message=user_message,
            assistant_message=assistant_message,
            retrieved_chunks=retrieved_chunks,
            created_at=datetime.now(tz=timezone.utc),
        )
        try:
            await self._store.append_turn(turn)
        except Exception as exc:
            logger.error("Turn persistence failed for session %s: %s", session.session_id, exc)

        # --- step 8: cache the response and invalidate history ---
        if is_single_turn:
            await self._cache.set(
                cache_key,
                assistant_text,
                ttl=self._cache_response_ttl,
            )
        await self._cache.evict(f"session:{session.session_id}:history")
