"""PermissionScope tests — the security boundary VO.

`from_claims` turns decoded JWT claims into the tenant/permission boundary the whole
RAG + agent stack filters on, so its parsing (esp. the missing-tenant failure) is
security-critical and was previously only exercised indirectly via the auth middleware.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.domain.value_objects.permission_scope import PermissionDenied, PermissionScope


def test_has_variants():
    scope = PermissionScope(tenant_id="t1", permissions=frozenset({"read", "write"}))
    assert scope.has("read")
    assert not scope.has("delete")
    assert scope.has_any("delete", "write")
    assert not scope.has_any("delete", "admin")
    assert scope.has_all("read", "write")
    assert not scope.has_all("read", "admin")


def test_require_raises_on_missing_permission():
    scope = PermissionScope(tenant_id="t1", permissions=frozenset({"read"}))
    scope.require("read")  # no raise
    with pytest.raises(PermissionDenied):
        scope.require("write")


def test_from_claims_happy_path():
    scope = PermissionScope.from_claims(
        {"tenant_id": "t1", "permissions": ["read", "write"], "sub": "user-9"}
    )
    assert scope.tenant_id == "t1"
    assert scope.permissions == frozenset({"read", "write"})
    assert scope.subject_id == "user-9"


def test_from_claims_missing_tenant_is_denied():
    with pytest.raises(PermissionDenied):
        PermissionScope.from_claims({"permissions": ["read"]})


def test_from_claims_empty_tenant_is_denied():
    with pytest.raises(PermissionDenied):
        PermissionScope.from_claims({"tenant_id": "", "permissions": ["read"]})


def test_from_claims_malformed_permissions_default_to_empty():
    """A non-list permissions claim must not crash and must not grant anything."""
    scope = PermissionScope.from_claims({"tenant_id": "t1", "permissions": "read"})
    assert scope.permissions == frozenset()


def test_from_claims_without_subject():
    scope = PermissionScope.from_claims({"tenant_id": "t1"})
    assert scope.subject_id is None
    assert scope.permissions == frozenset()


def test_scope_is_frozen():
    scope = PermissionScope(tenant_id="t1")
    with pytest.raises(FrozenInstanceError):
        scope.tenant_id = "t2"  # type: ignore[misc]
