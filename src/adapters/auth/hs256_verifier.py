"""HS256TokenVerifier — TokenVerifierPort for local dev (shared-secret JWT).

The tokens are minted outside the API (dev-mint helper / paste, DD-19) and already carry
the canonical claims ``tenant_id`` / ``permissions`` / ``sub``, so verification is a plain
symmetric ``jwt.decode`` with no claim remapping. This is the same logic that lived inline
in the middleware before the verifier seam was introduced; Cognito is the prod swap.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import jwt

from core.ports.token_verifier import TokenVerificationError

logger = logging.getLogger(__name__)


class HS256TokenVerifier:
    """Verify an HS256 shared-secret JWT and return its claims unchanged."""

    def __init__(self, *, secret: str, algorithm: str, audience: str, issuer: str) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._audience = audience
        self._issuer = issuer

    async def verify(self, token: str) -> Mapping[str, object]:
        try:
            claims: dict[str, object] = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenVerificationError("Token expired") from exc
        except jwt.InvalidTokenError as exc:
            logger.warning("HS256 JWT decode failed: %s", exc)
            raise TokenVerificationError("Invalid token") from exc
        return claims

    async def close(self) -> None:
        # Nothing to release — symmetric verification holds no client/connection.
        return None
