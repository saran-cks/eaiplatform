"""GuardVerdict — the result of screening untrusted input through the prompt guard.

Produced by a ``GuardPort`` adapter from the prompt-guard sidecar's classify-only
response. The *product* decision (refuse / allow) is the use-case's call based on
``blocked``; this object only carries the classification. Immutable (frozen).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    label: str  # "benign" | "malicious" | "error"
    score: float  # P(malicious) in [0, 1]
    blocked: bool  # screening says do not proceed

    @classmethod
    def allow(cls) -> GuardVerdict:
        """A benign verdict — used by the null guard and as a safe default."""
        return cls(label="benign", score=0.0, blocked=False)

    @classmethod
    def refuse(cls, *, label: str = "error", score: float = 1.0) -> GuardVerdict:
        """A blocking verdict — used to fail closed when screening cannot complete."""
        return cls(label=label, score=score, blocked=True)
