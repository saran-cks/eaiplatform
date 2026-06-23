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
