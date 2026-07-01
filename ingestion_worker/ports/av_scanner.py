"""AvScannerPort — anti-virus scan (clamd, always-on, freshclam-refreshed)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    signature: str | None = None  # set when an infection is found


class AvScannerUnavailable(Exception):
    """The scanner could not render a verdict (daemon down, transport error, bad reply).

    Distinct from a clean/infected ScanResult: it signals *absence* of a verdict, not a
    negative one. Callers must fail **closed** on it — an unreachable scanner may never be
    treated as "no virus". Lives on the port (not the adapter) so pipeline stages can catch
    it without importing an adapter.
    """


@runtime_checkable
class AvScannerPort(Protocol):
    async def scan(self, data: bytes) -> ScanResult:
        """Scan raw bytes before the file is opened/parsed.

        Raises AvScannerUnavailable when no verdict can be produced (caller fails closed).
        """
        ...
