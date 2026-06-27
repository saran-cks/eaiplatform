"""Pydantic schemas for the retrieval search endpoint."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RetrievedChunkResponse(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    chunks: list[RetrievedChunkResponse]
    fusion: str
    reranked: bool
