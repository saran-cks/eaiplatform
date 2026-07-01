"""FastAPI application factory.

``create_app()`` is the ASGI entry point used by uvicorn::

    uvicorn api.main:create_app --factory --reload

The lifespan context manager handles startup (DI container, OTel, daemons)
and shutdown (daemon cancellation, OTel flush) in a single place.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.middleware.auth import AuthMiddleware
from api.middleware.telemetry import TelemetryMiddleware
from api.routes.agent import router as agent_router
from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.observability import router as observability_router
from api.routes.search import router as search_router
from config.di import build_container
from config.settings import Settings, get_settings
from daemon.tasks import start_daemons, stop_daemons
from observability.otel import init_otel, shutdown_otel

logger = logging.getLogger(__name__)


def _configure_logging(settings: Settings) -> None:
    """Set up root logging based on settings."""
    handlers: list[logging.Handler] = []

    # Always log to stdout (CloudWatch picks this up in prod).
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handlers.append(stdout_handler)

    # Optionally also log to file for local dev.
    if settings.log_to_file:
        from pathlib import Path

        log_dir = Path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / settings.log_file)
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        handlers.append(file_handler)

    logging.basicConfig(level=settings.log_level, handlers=handlers, force=True)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle for the application."""
    settings: Settings = app.state.settings

    # --- Startup ---
    logger.info("Starting %s (%s)", settings.app_name, settings.app_env)

    init_otel(
        app,
        enabled=settings.otel_enabled,
        service_name=settings.otel_service_name,
        environment=settings.app_env,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        autoinstrument=settings.otel_autoinstrument,
    )
    # The agent_reaper needs the agent port + the shared DD-11 kill registry to force-terminate
    # sessions the trajectory monitor killed. Building the agent here also fails fast on a
    # mis-wired MCP chokepoint rather than on first request.
    container = app.state.container
    start_daemons(
        settings,
        agent=container.agent,
        kill_registry=container.agent_kill_registry,
    )

    logger.info("%s ready on %s:%d", settings.app_name, settings.api_host, settings.api_port)

    yield

    # --- Shutdown ---
    logger.info("Shutting down %s", settings.app_name)

    await stop_daemons()
    shutdown_otel()

    # Gracefully close active database pools and gRPC channels
    container = app.state.container
    if "store" in container.__dict__:
        try:
            await container.store.close()
        except Exception as exc:
            logger.warning("Error closing store adapter: %s", exc)

    if "retriever" in container.__dict__:
        try:
            await container.retriever.close()
        except Exception as exc:
            logger.warning("Error closing retriever adapter: %s", exc)

    if "guard" in container.__dict__:
        try:
            await container.guard.close()
        except Exception as exc:
            logger.warning("Error closing guard adapter: %s", exc)

    if "mcp" in container.__dict__:
        try:
            await container.mcp.close()
        except Exception as exc:
            logger.warning("Error closing mcp connector: %s", exc)

    if "observability" in container.__dict__:
        try:
            await container.observability.close()
        except Exception as exc:
            logger.warning("Error closing observability adapter: %s", exc)

    if "token_verifier" in container.__dict__:
        try:
            await container.token_verifier.close()
        except Exception as exc:
            logger.warning("Error closing token verifier: %s", exc)

    logger.info("%s stopped", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = settings or get_settings()
    _configure_logging(settings)

    container = build_container(settings)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Enterprise AI Platform — Core API",
        lifespan=_lifespan,
        debug=settings.debug,
    )

    # Attach settings and DI container to app state so routes/middleware can access them.
    app.state.settings = settings
    app.state.container = container

    # --- Middleware (order matters: outermost first) ---
    # Telemetry wraps everything (including auth), so it captures full request duration.
    app.add_middleware(TelemetryMiddleware)
    # Auth runs after telemetry, before route handlers. The verifier (HS256 dev / Cognito
    # RS256 prod) is selected in the container by AUTH_PROVIDER — the middleware is agnostic.
    app.add_middleware(AuthMiddleware, verifier=container.token_verifier)

    # --- Routes ---
    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(chat_router)
    app.include_router(agent_router)
    app.include_router(observability_router)

    return app


# Module-level app instance for ``uvicorn api.main:app`` (non-factory mode).
app = create_app()
