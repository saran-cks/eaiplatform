"""TokenVerifierPort — verify a bearer token and yield canonical claims.

The inbound-auth seam. ``api/middleware/auth.py`` holds a ``TokenVerifierPort`` and
does not know *how* a token is verified — only that ``verify`` returns claims it can
hand to ``PermissionScope.from_claims`` (canonical keys ``tenant_id``, ``permissions``,
``sub``) or raises ``TokenVerificationError``.

Two adapters implement it (bound in ``config/di.py`` by ``AUTH_PROVIDER``): the HS256
shared-secret verifier for local dev, and the Cognito RS256/JWKS verifier for prod. The
adapter is the anti-corruption layer — a provider that speaks its own claim names (e.g.
Cognito's ``cognito:groups`` / ``custom:tenant_id``) normalises them to the canonical
keys, so neither the middleware nor ``PermissionScope`` knows the provider (DD-19).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


class TokenVerificationError(Exception):
    """Raised when a token fails signature/claim verification.

    Carries a client-safe ``detail`` the middleware surfaces in the 401 body; it must
    never leak internals (stack, secret, raw provider error). Default: ``"Invalid token"``.
    """

    def __init__(self, detail: str = "Invalid token") -> None:
        super().__init__(detail)
        self.detail = detail


@runtime_checkable
class TokenVerifierPort(Protocol):
    async def verify(self, token: str) -> Mapping[str, object]:
        """Verify signature + standard claims; return normalised claims.

        The returned mapping uses the canonical keys ``PermissionScope.from_claims``
        expects (``tenant_id``, ``permissions``, ``sub``). Raises
        ``TokenVerificationError`` on any failure (bad signature, wrong issuer/audience,
        expired, unknown key, wrong token type).
        """
        ...

    async def close(self) -> None:
        """Release any underlying client/connection (e.g. the JWKS HTTP client)."""
        ...
