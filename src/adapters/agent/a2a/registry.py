"""A2A peer routing and directory registry stub.

Maintains peer registration bindings and handles message forwarding.
"""

from __future__ import annotations

from adapters.agent.a2a.protocol import PeerQueryPayload, PeerResponsePayload


class PeerRegistry:
    """Directory registry to resolve and invoke peer agents across system boundaries."""

    def __init__(self, peers: dict[str, str] | None = None) -> None:
        # peers mapping: agent_id -> target_url
        self._peers = peers or {}

    async def resolve(self, agent_id: str) -> str:
        """Resolve the target HTTP url endpoint associated with an agent identifier."""
        if agent_id not in self._peers:
            raise KeyError(f"Peer agent {agent_id} not registered")
        return self._peers[agent_id]

    async def query_peer(self, target_url: str, payload: PeerQueryPayload) -> PeerResponsePayload:
        """Forward a query payload to the peer target URL (simulated stub for Phase 1)."""
        return PeerResponsePayload(
            responding_agent_id=payload.requesting_agent_id,
            content="A2A simulation response from mock backend",
            success=True,
            error=None,
        )
