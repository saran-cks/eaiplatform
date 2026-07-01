"""Observability read-side + feedback routes.

Backed by ``GetObservabilityDataUseCase`` over the neutral ``ObservabilityPort``, so these
endpoints work against Phoenix today and any future backend without route changes.

  GET  /observability/traces    — recent traces (optionally filtered to a session)
  GET  /observability/evals     — recent eval annotations
  GET  /observability/datasets  — curated datasets
  GET  /observability/drift     — embedding-drift signal for the caller's tenant
  POST /feedback                — attach human feedback to a turn's span (annotator=HUMAN)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas.observability import DriftOut, FeedbackAck, FeedbackRequest, ListOut
from core.use_cases.observability.get_phoenix_data import GetObservabilityDataUseCase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["observability"])


def _get_scope(request: Request):  # type: ignore[return]
    scope = getattr(request.state, "scope", None)
    if scope is None:
        raise HTTPException(status_code=401, detail="Permission scope missing from request context")
    return scope


def _use_case(request: Request) -> GetObservabilityDataUseCase:
    container = request.app.state.container
    return GetObservabilityDataUseCase(observability=container.observability)


@router.get("/observability/traces", response_model=ListOut, summary="Recent traces")
async def get_traces(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    session_id: str | None = Query(None),
) -> ListOut:
    scope = _get_scope(request)
    items = await _use_case(request).traces(
        tenant_id=scope.tenant_id, limit=limit, session_id=session_id
    )
    return ListOut(items=list(items), count=len(items))


@router.get("/observability/evals", response_model=ListOut, summary="Recent evals")
async def get_evals(request: Request, limit: int = Query(50, ge=1, le=500)) -> ListOut:
    scope = _get_scope(request)
    items = await _use_case(request).evals(tenant_id=scope.tenant_id, limit=limit)
    return ListOut(items=list(items), count=len(items))


@router.get("/observability/datasets", response_model=ListOut, summary="Curated datasets")
async def get_datasets(request: Request) -> ListOut:
    scope = _get_scope(request)
    items = await _use_case(request).datasets(tenant_id=scope.tenant_id)
    return ListOut(items=list(items), count=len(items))


@router.get("/observability/drift", response_model=DriftOut, summary="Embedding drift")
async def get_drift(request: Request) -> DriftOut:
    scope = _get_scope(request)
    result = await _use_case(request).drift(tenant_id=scope.tenant_id)
    return DriftOut(**result)


@router.post("/feedback", response_model=FeedbackAck, summary="Submit human feedback")
async def post_feedback(body: FeedbackRequest, request: Request) -> FeedbackAck:
    _get_scope(request)
    container = request.app.state.container
    await container.observability.record_eval(
        span_id=body.span_id,
        name=body.name,
        label=body.label,
        score=body.score,
        explanation=body.explanation,
        annotator_kind="HUMAN",
    )
    return FeedbackAck(span_id=body.span_id)
