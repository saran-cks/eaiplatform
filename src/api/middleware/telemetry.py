"""Request-level telemetry middleware.

Adds lightweight OTel span attributes (method, path, status code) to each
request. The actual span is already created by the FastAPI auto-instrumentation
in ``observability/otel.py``; this middleware enriches it with custom attributes
and logs request duration.

When OTel is disabled this middleware still logs timing at DEBUG level.
"""

from __future__ import annotations

import logging
import time

from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class TelemetryMiddleware(BaseHTTPMiddleware):
    """Enrich the current OTel span with request metadata and log timing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        span = trace.get_current_span()

        # Enrich span with request info.
        if span.is_recording():
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url.path", request.url.path)
            if hasattr(request.state, "scope"):
                scope = request.state.scope
                span.set_attribute("user.tenant_id", scope.tenant_id)
                if scope.subject_id:
                    span.set_attribute("user.subject_id", scope.subject_id)

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000

        if span.is_recording():
            span.set_attribute("http.status_code", response.status_code)
            span.set_attribute("http.duration_ms", round(duration_ms, 2))

        logger.debug(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        return response
