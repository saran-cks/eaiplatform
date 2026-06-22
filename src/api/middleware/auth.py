"""JWT authentication middleware.

Decodes the ``Authorization: Bearer <token>`` header using the configured HS256
shared secret and builds a ``PermissionScope`` value object that is attached to
``request.state.scope``.

Public paths (health probes, docs) bypass authentication entirely.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.domain.value_objects.permission_scope import PermissionScope

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
    """Extract and verify JWT, build PermissionScope, attach to request.state."""

    def __init__(self, app: FastAPI, *, secret: str, algorithm: str, audience: str) -> None:
        super().__init__(app)
        self._secret = secret
        self._algorithm = algorithm
        self._audience = audience

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
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
            )
        except jwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"detail": "Token expired"})
        except jwt.InvalidTokenError as exc:
            logger.warning("JWT decode failed: %s", exc)
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})

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
