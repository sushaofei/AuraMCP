from __future__ import annotations

import pytest
from tests.conftest import modern_meta

from auramcp.contracts.errors import IdentityConflictError, IdentityDeniedError
from auramcp.identity.guard import IdentityGuard


def test_production_rejects_insecure_flag() -> None:
    with pytest.raises(ValueError, match="insecure identity is forbidden"):
        IdentityGuard(
            workload_token="token",
            deployment_profile="production",
            allow_insecure=True,
        )


def test_missing_workload_is_denied() -> None:
    guard = IdentityGuard(
        workload_token="token",
        deployment_profile="production",
        allow_insecure=False,
    )
    with pytest.raises(IdentityDeniedError):
        guard.authenticate(
            authorization=None,
            headers={"x-ct-tenant-id": "t1", "x-ct-user-id": "u1"},
            params={"_meta": modern_meta(tenant="t1", user="u1")},
            method="tools/call",
            require_modern_meta=True,
        )


def test_header_meta_conflict_is_denied() -> None:
    guard = IdentityGuard(
        workload_token="token",
        deployment_profile="production",
        allow_insecure=False,
    )
    with pytest.raises(IdentityConflictError, match="tenant"):
        guard.authenticate(
            authorization="Bearer token",
            headers={"x-ct-tenant-id": "t1", "x-ct-user-id": "u1"},
            params={"_meta": modern_meta(tenant="other", user="u1")},
            method="tools/call",
            require_modern_meta=True,
        )


def test_development_insecure_defaults_identity() -> None:
    guard = IdentityGuard(
        workload_token="",
        deployment_profile="development",
        allow_insecure=True,
    )
    trusted = guard.authenticate(
        authorization=None,
        headers={},
        params={"_meta": modern_meta(tenant="", user="")},
        method="server/discover",
        require_modern_meta=False,
    )
    assert trusted.tenant_id == "local"
