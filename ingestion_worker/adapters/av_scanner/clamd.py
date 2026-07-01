"""clamd anti-virus adapter — INSTREAM scan of raw bytes over TCP, fail-closed on outage.

Why the *synchronous* `clamd` client wrapped in `asyncio.to_thread`, not a hand-rolled
async clamd protocol: the ingestion worker is a throughput-oriented **batch** deployable,
not the latency-critical always-on Core API, so the Core API's "zero blocking calls on the
event loop" rule does not bind here. Reusing the mature, well-tested sync `clamd` client and
pushing its blocking socket work onto a worker thread is strictly less code to get wrong than
re-implementing the wire protocol asynchronously — and the worker ingests items sequentially,
so there is no event-loop concurrency to protect. See the ingestion-worker dev log.

Fail-closed posture: if the daemon is unreachable, times out, or answers with anything we
can't read as OK/FOUND, we raise `AvScannerUnavailable` rather than return a clean verdict.
The security gate turns that into a quarantine, matching the Prompt Guard fail-closed stance —
a scanner outage must never become an open door.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from io import BytesIO
from typing import Any, Protocol

from ingestion_worker.ports.av_scanner import AvScannerUnavailable, ScanResult


class _ClamdClient(Protocol):
    """The slice of the `clamd` client surface this adapter uses."""

    def instream(self, buff: BytesIO) -> dict[str, Any]: ...


def _default_factory(host: str, port: int, timeout: float) -> _ClamdClient:
    # Imported lazily so this module — and its mock-based unit tests — load without the
    # optional `clamd` dependency being installed. The lib ships no type stubs.
    import clamd  # type: ignore[import-untyped]

    client: _ClamdClient = clamd.ClamdNetworkSocket(host=host, port=port, timeout=timeout)
    return client


class ClamdScanner:
    """AvScannerPort backed by a clamav daemon via the sync `clamd` INSTREAM command.

    A fresh client is built per scan: `ClamdNetworkSocket` opens the socket lazily on the
    call, so there is no long-lived connection to reap between (sequential) batch items.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        timeout: float = 30.0,
        client_factory: Callable[[str, int, float], _ClamdClient] = _default_factory,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._factory = client_factory

    async def scan(self, data: bytes) -> ScanResult:
        # The `clamd` client is blocking; keep it off the event loop.
        return await asyncio.to_thread(self._scan_sync, data)

    def _scan_sync(self, data: bytes) -> ScanResult:
        try:
            client = self._factory(self._host, self._port, self._timeout)
            reply = client.instream(BytesIO(data))
        except Exception as exc:  # ConnectionError, socket timeout, BufferTooLongError, ...
            raise AvScannerUnavailable(
                f"clamd scan failed against {self._host}:{self._port}: {exc}"
            ) from exc
        return self._interpret(reply)

    @staticmethod
    def _interpret(reply: dict[str, Any]) -> ScanResult:
        # clamd answers INSTREAM as {'stream': ('OK', None)} or {'stream': ('FOUND', sig)}.
        verdict = reply.get("stream") if isinstance(reply, dict) else None
        if not verdict:
            raise AvScannerUnavailable(f"unexpected clamd reply: {reply!r}")
        status, signature = verdict
        if status == "OK":
            return ScanResult(clean=True)
        if status == "FOUND":
            return ScanResult(clean=False, signature=signature)
        # ERROR / anything else -> no usable verdict -> fail closed.
        raise AvScannerUnavailable(f"clamd returned {status}: {reply!r}")
