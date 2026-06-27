"""HttpGuardAdapter — GuardPort backed by the Prompt Guard HTTP sidecar.

Frozen contract (see sidecars/prompt_guard/app.py)::

    POST {guard_gateway_url}/guard   {"text": "..."}  -> {"label", "score", "blocked"}

This adapter only speaks the transport and maps the JSON to a ``GuardVerdict``. It does
NOT decide product behaviour and it does NOT swallow transport errors — a failed call
raises, and the use-case applies the platform's fail-closed policy (refuse).
"""

from __future__ import annotations

import logging

import httpx

from config.settings import Settings
from core.domain.value_objects.guard_verdict import GuardVerdict

logger = logging.getLogger(__name__)

# The 86M guard is fast; keep timeouts tight so a wedged sidecar fails closed quickly
# rather than stalling the request.
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


class HttpGuardAdapter:
    """GuardPort implementation calling the Prompt Guard sidecar over HTTP."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.guard_gateway_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=_TIMEOUT)
        logger.info("HttpGuardAdapter initialised (gateway=%s)", self._base_url)

    async def screen(self, text: str) -> GuardVerdict:
        """POST text to the sidecar and map the response to a GuardVerdict.

        Raises on any transport/HTTP error so the caller can fail closed.
        """
        resp = await self._client.post("/guard", json={"text": text})
        resp.raise_for_status()
        data = resp.json()
        return GuardVerdict(
            label=data["label"],
            score=float(data["score"]),
            blocked=bool(data["blocked"]),
        )

    async def close(self) -> None:
        await self._client.aclose()
