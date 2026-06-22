"""LLMPort — text generation (AWS Bedrock in phase 1; vLLM is a FUTURE adapter)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from core.domain.entities.message import Message


@runtime_checkable
class LLMPort(Protocol):
    async def generate(
        self,
        *,
        messages: Sequence[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        """Single-shot completion; returns the full assistant text."""
        ...

    def stream(
        self,
        *,
        messages: Sequence[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Token/delta stream for SSE. Returns an async iterator of text deltas."""
        ...
