"""Chat API routes.

Endpoints:
  POST /chat                         — Create a new session (returns session metadata).
  GET  /chat                         — List sessions for the authenticated tenant/subject.
  GET  /chat/{session_id}/history    — Return persisted message history for a session.
  POST /chat/{session_id}/message    — Send a user message; streams assistant response as SSE.

SSE format:
  Each event is a ``data: <token>`` line followed by a blank line (EventSource compliant).
  The stream ends with ``data: [DONE]\n\n`` to signal completion.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.schemas.chat import (
    ChatMessageRequest,
    HistoryOut,
    MessageOut,
    SessionOut,
)
from core.domain.entities.session import Session
from core.use_cases.chat.manage_session import ManageSessionUseCase
from core.use_cases.chat.send_message import SendChatMessageUseCase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _get_scope(request: Request):  # type: ignore[return]
    """Extract PermissionScope from request state, raise 401 if absent."""
    scope = getattr(request.state, "scope", None)
    if scope is None:
        raise HTTPException(status_code=401, detail="Permission scope missing from request context")
    return scope


# ---------------------------------------------------------------------------
# POST /chat — create new session
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=SessionOut,
    status_code=201,
    summary="Create a new chat session",
)
async def create_session(request: Request) -> SessionOut:
    """Create and return a new chat session for the authenticated principal."""
    scope = _get_scope(request)
    container = request.app.state.container

    manage = ManageSessionUseCase(store=container.store, cache=container.cache)
    session_id = str(uuid4())
    session = await manage.get_or_create_session(session_id=session_id, scope=scope)

    return SessionOut(
        session_id=session.session_id,
        title=session.title,
        status=session.status.value,
        tenant_id=session.tenant_id,
        subject_id=session.subject_id,
    )


# ---------------------------------------------------------------------------
# GET /chat — list sessions
# ---------------------------------------------------------------------------
@router.get(
    "",
    response_model=list[SessionOut],
    summary="List chat sessions for the authenticated principal",
)
async def list_sessions(request: Request) -> list[SessionOut]:
    """Return all active sessions scoped to the JWT tenant/subject."""
    scope = _get_scope(request)
    container = request.app.state.container

    sessions: list[Session] = await container.store.list_sessions(
        tenant_id=scope.tenant_id,
        subject_id=scope.subject_id,
        limit=50,
    )
    return [
        SessionOut(
            session_id=s.session_id,
            title=s.title,
            status=s.status.value,
            tenant_id=s.tenant_id,
            subject_id=s.subject_id,
        )
        for s in sessions
    ]


# ---------------------------------------------------------------------------
# GET /chat/{session_id}/history — fetch message history
# ---------------------------------------------------------------------------
@router.get(
    "/{session_id}/history",
    response_model=HistoryOut,
    summary="Retrieve message history for a session",
)
async def get_history(session_id: str, request: Request) -> HistoryOut:
    """Return up to 20 recent messages for the given session."""
    scope = _get_scope(request)
    container = request.app.state.container

    manage = ManageSessionUseCase(store=container.store, cache=container.cache)
    messages = await manage.hydrate_history(
        session_id=session_id,
        scope=scope,
        limit=20,
    )
    return HistoryOut(
        session_id=session_id,
        messages=[
            MessageOut(
                message_id=m.message_id,
                role=m.role.value,
                content=m.content,
            )
            for m in messages
        ],
        count=len(messages),
    )


# ---------------------------------------------------------------------------
# POST /chat/{session_id}/message — SSE streaming chat endpoint
# ---------------------------------------------------------------------------
@router.post(
    "/{session_id}/message",
    summary="Send a user message and stream the assistant response (SSE)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-Sent Events stream of token deltas ending with [DONE]",
            "content": {"text/event-stream": {}},
        }
    },
)
async def send_message(
    session_id: str,
    body: ChatMessageRequest,
    request: Request,
) -> StreamingResponse:
    """Stream an assistant response for the given user query via SSE.

    The response is ``Content-Type: text/event-stream``. Each token is sent as::

        data: <token_text>\\n\\n

    The stream terminates with::

        data: [DONE]\\n\\n

    On client disconnect during streaming the generator is garbage-collected
    automatically by Starlette's StreamingResponse.
    """
    scope = _get_scope(request)
    container = request.app.state.container
    settings = container.settings

    # 1. Resolve or create the session
    manage = ManageSessionUseCase(store=container.store, cache=container.cache)
    try:
        session = await manage.get_or_create_session(
            session_id=session_id,
            scope=scope,
            title=body.title,
        )
    except Exception as exc:
        logger.error("Session resolution failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve session") from exc

    # Refresh session sliding TTL in background (fire-and-forget; errors are logged not raised)
    await manage.refresh_session_cache(session=session, session_ttl=settings.session_ttl)

    # 2. Hydrate message history
    history = await manage.hydrate_history(
        session_id=session_id,
        scope=scope,
        limit=20,
    )

    # 3. Build the use case
    send_uc = SendChatMessageUseCase(
        store=container.store,
        cache=container.cache,
        retriever=container.retriever,
        llm=container.llm,
        guard=container.guard,
        retrieval_top_k=settings.retrieval_top_k,
        cache_response_ttl=settings.cache_response_ttl,
        observability=container.observability,
        evaluator=container.evaluator,
        eval_sample_rate=settings.eval_sample_rate,
    )

    # 4. Build the SSE generator
    #
    # The use case hands back the turn's LLM span id via ``on_span``; we relay it
    # once as a named ``meta`` event so the client can attach human feedback to
    # this turn (POST /feedback). It rides on a distinct event name, never as a
    # ``data:`` token, so the bare-token stream contract is unchanged.
    span_box: dict[str, str] = {}

    async def _event_generator():
        meta_sent = False
        try:
            async for token in send_uc.execute(
                session=session,
                query=body.query,
                scope=scope,
                history=history,
                client_message_id=body.message_id,
                on_span=lambda sid: span_box.__setitem__("span_id", sid),
            ):
                if not meta_sent and "span_id" in span_box:
                    yield f"event: meta\ndata: {json.dumps({'span_id': span_box['span_id']})}\n\n"
                    meta_sent = True
                if token:
                    # Escape newlines inside the token so they don't break SSE framing
                    safe = token.replace("\n", " ")
                    yield f"data: {safe}\n\n"
        except Exception as exc:
            logger.exception("SSE pipeline error in session %s: %s", session_id, exc)
            yield "event: error\ndata: An internal error occurred while processing the request.\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for SSE
        },
    )
