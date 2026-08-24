from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auramcp.contracts.errors import IdentityConflictError
from auramcp.contracts.identity import TrustedContext

CANONICAL_PREFIX = "auramcp."
RESOURCE_SCHEME = "auramcp"


def assert_canonical_name(name: str) -> None:
    if not name.startswith(CANONICAL_PREFIX):
        raise ValueError(f"capability name must start with {CANONICAL_PREFIX}")


def assert_resource_uri(uri: str) -> None:
    if not uri.startswith(f"{RESOURCE_SCHEME}://"):
        raise ValueError(f"resource URI must use {RESOURCE_SCHEME}://")


def arguments_identity_conflicts(
    arguments: Mapping[str, Any],
    trusted: TrustedContext,
) -> None:
    declared_tenant = arguments.get("tenant_id")
    declared_user = arguments.get("user_id")
    declared_dept = arguments.get("dept_id")
    if declared_tenant is not None and str(declared_tenant) != trusted.tenant_id:
        raise IdentityConflictError("tool argument tenant_id is not an authorization source")
    if (
        declared_user is not None
        and trusted.user_id is not None
        and str(declared_user) != trusted.user_id
    ):
        raise IdentityConflictError("tool argument user_id is not an authorization source")
    if (
        declared_dept is not None
        and trusted.dept_id is not None
        and str(declared_dept) != trusted.dept_id
    ):
        raise IdentityConflictError("tool argument dept_id is not an authorization source")


def visible_to_tenant(tenant_ids: tuple[str, ...], tenant_id: str) -> bool:
    return not tenant_ids or tenant_id in tenant_ids
