"""Health and readiness routes.

- ``/health``  — liveness: always 200 if the process is alive.
- ``/ready``   — readiness: probes Postgres, Valkey, and Qdrant connectivity.
                 Returns 200 if all pass, 503 if any fail.

These endpoints are unauthenticated (excluded from JWT middleware) so that
load balancers and Kubernetes probes can reach them without a token.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

from api.schemas.health import HealthResponse, ReadinessResponse, ServiceCheck

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
)
async def health() -> HealthResponse:
    """Process is alive — always returns 200."""
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"description": "One or more downstream services unavailable"}},
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    """Probe connectivity to Postgres, Valkey, and Qdrant.

    Uses lightweight connection checks via settings-based URLs.
    Once storage adapters are wired (Session 3+), these will use the actual
    adapter pools for deeper health verification.
    """
    settings = request.app.state.settings
    checks: list[ServiceCheck] = []

    # --- Postgres probe ---
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn=settings.postgres_dsn, timeout=1)
        await conn.execute("SELECT 1")
        await conn.close()
        checks.append(ServiceCheck(name="postgres", ok=True, detail="connected"))
    except Exception as exc:
        logger.warning("Readiness: postgres unreachable: %s", exc)
        checks.append(ServiceCheck(name="postgres", ok=False, detail=str(exc)))

    # --- Valkey probe ---
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.valkey_url, socket_connect_timeout=1)
        await r.ping()
        await r.aclose()
        checks.append(ServiceCheck(name="valkey", ok=True, detail="connected"))
    except Exception as exc:
        logger.warning("Readiness: valkey unreachable: %s", exc)
        checks.append(ServiceCheck(name="valkey", ok=False, detail=str(exc)))

    # --- Qdrant probe ---
    try:
        import httpx

        async with httpx.AsyncClient(timeout=1) as client:
            resp = await client.get(f"{settings.qdrant_url}/readyz")
            if resp.status_code == 200:
                checks.append(ServiceCheck(name="qdrant", ok=True, detail="connected"))
            else:
                checks.append(
                    ServiceCheck(name="qdrant", ok=False, detail=f"status {resp.status_code}")
                )
    except Exception as exc:
        logger.warning("Readiness: qdrant unreachable: %s", exc)
        checks.append(ServiceCheck(name="qdrant", ok=False, detail=str(exc)))

    all_ok = all(c.ok for c in checks)
    if not all_ok:
        response.status_code = 503

    return ReadinessResponse(ready=all_ok, checks=checks)
