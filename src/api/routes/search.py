"""Retrieval search route handler."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas.search import RetrievedChunkResponse, SearchResponse
from core.use_cases.retrieval.search_chunks import SearchChunksUseCase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Query hybrid search chunks",
)
async def search(
    request: Request,
    query: str = Query(..., min_length=1, description="Query text to search"),
    limit: int = Query(5, ge=1, le=50, description="Max retrieval count"),
) -> SearchResponse:
    """Enforces scope-filtered hybrid retrieval on Qdrant using JWT token scopes."""
    scope = getattr(request.state, "scope", None)
    if scope is None:
        logger.error("Authentication state scope not found on request.")
        raise HTTPException(
            status_code=401,
            detail="Permission scope not found in request context",
        )

    # Initialize the search use case with the retriever adapter from DI container
    use_case = SearchChunksUseCase(request.app.state.container.retriever)
    
    try:
        result = await use_case.execute(
            query_text=query,
            scope=scope,
            limit=limit,
        )
    except Exception as e:
        logger.exception("Failed to execute search use case: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Retrieval query failed internally",
        ) from e

    # Map core domain result structures to API response schemas
    chunks_response = [
        RetrievedChunkResponse(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            text=c.text,
            score=c.score,
            metadata=c.metadata,
        )
        for c in result.chunks
    ]

    return SearchResponse(
        chunks=chunks_response,
        fusion=result.fusion,
        reranked=result.reranked,
    )
