"""NullGuardAdapter — GuardPort that allows everything.

Bound by the DI container when ``GUARD_ENABLED`` is false, so the use-cases can call
``screen()`` unconditionally without knowing whether the guard is configured. Disabling
the guard is an explicit, logged operational choice — never a silent default.
"""

from __future__ import annotations

import logging

from core.domain.value_objects.guard_verdict import GuardVerdict

logger = logging.getLogger(__name__)


class NullGuardAdapter:
    """GuardPort implementation that classifies all input as benign."""

    def __init__(self) -> None:
        logger.warning(
            "NullGuardAdapter active — GUARD_ENABLED is false; input is NOT screened."
        )

    async def screen(self, text: str) -> GuardVerdict:
        del text  # unused: this guard allows everything
        return GuardVerdict.allow()

    async def close(self) -> None:
        return None
