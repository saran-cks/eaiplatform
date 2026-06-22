"""Background daemon tasks — asyncio loops managed by the FastAPI lifespan.

Each daemon is a long-running coroutine that sleeps on a configurable interval.
The ``start_daemons`` / ``stop_daemons`` functions are called from the app
lifespan in ``api/main.py``.

All daemons are skeleton implementations for Session 2. Real logic is added as
the corresponding adapters come online (Sessions 3–9).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

# Handles to running tasks so we can cancel them on shutdown.
_tasks: list[asyncio.Task[None]] = []


async def _agent_reaper(interval: int) -> None:
    """Kill TTL-exceeded or orphaned agent sessions (Session 6)."""
    while True:
        await asyncio.sleep(interval)
        logger.debug("agent_reaper: sweep (no-op until Session 6)")


async def _session_cleanup(interval: int) -> None:
    """Evict expired chat sessions from Valkey / Postgres (Session 3)."""
    while True:
        await asyncio.sleep(interval)
        logger.debug("session_cleanup: sweep (no-op until Session 3)")


async def _health_watchdog(interval: int) -> None:
    """Deep readiness probes for downstream services (Postgres, Valkey, Qdrant)."""
    while True:
        await asyncio.sleep(interval)
        logger.debug("health_watchdog: probe (no-op until adapters wired)")


async def _process_manager(interval: int) -> None:
    """Manage background processing state (queue draining, etc.)."""
    while True:
        await asyncio.sleep(interval)
        logger.debug("process_manager: tick (no-op until queue adapter wired)")


def start_daemons(settings: Settings) -> None:
    """Create and schedule all daemon tasks. Called once during app startup."""
    loop = asyncio.get_running_loop()

    _tasks.extend(
        [
            loop.create_task(_agent_reaper(settings.reaper_interval), name="agent_reaper"),
            loop.create_task(_session_cleanup(settings.cleanup_interval), name="session_cleanup"),
            loop.create_task(_health_watchdog(settings.watchdog_interval), name="health_watchdog"),
            loop.create_task(_process_manager(60), name="process_manager"),
        ]
    )
    logger.info("Started %d daemon tasks", len(_tasks))


async def stop_daemons() -> None:
    """Cancel all daemon tasks and wait for them to finish. Called on shutdown."""
    for task in _tasks:
        task.cancel()

    results = await asyncio.gather(*_tasks, return_exceptions=True)
    cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
    logger.info("Stopped %d daemon tasks (%d cancelled)", len(_tasks), cancelled)
    _tasks.clear()
