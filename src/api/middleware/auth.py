"""JWT authentication middleware.

Verifies the ``Authorization: Bearer <token>`` header via the injected
``TokenVerifierPort`` (HS256 shared-secret in dev, Cognito RS256/JWKS in prod — bound in
``config/di.py`` by ``AUTH_PROVIDER``) and builds a ``PermissionScope`` value object that
is attached to ``request.state.scope``. The middleware knows nothing about *how* a token
is verified — only the port's contract (DD-19).

Public paths (health probes, docs) bypass authentication entirely.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.token_verifier import TokenVerificationError, TokenVerifierPort

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Paths that do NOT require a JWT.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Verify the bearer token via the port, build PermissionScope, attach to request.state."""

    def __init__(self, app: FastAPI, *, verifier: TokenVerifierPort) -> None:
        super().__init__(app)
        self._verifier = verifier

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip auth for public paths.
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or malformed Authorization header"},
            )

        token = auth_header[7:]  # Strip "Bearer "

        try:
            claims = await self._verifier.verify(token)
        except TokenVerificationError as exc:
            logger.warning("Token verification failed: %s", exc.detail)
            return JSONResponse(status_code=401, content={"detail": exc.detail})

        try:
            scope = PermissionScope.from_claims(claims)
        except Exception as exc:
            logger.warning("PermissionScope construction failed: %s", exc)
            return JSONResponse(
                status_code=403,
                content={"detail": f"Invalid token claims: {exc}"},
            )

        request.state.scope = scope
        return await call_next(request)
