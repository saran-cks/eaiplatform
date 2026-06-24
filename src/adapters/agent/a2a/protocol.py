"""Wire protocol schemas for Agent-to-Agent (A2A) peer exchanges.

These define the standard payload structures compatible across autonomous systems
for federated query forwarding, response delivery, and consent/scope challenge exchanges.
"""

from __future__ import annotations

from pydantic import BaseModel


class PeerQueryPayload(BaseModel):
    """Payload sent to request information or actions from a peer agent."""

    requesting_agent_id: str
    tenant_id: str
    query: str
    scope: dict          # permission scope forwarded to peer


class PeerResponsePayload(BaseModel):
    """Payload received from a peer agent containing result or status details."""

    responding_agent_id: str
    content: str
    success: bool
    error: str | None


class ConsentChallenge(BaseModel):
    """Consent validation payload generated during cross-tenant boundary traversals."""

    challenge_id: str
    requesting_tenant_id: str
    requested_scope: dict
