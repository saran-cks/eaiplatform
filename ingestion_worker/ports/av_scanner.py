"""AvScannerPort — anti-virus scan (clamd, always-on, freshclam-refreshed)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    signature: str | None = None  # set when an infection is found


@runtime_checkable
class AvScannerPort(Protocol):
    async def scan(self, data: bytes) -> ScanResult:
        """Scan raw bytes before the file is opened/parsed."""
        ...
