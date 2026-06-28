"""Observability + feedback API schemas (Pydantic v2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """Human feedback on a turn, attached to its span as an annotation (annotator=HUMAN)."""

    span_id: str = Field(..., description="The trace span id the feedback applies to.")
    name: str = Field("User Feedback", max_length=64, description="Annotation name.")
    label: str | None = Field(
        None, max_length=64, description="Categorical verdict, e.g. 'thumbs_up'/'thumbs_down'."
    )
    score: float | None = Field(None, ge=0.0, le=1.0, description="Optional 0..1 score.")
    explanation: str | None = Field(None, max_length=2000)


class FeedbackAck(BaseModel):
    status: str = "recorded"
    span_id: str


class ListOut(BaseModel):
    """Generic list envelope for traces/evals/datasets (backend-shaped dicts)."""

    items: list[dict[str, Any]]
    count: int


class DriftOut(BaseModel):
    """Embedding-drift signal for a tenant."""

    status: str
    tenant_id: str | None = None
    samples: int | None = None
    cosine_distance: float | None = None
    euclidean_distance: float | None = None
    drift: float | None = None
