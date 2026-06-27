"""Security Gate — runs BEFORE the file is ever opened/parsed.

Three checks, in cheap-to-expensive order:
  1. magic-byte type check (trust bytes, not the declared extension),
  2. size bound (cheap zip-bomb / oversize guard),
  3. clamd scan (via AvScannerPort).

Static checks (1, 2) are pure and live here; the AV scan is I/O behind a port. A failure
routes the item to quarantine/dead-letter — the file is never parsed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ingestion_worker.domain.document import RawItem
from ingestion_worker.ports.av_scanner import AvScannerPort

# Declared content-type -> required leading magic bytes. Text-like types (txt/csv/json/
# code) have no reliable magic and are skipped here.
_MAGIC: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "application/zip": b"PK\x03\x04",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK\x03\x04",
    "image/png": b"\x89PNG",
}

_DEFAULT_MAX_BYTES = 25 * 1024 * 1024  # 25 MiB


@dataclass(frozen=True, slots=True)
class GateResult:
    ok: bool
    reason: str | None = None  # "malformed" | "oversize" | "infected"
    detail: str = ""


def static_checks(item: RawItem, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> GateResult:
    """Pure magic-byte + size checks. No I/O."""
    if len(item.raw) == 0:
        return GateResult(ok=False, reason="malformed", detail="empty payload")
    if len(item.raw) > max_bytes:
        return GateResult(
            ok=False, reason="oversize", detail=f"{len(item.raw)} > {max_bytes} bytes"
        )
    expected = _MAGIC.get(item.content_type)
    if expected is not None and not item.raw.startswith(expected):
        return GateResult(
            ok=False,
            reason="malformed",
            detail=f"magic mismatch for {item.content_type}",
        )
    return GateResult(ok=True)


class SecurityGate:
    """Static checks + AV scan. Returns the first failure, or ok."""

    def __init__(self, av_scanner: AvScannerPort, *, max_bytes: int = _DEFAULT_MAX_BYTES) -> None:
        self._av = av_scanner
        self._max_bytes = max_bytes

    async def screen(self, item: RawItem) -> GateResult:
        static = static_checks(item, max_bytes=self._max_bytes)
        if not static.ok:
            return static
        scan = await self._av.scan(item.raw)
        if not scan.clean:
            return GateResult(ok=False, reason="infected", detail=scan.signature or "")
        return GateResult(ok=True)
