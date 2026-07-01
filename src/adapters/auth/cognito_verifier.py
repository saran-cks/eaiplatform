"""CognitoJwtVerifier — TokenVerifierPort for AWS Cognito (RS256 + JWKS).

The prod swap DD-19 anticipated ("swap the verifier adapter for RS256/JWKS later"). It
verifies a Cognito-issued JWT end to end:

* fetch the pool's public keys from ``…/.well-known/jwks.json`` (cached, async httpx),
  match the token's ``kid``, refresh once on an unknown ``kid`` (key rotation);
* verify the RS256 signature, ``iss`` (the user-pool URL), ``exp``, and ``token_use``
  (access vs id — configurable), plus the app-client binding: ``aud`` for id tokens,
  ``client_id`` for access tokens (Cognito access tokens carry no ``aud``);
* normalise Cognito's claim names to the canonical shape ``PermissionScope`` consumes —
  ``cognito:groups`` → ``permissions``, ``custom:tenant_id`` → ``tenant_id`` (both claim
  names configurable). This adapter is the anti-corruption layer; the middleware and the
  domain never learn a Cognito-specific claim name.

Token choice (config ``COGNITO_TOKEN_USE``): the **access** token is the correct API
credential and is the default. It natively carries ``cognito:groups`` + ``client_id`` +
``scope`` but NOT custom attributes — surfacing ``tenant_id`` there needs a
pre-token-generation Lambda. Set ``COGNITO_TOKEN_USE=id`` to instead read the id token,
which carries ``custom:tenant_id`` out of the box (no Lambda) at the cost of using an
identity token for authorization.

Fail-closed: any verification problem raises ``TokenVerificationError`` (→ 401). A JWKS
fetch failure raises too — an unauthenticated request must never be let through.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping

import httpx
import jwt

from core.ports.token_verifier import TokenVerificationError

logger = logging.getLogger(__name__)

# Tight timeout: a wedged JWKS endpoint must fail the request fast, not stall it.
_JWKS_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
# Floor between real JWKS network fetches. Bounds the DoS where a flood of tokens bearing
# random ``kid``s would otherwise force a fetch per request. Within the floor an unknown
# kid fails closed; genuine Cognito rotation is rare and keys overlap, so this is safe.
_MIN_REFRESH_INTERVAL_S = 30.0


class CognitoJwtVerifier:
    """Verify AWS Cognito JWTs against the user pool's JWKS and normalise claims."""

    def __init__(
        self,
        *,
        region: str,
        user_pool_id: str,
        app_client_id: str,
        token_use: str = "access",
        tenant_claim: str = "custom:tenant_id",
        groups_claim: str = "cognito:groups",
        jwks_cache_ttl: int = 3600,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self._jwks_url = f"{self._issuer}/.well-known/jwks.json"
        self._app_client_id = app_client_id
        self._token_use = token_use
        self._tenant_claim = tenant_claim
        self._groups_claim = groups_claim
        self._ttl = jwks_cache_ttl
        self._client = http_client or httpx.AsyncClient(timeout=_JWKS_TIMEOUT)
        # kid -> cryptography public key, plus the monotonic time of the last successful fetch.
        self._keys: dict[str, object] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()
        logger.info(
            "CognitoJwtVerifier initialised (issuer=%s token_use=%s)",
            self._issuer,
            self._token_use,
        )

    async def verify(self, token: str) -> Mapping[str, object]:
        key = await self._resolve_key(token)

        # Access tokens carry no ``aud`` (the app client is in ``client_id``); only verify
        # ``aud`` for id tokens, and only when an app client id is configured.
        verify_aud = self._token_use == "id" and bool(self._app_client_id)
        try:
            claims: dict[str, object] = jwt.decode(
                token,
                key,  # type: ignore[arg-type]  # cryptography public key from the JWK
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._app_client_id if verify_aud else None,
                options={
                    "require": ["exp", "iss", "token_use"],
                    "verify_aud": verify_aud,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenVerificationError("Token expired") from exc
        except jwt.InvalidTokenError as exc:
            logger.warning("Cognito JWT decode failed: %s", exc)
            raise TokenVerificationError("Invalid token") from exc

        self._check_token_use(claims)
        self._check_client_binding(claims)
        return self._normalise(claims)

    # --- key resolution / JWKS caching ---------------------------------------------------

    async def _resolve_key(self, token: str) -> object:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.InvalidTokenError as exc:
            raise TokenVerificationError("Malformed token header") from exc
        if not isinstance(kid, str) or not kid:
            raise TokenVerificationError("Token missing 'kid' header")

        key = self._cached_key(kid)
        if key is not None:
            return key
        # Cache miss or stale: refresh once (handles key rotation), then retry.
        await self._refresh_jwks()
        key = self._keys.get(kid)
        if key is None:
            raise TokenVerificationError("Signing key not found for token")
        return key

    def _cached_key(self, kid: str) -> object | None:
        """Return the cached key for ``kid`` iff the cache is still within its TTL."""
        if self._fetched_at is None:
            return None
        if (time.monotonic() - self._fetched_at) > self._ttl:
            return None  # stale — force a refresh
        return self._keys.get(kid)

    async def _refresh_jwks(self) -> None:
        async with self._lock:
            # Another coroutine may have refreshed while we waited on the lock; also throttle
            # to bound fetch-per-unknown-kid flooding.
            if (
                self._fetched_at is not None
                and (time.monotonic() - self._fetched_at) < _MIN_REFRESH_INTERVAL_S
            ):
                return
            try:
                resp = await self._client.get(self._jwks_url)
                resp.raise_for_status()
                jwks = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("JWKS fetch failed (%s): %s", self._jwks_url, exc)
                raise TokenVerificationError("Unable to verify token signing key") from exc

            keys: dict[str, object] = {}
            for entry in jwks.get("keys", []):
                kid = entry.get("kid")
                if kid:
                    try:
                        keys[kid] = jwt.PyJWK.from_dict(entry).key
                    except (jwt.InvalidKeyError, jwt.PyJWKError) as exc:
                        logger.warning("Skipping malformed JWK (kid=%s): %s", kid, exc)
            self._keys = keys
            self._fetched_at = time.monotonic()
            logger.debug("Refreshed Cognito JWKS: %d key(s)", len(keys))

    # --- claim checks / normalisation ----------------------------------------------------

    def _check_token_use(self, claims: Mapping[str, object]) -> None:
        if claims.get("token_use") != self._token_use:
            raise TokenVerificationError("Unexpected token type")

    def _check_client_binding(self, claims: Mapping[str, object]) -> None:
        # id tokens are bound via ``aud`` (already verified in decode). Access tokens must be
        # bound to our app client via ``client_id``.
        if self._token_use == "access" and self._app_client_id:
            if claims.get("client_id") != self._app_client_id:
                raise TokenVerificationError("Token not issued for this application")

    def _normalise(self, claims: dict[str, object]) -> dict[str, object]:
        """Map Cognito claim names onto the canonical PermissionScope keys."""
        normalised = dict(claims)

        tenant = claims.get(self._tenant_claim)
        if tenant is not None:
            normalised["tenant_id"] = tenant  # absent ⇒ from_claims raises → 403 (as intended)

        raw_groups = claims.get(self._groups_claim, [])
        if isinstance(raw_groups, str):
            # A ``scope`` string is space-delimited; groups are already a list.
            groups: list[str] = raw_groups.split()
        elif isinstance(raw_groups, (list, tuple)):
            groups = [str(g) for g in raw_groups]
        else:
            groups = []
        normalised["permissions"] = groups
        return normalised

    async def close(self) -> None:
        await self._client.aclose()
