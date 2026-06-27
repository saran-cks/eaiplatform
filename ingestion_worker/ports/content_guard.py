"""ContentGuardPort — the two ingest-time guards (Fork #2: both run at ingest).

1. Prompt-injection screening (Llama Prompt Guard 2) -> stamps injection_risk/screened
   onto every chunk. MANDATORY: this is the DD-13 signal the core-api retrieval consumes.
2. Abuse/unsafe screening (Llama Guard) -> drop/quarantine genuinely unsafe content.
3. PII/secret detection (Presidio + regex) -> redact in place.

Screening at INGEST (once) not at retrieval is deliberate: it is cheaper, and the
verdict is stored on the chunk so every later read is free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class InjectionVerdict:
    injection_risk: float           # P(injection) in [0, 1] from Prompt Guard 2


@dataclass(frozen=True, slots=True)
class AbuseVerdict:
    unsafe: bool
    categories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str                       # text with PII/secrets redacted in place
    redacted: bool = False
    entities: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class ContentGuardPort(Protocol):
    async def screen_injection(self, text: str) -> InjectionVerdict:
        """Prompt Guard 2 — injection/jailbreak probability for this text."""
        ...

    async def screen_abuse(self, text: str) -> AbuseVerdict:
        """Llama Guard — is this content unsafe/abusive (drop-worthy)?"""
        ...

    async def redact_pii(self, text: str) -> RedactionResult:
        """Presidio + regex — redact PII/secrets, returning the cleaned text."""
        ...
