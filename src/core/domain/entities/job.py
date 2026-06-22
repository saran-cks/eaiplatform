"""IngestionJob entity & JobStatus.

The ingestion worker is a separate service; here we model the job handle we enqueue and
poll via the QueuePort (ARQ on Valkey). We trigger and track — we do not run ingestion.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"


class IngestionJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    status: JobStatus = JobStatus.QUEUED
    source_uri: str | None = None
    params: dict[str, object] = Field(default_factory=dict)
    error: str | None = None
    enqueued_at: datetime | None = None
    finished_at: datetime | None = None
