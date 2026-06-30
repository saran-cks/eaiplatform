"""Chat API request / response schemas.

All schemas are Pydantic v2 models; any change here must stay backward-compatible
with existing clients or be coordinated with a version bump.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    """Incoming user message payload for the chat endpoint."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        description="The user's natural-language question or instruction.",
    )
    title: str | None = Field(
        None,
        max_length=255,
        description="Optional session title (used only when creating a new session).",
    )
    message_id: str | None = Field(
        None,
        min_length=1,
        max_length=128,
        description=(
            "Optional client-generated idempotency key for this message. Supply a stable "
            "id (e.g. a UUID minted once per user submission and reused on retry) so a "
            "duplicate submission — double-click, proxy/LB retry, SSE reconnect-and-resend "
            "— is deduplicated on persist instead of creating a duplicate turn. Omit to get "
            "a fresh server-side id per request (no cross-retry dedup)."
        ),
    )


class SessionOut(BaseModel):
    """Minimal session representation returned by the create session endpoint."""

    session_id: str
    title: str | None = None
    status: str
    tenant_id: str
    subject_id: str | None = None


class MessageOut(BaseModel):
    """Minimal message representation (used in history listings)."""

    message_id: str
    role: str
    content: str


class HistoryOut(BaseModel):
    """Paginated message history response."""

    session_id: str
    messages: list[MessageOut]
    count: int
