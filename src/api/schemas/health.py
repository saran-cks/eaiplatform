"""Pydantic response schemas for health and readiness endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness check — always returns status ok if the process is alive."""

    status: str = Field("ok", examples=["ok"])


class ServiceCheck(BaseModel):
    """Connectivity result for a single downstream service."""

    name: str = Field(..., examples=["postgres"])
    ok: bool = Field(..., examples=[True])
    detail: str = Field("", examples=["connected"])


class ReadinessResponse(BaseModel):
    """Readiness check — reports connectivity for each downstream service."""

    ready: bool = Field(..., examples=[True])
    checks: list[ServiceCheck] = Field(default_factory=list)
