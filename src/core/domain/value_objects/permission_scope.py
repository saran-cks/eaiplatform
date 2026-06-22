"""PermissionScope — the security boundary value object.

Extracted from the JWT by ``api/middleware/auth.py`` and passed top-down through
use-cases into adapters (e.g. the Qdrant payload filter). It is NEVER constructed or
derived inside an adapter. Immutable by construction (frozen).
"""

from __future__ import annotations

from dataclasses import dataclass, field


class PermissionDenied(PermissionError):
    """Raised when a required permission is absent from a scope."""


@dataclass(frozen=True, slots=True)
class PermissionScope:
    tenant_id: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    subject_id: str | None = None

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def has_any(self, *permissions: str) -> bool:
        return any(p in self.permissions for p in permissions)

    def has_all(self, *permissions: str) -> bool:
        return all(p in self.permissions for p in permissions)

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise PermissionDenied(
                f"tenant={self.tenant_id} subject={self.subject_id} lacks '{permission}'"
            )

    @classmethod
    def from_claims(cls, claims: dict[str, object]) -> PermissionScope:
        """Build a scope from decoded JWT claims (tenant_id, permissions, sub)."""
        tenant = claims.get("tenant_id")
        if not isinstance(tenant, str) or not tenant:
            raise PermissionDenied("JWT missing required 'tenant_id' claim")
        raw = claims.get("permissions", [])
        perms = frozenset(str(p) for p in raw) if isinstance(raw, (list, tuple, set)) else frozenset()
        sub = claims.get("sub")
        return cls(
            tenant_id=tenant,
            permissions=perms,
            subject_id=str(sub) if sub is not None else None,
        )
