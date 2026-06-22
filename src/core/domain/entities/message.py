"""Message & Turn entities.

A ``Message`` is one utterance. A ``Turn`` pairs a user message with the assistant
response plus the chunks that grounded it — the unit feedback and evals attach to.
``message_id`` is the idempotency key for persistence.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from core.domain.entities.chunk import RetrievedChunk


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    role: Role
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None


class Turn(BaseModel):
    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    user_message: Message
    assistant_message: Message | None = None
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    created_at: datetime | None = None
