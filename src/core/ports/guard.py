"""GuardPort — screen untrusted input for prompt injection / jailbreak.

The first line of defence on every user-facing entry point (RAG chat and agent).
Backed by the Llama Prompt Guard 2 HTTP sidecar in phase 1; the adapter is the only
thing that knows the transport. The port is classify-only — callers decide what to do
with a blocking verdict (the platform's policy is fail-closed: refuse).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.domain.value_objects.guard_verdict import GuardVerdict


@runtime_checkable
class GuardPort(Protocol):
    async def screen(self, text: str) -> GuardVerdict:
        """Classify ``text``; return a verdict. Raises on transport failure."""
        ...

    async def close(self) -> None:
        """Release any underlying client/connection."""
        ...
