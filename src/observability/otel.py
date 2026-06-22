"""OpenTelemetry initialisation — tracer and meter providers.

Called once at app startup (via the FastAPI lifespan). Configures:
- TracerProvider with OTLP gRPC exporter → Phoenix (:4317)
- MeterProvider with OTLP gRPC exporter → Phoenix
- FastAPI auto-instrumentation (span per request)

This module is the permanent OTel foundation. Domain-specific span builders,
metrics, and drift logic are added in ``observability/{spans,metrics,drift}.py``
during Session 8.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

if TYPE_CHECKING:
    from fastapi import FastAPI

    from config.settings import Settings

logger = logging.getLogger(__name__)


def init_otel(app: FastAPI, settings: Settings) -> None:
    """Bootstrap OpenTelemetry providers and instrument FastAPI.

    When ``OTEL_ENABLED`` is False the function returns immediately, leaving
    the global no-op providers in place (zero overhead).
    """
    if not settings.otel_enabled:
        logger.info("OpenTelemetry disabled (OTEL_ENABLED=false)")
        return

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "deployment.environment": settings.app_env,
        }
    )

    # --- Traces ---
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    metric_exporter = OTLPMetricExporter(
        endpoint=settings.otel_exporter_otlp_endpoint, insecure=True
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(metric_exporter, export_interval_millis=15000)],
    )
    metrics.set_meter_provider(meter_provider)

    # --- FastAPI auto-instrumentation ---
    FastAPIInstrumentor.instrument_app(app)

    logger.info(
        "OpenTelemetry initialised: traces+metrics -> %s",
        settings.otel_exporter_otlp_endpoint,
    )


def shutdown_otel() -> None:
    """Flush and shut down OTel providers. Called during app lifespan shutdown."""
    tracer_provider = trace.get_tracer_provider()
    if isinstance(tracer_provider, TracerProvider):
        tracer_provider.shutdown()

    meter_provider = metrics.get_meter_provider()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.shutdown()

    logger.info("OpenTelemetry shut down")
