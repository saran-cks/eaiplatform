"""CognitoJwtVerifier tests — RS256/JWKS verification + Cognito→canonical claim mapping.

No live Cognito: an in-test RSA keypair mints tokens, and the pool's JWKS endpoint is
served by an httpx.MockTransport so signature verification runs for real against a
fake-but-valid key set. Live-pool verification (real issuer, real rotation) is deferred to
a smoke test (docs/smoke-tests.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from adapters.auth.cognito_verifier import CognitoJwtVerifier
from core.ports.token_verifier import TokenVerificationError

REGION = "us-east-1"
POOL_ID = "us-east-1_testpool"
CLIENT_ID = "app-client-123"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"
KID = "test-key-1"

# One keypair for the whole module (RSA gen is slow).
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(kid: str = KID) -> dict[str, object]:
    """Public JWKS document as Cognito would serve it, for the module keypair."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def _mint(*, kid: str = KID, **claims: object) -> str:
    base: dict[str, object] = {
        "sub": "user-1",
        "iss": ISSUER,
        "token_use": "access",
        "client_id": CLIENT_ID,
        "cognito:groups": ["read", "chat:write"],
        "custom:tenant_id": "tenant-1",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    base.update(claims)
    base = {k: v for k, v in base.items() if v is not None}
    return jwt.encode(base, _PRIVATE_KEY, algorithm="RS256", headers={"kid": kid})


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _jwks_handler(counter: list[int] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.append(1)
        return httpx.Response(200, json=_jwks())

    return handle


def _verifier(
    handler: Callable[[httpx.Request], httpx.Response], **kw: object
) -> CognitoJwtVerifier:
    return CognitoJwtVerifier(
        region=REGION,
        user_pool_id=POOL_ID,
        app_client_id=CLIENT_ID,
        http_client=_client(handler),
        **kw,  # type: ignore[arg-type]
    )


async def test_valid_access_token_maps_groups_and_tenant():
    v = _verifier(_jwks_handler())
    claims = await v.verify(_mint())
    assert claims["tenant_id"] == "tenant-1"
    assert claims["permissions"] == ["read", "chat:write"]
    assert claims["sub"] == "user-1"


async def test_expired_token_is_rejected():
    v = _verifier(_jwks_handler())
    expired = _mint(exp=int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()))
    with pytest.raises(TokenVerificationError, match="expired"):
        await v.verify(expired)


async def test_wrong_issuer_is_rejected():
    v = _verifier(_jwks_handler())
    with pytest.raises(TokenVerificationError):
        await v.verify(_mint(iss="https://evil.example.com/pool"))


async def test_wrong_client_id_is_rejected():
    v = _verifier(_jwks_handler())
    with pytest.raises(TokenVerificationError, match="application"):
        await v.verify(_mint(client_id="some-other-app"))


async def test_wrong_token_use_is_rejected():
    # Verifier defaults to "access"; an id token must be refused.
    v = _verifier(_jwks_handler())
    with pytest.raises(TokenVerificationError):
        await v.verify(_mint(token_use="id"))


async def test_unknown_kid_is_rejected_after_refresh():
    v = _verifier(_jwks_handler())
    with pytest.raises(TokenVerificationError, match="Signing key"):
        await v.verify(_mint(kid="rotated-away-kid"))


async def test_missing_tenant_claim_leaves_tenant_absent():
    # Without a mapped tenant_id, PermissionScope.from_claims (downstream) will 403.
    v = _verifier(_jwks_handler())
    claims = await v.verify(_mint(**{"custom:tenant_id": None}))
    assert "tenant_id" not in claims


async def test_id_token_mode_verifies_aud():
    handler = _jwks_handler()
    v = _verifier(handler, token_use="id")
    token = _mint(token_use="id", aud=CLIENT_ID, client_id=None)
    claims = await v.verify(token)
    assert claims["tenant_id"] == "tenant-1"

    bad_aud = _mint(token_use="id", aud="wrong-app", client_id=None)
    with pytest.raises(TokenVerificationError):
        await v.verify(bad_aud)


async def test_jwks_is_cached_across_calls():
    counter: list[int] = []
    v = _verifier(_jwks_handler(counter))
    await v.verify(_mint())
    await v.verify(_mint())
    await v.verify(_mint())
    assert sum(counter) == 1  # fetched once, then served from cache


async def test_jwks_fetch_failure_fails_closed():
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    v = _verifier(boom)
    with pytest.raises(TokenVerificationError, match="signing key"):
        await v.verify(_mint())
