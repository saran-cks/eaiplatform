"""Result/report value objects for a pipeline run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ItemResult:
    document_id: str | None = None
    quarantined: bool = False
    reason: str | None = None     # quarantine reason when quarantined
    upserted: int = 0
    unchanged: int = 0
    deleted: int = 0


@dataclass(slots=True)
class IngestReport:
    items: int = 0
    quarantined: int = 0
    upserted: int = 0
    unchanged: int = 0
    deleted: int = 0

    def add(self, result: ItemResult) -> None:
        self.items += 1
        if result.quarantined:
            self.quarantined += 1
        self.upserted += result.upserted
        self.unchanged += result.unchanged
        self.deleted += result.deleted
