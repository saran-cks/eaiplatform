"""AcquisitionPort — incremental fetch from a source system (connector plugin).

Real adapters (ServiceNow/Zendesk/GitHub/SharePoint/S3) live behind this and own their
own cursor/delta logic. They are BLOCKING work (need live creds) and are built last.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from ingestion_worker.domain.document import RawItem


@runtime_checkable
class AcquisitionPort(Protocol):
    def fetch(self, *, cursor: str | None) -> AsyncIterator[RawItem]:
        """Yield items changed since ``cursor`` (incremental). Returns an async iterator."""
        ...
