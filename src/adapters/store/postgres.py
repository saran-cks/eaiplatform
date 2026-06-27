"""Postgres adapter implementing StorePort via raw asyncpg.

Handles automatic table bootstrapping on first query via an internal connection pool.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import asyncpg

from config.settings import Settings
from core.domain.entities.document import Document, Source, SourceKind
from core.domain.entities.message import Message, Role, Turn
from core.domain.entities.session import AgentSession, AgentStatus, Session, SessionStatus
from core.ports.store import StorePort

logger = logging.getLogger(__name__)


class PostgresAdapter(StorePort):
    """Postgres adapter implementing StorePort."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dsn = settings.postgres_dsn
        self._pool: asyncpg.Pool | None = None
        self._pool_lock = asyncio.Lock()

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is None:
                logger.info("Initializing asyncpg connection pool to: %s", self._settings.postgres_host)
                self._pool = await asyncpg.create_pool(
                    self._dsn,
                    min_size=self._settings.postgres_pool_min,
                    max_size=self._settings.postgres_pool_max,
                )
                # Auto bootstrap database tables
                await self._bootstrap_tables()
            return self._pool

    async def _bootstrap_tables(self) -> None:
        """Create database tables if they do not exist."""
        ddl = """
        -- Sessions table
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            subject_id TEXT,
            title TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_tenant_subject ON sessions(tenant_id, subject_id);

        -- Messages table
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

        -- Turns table (grouping user/assistant interactions with grounding and feedback)
        CREATE TABLE IF NOT EXISTS turns (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            user_message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
            assistant_message_id TEXT REFERENCES messages(message_id) ON DELETE CASCADE,
            retrieved_chunks JSONB NOT NULL DEFAULT '[]'::jsonb,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);

        -- Agent Sessions table
        CREATE TABLE IF NOT EXISTS agent_sessions (
            agent_session_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            subject_id TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            sandbox_ref TEXT,
            a2a_peers JSONB NOT NULL DEFAULT '[]'::jsonb,
            iterations INTEGER NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP WITH TIME ZONE
        );
        CREATE INDEX IF NOT EXISTS idx_agent_sessions_tenant ON agent_sessions(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);

        -- Documents table (Read-only metadata reference registry)
        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_uri TEXT,
            source_label TEXT,
            title TEXT,
            permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            indexed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id);

        -- Artifacts table (Monaco generated code/files)
        CREATE TABLE IF NOT EXISTS artifacts (
            file_id TEXT PRIMARY KEY,
            agent_session_id TEXT NOT NULL REFERENCES agent_sessions(agent_session_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_artifacts_agent_session ON artifacts(agent_session_id);
        CREATE INDEX IF NOT EXISTS idx_artifacts_tenant ON artifacts(tenant_id);

        -- Connector Credentials table (MCP integration)
        CREATE TABLE IF NOT EXISTS connector_credentials (
            tenant_id TEXT NOT NULL,
            connector TEXT NOT NULL,
            credentials JSONB NOT NULL,
            PRIMARY KEY (tenant_id, connector)
        );
        """
        logger.info("Bootstrapping Postgres database schema...")
        async with self._pool.acquire() as conn:
            await conn.execute(ddl)
        logger.info("Postgres schema bootstrapped successfully.")

    # --- chat sessions ---
    async def create_session(self, session: Session) -> Session:
        query = """
            INSERT INTO sessions (session_id, tenant_id, subject_id, title, status, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (session_id) DO UPDATE SET
                title = EXCLUDED.title,
                status = EXCLUDED.status,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at
            RETURNING created_at, updated_at
        """
        created_at = session.created_at or datetime.now(UTC)
        updated_at = session.updated_at or datetime.now(UTC)
        metadata_json = json.dumps(session.metadata)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                session.session_id,
                session.tenant_id,
                session.subject_id,
                session.title,
                session.status.value,
                metadata_json,
                created_at,
                updated_at
            )
            if row:
                session.created_at = row["created_at"]
                session.updated_at = row["updated_at"]
        return session

    async def get_session(self, *, session_id: str, tenant_id: str) -> Session | None:
        query = """
            SELECT session_id, tenant_id, subject_id, title, status, metadata, created_at, updated_at
            FROM sessions
            WHERE session_id = $1 AND tenant_id = $2
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, session_id, tenant_id)
            if not row:
                return None
            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            return Session(
                session_id=row["session_id"],
                tenant_id=row["tenant_id"],
                subject_id=row["subject_id"],
                title=row["title"],
                status=SessionStatus(row["status"]),
                metadata=meta or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )

    async def list_sessions(
        self, *, tenant_id: str, subject_id: str | None = None, limit: int = 50
    ) -> list[Session]:
        if subject_id is not None:
            query = """
                SELECT session_id, tenant_id, subject_id, title, status, metadata, created_at, updated_at
                FROM sessions
                WHERE tenant_id = $1 AND subject_id = $2
                ORDER BY updated_at DESC
                LIMIT $3
            """
            args = (tenant_id, subject_id, limit)
        else:
            query = """
                SELECT session_id, tenant_id, subject_id, title, status, metadata, created_at, updated_at
                FROM sessions
                WHERE tenant_id = $1
                ORDER BY updated_at DESC
                LIMIT $2
            """
            args = (tenant_id, limit)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            sessions = []
            for row in rows:
                meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                sessions.append(
                    Session(
                        session_id=row["session_id"],
                        tenant_id=row["tenant_id"],
                        subject_id=row["subject_id"],
                        title=row["title"],
                        status=SessionStatus(row["status"]),
                        metadata=meta or {},
                        created_at=row["created_at"],
                        updated_at=row["updated_at"]
                    )
                )
            return sessions

    async def set_session_status(
        self, *, session_id: str, tenant_id: str, status: SessionStatus
    ) -> None:
        query = """
            UPDATE sessions
            SET status = $1, updated_at = CURRENT_TIMESTAMP
            WHERE session_id = $2 AND tenant_id = $3
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, status.value, session_id, tenant_id)

    async def delete_session(self, *, session_id: str, tenant_id: str) -> None:
        query = """
            DELETE FROM sessions
            WHERE session_id = $1 AND tenant_id = $2
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, session_id, tenant_id)

    # --- messages / turns ---
    async def append_turn(self, turn: Turn) -> Turn:
        msg_query = """
            INSERT INTO messages (message_id, session_id, role, content, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (message_id) DO NOTHING
        """
        user_created_at = turn.user_message.created_at or datetime.now(UTC)
        user_meta = json.dumps(turn.user_message.metadata)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Insert User Message
                await conn.execute(
                    msg_query,
                    turn.user_message.message_id,
                    turn.session_id,
                    turn.user_message.role.value,
                    turn.user_message.content,
                    user_meta,
                    user_created_at
                )

                # 2. Insert Assistant Message if present
                assistant_id = None
                if turn.assistant_message:
                    assistant_id = turn.assistant_message.message_id
                    assistant_created_at = turn.assistant_message.created_at or datetime.now(UTC)
                    assistant_meta = json.dumps(turn.assistant_message.metadata)
                    await conn.execute(
                        msg_query,
                        assistant_id,
                        turn.session_id,
                        turn.assistant_message.role.value,
                        turn.assistant_message.content,
                        assistant_meta,
                        assistant_created_at
                    )

                # 3. Serialize and Insert Turn
                chunks_data = [chunk.model_dump() for chunk in turn.retrieved_chunks]
                # Convert frozensets to list to allow standard JSON serialization
                for c in chunks_data:
                    if "permissions" in c and isinstance(c["permissions"], (frozenset, set)):
                        c["permissions"] = list(c["permissions"])

                chunks_json = json.dumps(chunks_data)

                turn_query = """
                    INSERT INTO turns (turn_id, session_id, user_message_id, assistant_message_id, retrieved_chunks, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (turn_id) DO UPDATE SET
                        assistant_message_id = EXCLUDED.assistant_message_id,
                        retrieved_chunks = EXCLUDED.retrieved_chunks
                    RETURNING created_at
                """
                turn_created_at = turn.created_at or datetime.now(UTC)
                row = await conn.fetchrow(
                    turn_query,
                    turn.turn_id,
                    turn.session_id,
                    turn.user_message.message_id,
                    assistant_id,
                    chunks_json,
                    turn_created_at
                )
                if row:
                    turn.created_at = row["created_at"]
        return turn

    async def get_messages(
        self, *, session_id: str, tenant_id: str, limit: int = 50
    ) -> list[Message]:
        query = """
            SELECT m.message_id, m.session_id, m.role, m.content, m.metadata, m.created_at
            FROM messages m
            JOIN sessions s ON m.session_id = s.session_id
            WHERE m.session_id = $1 AND s.tenant_id = $2
            ORDER BY m.created_at ASC
            LIMIT $3
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, session_id, tenant_id, limit)
            messages = []
            for row in rows:
                meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                messages.append(
                    Message(
                        message_id=row["message_id"],
                        session_id=row["session_id"],
                        role=Role(row["role"]),
                        content=row["content"],
                        metadata=meta or {},
                        created_at=row["created_at"]
                    )
                )
            return messages

    # --- agent sessions ---
    async def create_agent_session(self, agent_session: AgentSession) -> AgentSession:
        query = """
            INSERT INTO agent_sessions (
                agent_session_id, session_id, tenant_id, subject_id, status,
                sandbox_ref, a2a_peers, iterations, metadata, started_at, ended_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (agent_session_id) DO UPDATE SET
                status = EXCLUDED.status,
                a2a_peers = EXCLUDED.a2a_peers,
                iterations = EXCLUDED.iterations,
                metadata = EXCLUDED.metadata,
                ended_at = EXCLUDED.ended_at
            RETURNING started_at
        """
        started_at = agent_session.started_at or datetime.now(UTC)
        peers_json = json.dumps(agent_session.a2a_peers)
        metadata_json = json.dumps(agent_session.metadata)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                agent_session.agent_session_id,
                agent_session.session_id,
                agent_session.tenant_id,
                agent_session.subject_id,
                agent_session.status.value,
                agent_session.sandbox_ref,
                peers_json,
                agent_session.iterations,
                metadata_json,
                started_at,
                agent_session.ended_at
            )
            if row:
                agent_session.started_at = row["started_at"]
        return agent_session

    async def get_agent_session(
        self, *, agent_session_id: str, tenant_id: str
    ) -> AgentSession | None:
        query = """
            SELECT agent_session_id, session_id, tenant_id, subject_id, status,
                   sandbox_ref, a2a_peers, iterations, metadata, started_at, ended_at
            FROM agent_sessions
            WHERE agent_session_id = $1 AND tenant_id = $2
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, agent_session_id, tenant_id)
            if not row:
                return None

            peers = json.loads(row["a2a_peers"]) if isinstance(row["a2a_peers"], str) else row["a2a_peers"]
            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

            return AgentSession(
                agent_session_id=row["agent_session_id"],
                session_id=row["session_id"],
                tenant_id=row["tenant_id"],
                subject_id=row["subject_id"],
                status=AgentStatus(row["status"]),
                sandbox_ref=row["sandbox_ref"],
                a2a_peers=peers or [],
                iterations=row["iterations"],
                metadata=meta or {},
                started_at=row["started_at"],
                ended_at=row["ended_at"]
            )

    async def update_agent_status(
        self, *, agent_session_id: str, status: AgentStatus
    ) -> None:
        ended_at = None
        if status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.ZOMBIE, AgentStatus.INTERRUPTED):
            ended_at = datetime.now(UTC)
            query = """
                UPDATE agent_sessions
                SET status = $1, ended_at = COALESCE(ended_at, $2)
                WHERE agent_session_id = $3
            """
            args = (status.value, ended_at, agent_session_id)
        else:
            query = """
                UPDATE agent_sessions
                SET status = $1
                WHERE agent_session_id = $2
            """
            args = (status.value, agent_session_id)

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, *args)

    async def list_active_agent_sessions(self) -> list[AgentSession]:
        query = """
            SELECT agent_session_id, session_id, tenant_id, subject_id, status,
                   sandbox_ref, a2a_peers, iterations, metadata, started_at, ended_at
            FROM agent_sessions
            WHERE status = 'running'
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            sessions = []
            for row in rows:
                peers = json.loads(row["a2a_peers"]) if isinstance(row["a2a_peers"], str) else row["a2a_peers"]
                meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                sessions.append(
                    AgentSession(
                        agent_session_id=row["agent_session_id"],
                        session_id=row["session_id"],
                        tenant_id=row["tenant_id"],
                        subject_id=row["subject_id"],
                        status=AgentStatus(row["status"]),
                        sandbox_ref=row["sandbox_ref"],
                        a2a_peers=peers or [],
                        iterations=row["iterations"],
                        metadata=meta or {},
                        started_at=row["started_at"],
                        ended_at=row["ended_at"]
                    )
                )
            return sessions

    # --- documents (registry, read side) ---
    async def get_document(self, *, document_id: str, tenant_id: str) -> Document | None:
        query = """
            SELECT document_id, tenant_id, source_kind, source_uri, source_label,
                   title, permissions, chunk_count, metadata, indexed_at
            FROM documents
            WHERE document_id = $1 AND tenant_id = $2
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, document_id, tenant_id)
            if not row:
                return None

            perms = json.loads(row["permissions"]) if isinstance(row["permissions"], str) else row["permissions"]
            meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]

            source = Source(
                source_id=row["document_id"],
                kind=SourceKind(row["source_kind"]),
                uri=row["source_uri"],
                label=row["source_label"]
            )

            return Document(
                document_id=row["document_id"],
                tenant_id=row["tenant_id"],
                source=source,
                title=row["title"],
                permissions=frozenset(perms or []),
                chunk_count=row["chunk_count"],
                metadata=meta or {},
                indexed_at=row["indexed_at"]
            )

    # --- feedback ---
    async def record_feedback(
        self, *, turn_id: str, tenant_id: str, rating: int, comment: str | None = None
    ) -> None:
        query = """
            UPDATE turns t
            SET rating = $1, comment = $2
            FROM sessions s
            WHERE t.session_id = s.session_id AND t.turn_id = $3 AND s.tenant_id = $4
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, rating, comment, turn_id, tenant_id)

    # --- artifacts (generated code, Monaco display) ---
    async def save_artifact(
        self, *, agent_session_id: str, tenant_id: str, file_id: str, name: str, content: str
    ) -> None:
        query = """
            INSERT INTO artifacts (file_id, agent_session_id, tenant_id, name, content, created_at)
            VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
            ON CONFLICT (file_id) DO UPDATE SET
                name = EXCLUDED.name,
                content = EXCLUDED.content
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(query, file_id, agent_session_id, tenant_id, name, content)

    async def list_artifacts(
        self, *, agent_session_id: str, tenant_id: str
    ) -> list[dict[str, object]]:
        query = """
            SELECT file_id, agent_session_id, tenant_id, name, content, created_at
            FROM artifacts
            WHERE agent_session_id = $1 AND tenant_id = $2
            ORDER BY created_at DESC
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, agent_session_id, tenant_id)
            # Convert Record objects to pure dicts
            return [dict(row) for row in rows]

    async def get_artifact(
        self, *, file_id: str, tenant_id: str
    ) -> dict[str, object] | None:
        query = """
            SELECT file_id, agent_session_id, tenant_id, name, content, created_at
            FROM artifacts
            WHERE file_id = $1 AND tenant_id = $2
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, file_id, tenant_id)
            return dict(row) if row else None

    # --- connector credentials (MCP) ---
    async def get_connector_credentials(
        self, *, tenant_id: str, connector: str
    ) -> dict[str, object] | None:
        query = """
            SELECT credentials
            FROM connector_credentials
            WHERE tenant_id = $1 AND connector = $2
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, tenant_id, connector)
            if not row:
                return None
            creds = row["credentials"]
            return json.loads(creds) if isinstance(creds, str) else creds

    # --- lifecycle ---
    async def healthcheck(self) -> bool:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.warning("Postgres healthcheck failed: %s", e)
            return False

    async def close_expired_sessions(self, *, older_than_seconds: int) -> Sequence[str]:
        query = """
            UPDATE sessions
            SET status = 'expired', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'active'
              AND updated_at < (CURRENT_TIMESTAMP - $1 * INTERVAL '1 second')
            RETURNING session_id
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, older_than_seconds)
            return [row["session_id"] for row in rows]

    async def close(self) -> None:
        """Close the underlying connection pool on application shutdown."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Postgres connection pool closed.")
