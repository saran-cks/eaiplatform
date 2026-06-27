"""AuthMiddleware JWT validation tests.

Regression coverage for the issuer (`iss`) gap: the middleware must reject tokens
whose issuer is wrong or missing, not just validate signature + audience.
"""

from __future__ import annotations

import jwt
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from api.middleware.auth import AuthMiddleware

SECRET = "test-secret-at-least-32-bytes-long-for-hs256"
ALGORITHM = "HS256"
AUDIENCE = "core-api-clients"
ISSUER = "core-api"


def _make_token(**overrides: object) -> str:
    claims: dict[str, object] = {
        "tenant_id": "tenant-1",
        "sub": "user-123",
        "permissions": ["read"],
        "aud": AUDIENCE,
        "iss": ISSUER,
    }
    claims.update(overrides)
    # Drop any claim explicitly set to None (lets a test omit `iss`/`aud`).
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, SECRET, algorithm=ALGORITHM)


async def _whoami(request: Request) -> JSONResponse:
    scope = request.state.scope
    return JSONResponse({"tenant_id": scope.tenant_id, "subject_id": scope.subject_id})


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=[Route("/whoami", _whoami)])
    app.add_middleware(
        AuthMiddleware,
        secret=SECRET,
        algorithm=ALGORITHM,
        audience=AUDIENCE,
        issuer=ISSUER,
    )
    return TestClient(app)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_with_correct_issuer_passes(client: TestClient):
    resp = client.get("/whoami", headers=_auth(_make_token()))
    assert resp.status_code == 200
    assert resp.json() == {"tenant_id": "tenant-1", "subject_id": "user-123"}


def test_wrong_issuer_is_rejected(client: TestClient):
    token = _make_token(iss="attacker-idp")
    resp = client.get("/whoami", headers=_auth(token))
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid token"}


def test_missing_issuer_is_rejected(client: TestClient):
    token = _make_token(iss=None)  # omit the iss claim entirely
    resp = client.get("/whoami", headers=_auth(token))
    assert resp.status_code == 401


def test_wrong_audience_still_rejected(client: TestClient):
    token = _make_token(aud="someone-else")
    resp = client.get("/whoami", headers=_auth(token))
    assert resp.status_code == 401


def test_missing_bearer_header_is_rejected(client: TestClient):
    resp = client.get("/whoami")
    assert resp.status_code == 401
