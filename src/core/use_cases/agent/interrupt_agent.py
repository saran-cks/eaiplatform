"""InterruptAgentUseCase — ownership-checked cooperative cancellation.

The cooperative-cancel signal in the runner keys purely off ``agent_session_id`` and knows
nothing about who owns the session. Authenticating the caller is not enough: without an
ownership check any authenticated principal (including one from another tenant) could cancel
any running agent by id — a cross-tenant DoS. So this use case resolves the session
tenant-scoped from the store first and only dispatches ``interrupt`` when the caller's scope
owns it. A miss is indistinguishable from "does not exist" and surfaces as a 404 — we never
confirm the existence of another tenant's session.
"""

from __future__ import annotations

import logging

from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.agent import AgentPort
from core.ports.store import StorePort

logger = logging.getLogger(__name__)


class InterruptAgentUseCase:
    """Verifies tenant ownership, then flags a running agent for cooperative cancellation."""

    def __init__(self, store: StorePort, agent: AgentPort) -> None:
        self._store = store
        self._agent = agent

    async def execute(self, *, agent_session_id: str, scope: PermissionScope) -> bool:
        """Interrupt the session iff the scope's tenant owns it.

        Returns ``True`` when the session was owned and the interrupt dispatched, ``False``
        when no session with this id exists for the caller's tenant (route → 404). Failures
        of the underlying interrupt propagate to the caller.
        """
        owned = await self._store.get_agent_session(
            agent_session_id=agent_session_id,
            tenant_id=scope.tenant_id,
        )
        if owned is None:
            logger.warning(
                "Interrupt denied: session %s not found for tenant %s",
                agent_session_id,
                scope.tenant_id,
            )
            return False

        await self._agent.interrupt(agent_session_id=agent_session_id)
        return True
