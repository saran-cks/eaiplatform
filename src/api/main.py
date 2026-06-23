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
from api.routes.health import router as health_router
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

    init_otel(app, settings)
    start_daemons(settings)

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
    # Auth runs after telemetry, before route handlers.
    app.add_middleware(
        AuthMiddleware,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        audience=settings.jwt_audience,
    )

    # --- Routes ---
    app.include_router(health_router)
    app.include_router(search_router)

    return app


# Module-level app instance for ``uvicorn api.main:app`` (non-factory mode).
app = create_app()
