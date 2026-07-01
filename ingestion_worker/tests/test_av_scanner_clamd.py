"""ClamdScanner adapter tests — fully offline, two tiers.

Tier 1 (always runs): the `clamd` client is mocked via an injected factory, so we test the
adapter's own glue — reply interpretation and the fail-closed contract — with no `clamd`
library and no daemon.

Tier 2 (runs only if the `clamd` lib is importable): the adapter drives the *real* `clamd`
client against an in-process asyncio TCP server that speaks just enough of the INSTREAM wire
protocol to answer OK / FOUND. This exercises the actual socket + framing path — the only
thing left for live verification (ST-2) is a real clamav daemon with real signatures.
"""

from __future__ import annotations

import asyncio
import struct
from importlib.util import find_spec

import pytest

from ingestion_worker.adapters.av_scanner.clamd import ClamdScanner
from ingestion_worker.domain.document import RawItem
from ingestion_worker.domain.enums import SourceType
from ingestion_worker.pipeline.security_gate import SecurityGate
from ingestion_worker.ports.av_scanner import AvScannerUnavailable, ScanResult

_HAS_CLAMD = find_spec("clamd") is not None

# The literal EICAR anti-virus test string — a harmless payload every scanner flags.
EICAR = (
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


# --------------------------------------------------------------------------- #
# Tier 1 — mocked clamd client (no lib, no socket)                            #
# --------------------------------------------------------------------------- #
class _FakeClient:
    def __init__(self, reply: object) -> None:
        self._reply = reply

    def instream(self, buff: object) -> object:
        return self._reply


def _factory(reply: object):
    return lambda host, port, timeout: _FakeClient(reply)


async def test_clean_reply_maps_to_clean() -> None:
    scanner = ClamdScanner(host="h", port=1, client_factory=_factory({"stream": ("OK", None)}))
    assert await scanner.scan(b"harmless") == ScanResult(clean=True)


async def test_found_reply_maps_to_infected_with_signature() -> None:
    scanner = ClamdScanner(
        host="h", port=1, client_factory=_factory({"stream": ("FOUND", "Eicar-Test-Signature")})
    )
    result = await scanner.scan(b"whatever")
    assert result.clean is False
    assert result.signature == "Eicar-Test-Signature"


async def test_connection_error_fails_closed() -> None:
    def boom(host: str, port: int, timeout: float) -> object:
        raise ConnectionError("connection refused")

    scanner = ClamdScanner(host="h", port=1, client_factory=boom)
    with pytest.raises(AvScannerUnavailable):
        await scanner.scan(b"whatever")


async def test_error_status_fails_closed() -> None:
    scanner = ClamdScanner(
        host="h", port=1, client_factory=_factory({"stream": ("ERROR", "size limit exceeded")})
    )
    with pytest.raises(AvScannerUnavailable):
        await scanner.scan(b"whatever")


async def test_garbled_reply_fails_closed() -> None:
    scanner = ClamdScanner(host="h", port=1, client_factory=_factory({"nonsense": True}))
    with pytest.raises(AvScannerUnavailable):
        await scanner.scan(b"whatever")


async def test_gate_quarantines_on_scanner_outage() -> None:
    # The fail-closed exception must surface as a quarantine, not a crash, at the gate.
    def boom(host: str, port: int, timeout: float) -> object:
        raise ConnectionError("daemon down")

    gate = SecurityGate(ClamdScanner(host="h", port=1, client_factory=boom))
    item = RawItem(
        source="s", native_id="n", tenant_id="t1", source_type=SourceType.TEXT,
        permissions=frozenset(), content_type="text/plain", raw=b"plain text",
    )
    result = await gate.screen(item)
    assert result.ok is False
    assert result.reason == "scan_error"


# --------------------------------------------------------------------------- #
# Tier 2 — real `clamd` client over an in-process fake clamd TCP server        #
# --------------------------------------------------------------------------- #
async def _fake_clamd_server(marker: bytes = b"EICAR") -> asyncio.Server:
    """Minimal clamd INSTREAM responder: reads the framed stream, answers OK/FOUND."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readline()  # command line: b"nINSTREAM\n"
            buf = bytearray()
            while True:
                (size,) = struct.unpack("!L", await reader.readexactly(4))
                if size == 0:  # zero-length chunk terminates the stream
                    break
                buf += await reader.readexactly(size)
            if marker in buf:
                writer.write(b"stream: Eicar-Test-Signature FOUND\n")
            else:
                writer.write(b"stream: OK\n")
            await writer.drain()
        finally:
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


@pytest.mark.skipif(not _HAS_CLAMD, reason="clamd client library not installed")
async def test_clean_stream_over_real_socket() -> None:
    server = await _fake_clamd_server()
    port = server.sockets[0].getsockname()[1]
    async with server:
        scanner = ClamdScanner(host="127.0.0.1", port=port, timeout=5.0)
        result = await scanner.scan(b"perfectly harmless bytes")
    assert result == ScanResult(clean=True)


@pytest.mark.skipif(not _HAS_CLAMD, reason="clamd client library not installed")
async def test_eicar_stream_over_real_socket() -> None:
    server = await _fake_clamd_server()
    port = server.sockets[0].getsockname()[1]
    async with server:
        scanner = ClamdScanner(host="127.0.0.1", port=port, timeout=5.0)
        result = await scanner.scan(EICAR)
    assert result.clean is False
    assert result.signature == "Eicar-Test-Signature"


@pytest.mark.skipif(not _HAS_CLAMD, reason="clamd client library not installed")
async def test_daemon_down_fails_closed_over_real_socket() -> None:
    # Nothing is listening -> the real client's connect raises -> fail closed.
    scanner = ClamdScanner(host="127.0.0.1", port=1, timeout=1.0)
    with pytest.raises(AvScannerUnavailable):
        await scanner.scan(b"anything")
