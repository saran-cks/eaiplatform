"""Session & AgentSession entities.

``Session`` is a chat conversation. ``AgentSession`` tracks an autonomous agent run
with its lifecycle status and A2A peer references. Sandbox execution is FUTURE — the
field exists (``sandbox_ref``) but stays null in phase 1.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class SessionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"


class Session(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    subject_id: str | None = None
    title: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    KILLED = "killed"  # DD-11: trajectory monitor crossed KILL — reaped, not a soft failure
    ZOMBIE = "zombie"


class AgentSession(BaseModel):
    agent_session_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    tenant_id: str
    subject_id: str | None = None
    status: AgentStatus = AgentStatus.RUNNING
    sandbox_ref: str | None = None  # FUTURE EXTENSION — E2B sandbox execution
    a2a_peers: list[str] = Field(default_factory=list)
    iterations: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)
    started_at: datetime | None = None
    ended_at: datetime | None = None
