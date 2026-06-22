"""StorePort — all durable Postgres operations (asyncpg adapter).

Every method is scoped by tenant via the entities/arguments passed in; the adapter must
not bypass the supplied tenant_id. Turn persistence is idempotent on ``message_id``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from core.domain.entities.document import Document
from core.domain.entities.message import Message, Turn
from core.domain.entities.session import AgentSession, AgentStatus, Session, SessionStatus


@runtime_checkable
class StorePort(Protocol):
    # --- chat sessions ---
    async def create_session(self, session: Session) -> Session:
        ...

    async def get_session(self, *, session_id: str, tenant_id: str) -> Session | None:
        ...

    async def list_sessions(
        self, *, tenant_id: str, subject_id: str | None = None, limit: int = 50
    ) -> list[Session]:
        ...

    async def set_session_status(
        self, *, session_id: str, tenant_id: str, status: SessionStatus
    ) -> None:
        ...

    async def delete_session(self, *, session_id: str, tenant_id: str) -> None:
        ...

    # --- messages / turns ---
    async def append_turn(self, turn: Turn) -> Turn:
        """Persist a turn idempotently (message_id as idempotency key)."""
        ...

    async def get_messages(
        self, *, session_id: str, tenant_id: str, limit: int = 50
    ) -> list[Message]:
        ...

    # --- agent sessions ---
    async def create_agent_session(self, agent_session: AgentSession) -> AgentSession:
        ...

    async def get_agent_session(
        self, *, agent_session_id: str, tenant_id: str
    ) -> AgentSession | None:
        ...

    async def update_agent_status(
        self, *, agent_session_id: str, status: AgentStatus
    ) -> None:
        ...

    async def list_active_agent_sessions(self) -> list[AgentSession]:
        """Used by the agent reaper to find TTL-exceeded / orphaned agents."""
        ...

    # --- documents (registry, read side) ---
    async def get_document(self, *, document_id: str, tenant_id: str) -> Document | None:
        ...

    # --- feedback ---
    async def record_feedback(
        self, *, turn_id: str, tenant_id: str, rating: int, comment: str | None = None
    ) -> None:
        ...

    # --- artifacts (generated code, Monaco display) ---
    async def save_artifact(
        self, *, agent_session_id: str, tenant_id: str, file_id: str, name: str, content: str
    ) -> None:
        ...

    async def list_artifacts(
        self, *, agent_session_id: str, tenant_id: str
    ) -> list[dict[str, object]]:
        ...

    async def get_artifact(
        self, *, file_id: str, tenant_id: str
    ) -> dict[str, object] | None:
        ...

    # --- connector credentials (MCP) ---
    async def get_connector_credentials(
        self, *, tenant_id: str, connector: str
    ) -> dict[str, object] | None:
        ...

    # --- lifecycle ---
    async def healthcheck(self) -> bool:
        ...

    async def close_expired_sessions(self, *, older_than_seconds: int) -> Sequence[str]:
        """Mark dangling sessions closed; returns affected ids (session_cleanup daemon)."""
        ...
