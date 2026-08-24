from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Any

from auramcp.contracts.errors import IdentityConflictError, IdentityDeniedError
from auramcp.contracts.identity import TrustedContext
from auramcp.contracts.mcp import (
    MCP_AURACLAW_DEPT_ID_META_KEY,
    MCP_AURACLAW_INVOCATION_ID_META_KEY,
    MCP_AURACLAW_TENANT_ID_META_KEY,
    MCP_AURACLAW_USER_ID_META_KEY,
    MCP_CLIENT_CAPABILITIES_META_KEY,
    MCP_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION_META_KEY,
)


class IdentityGuard:
    def __init__(
        self,
        *,
        workload_token: str,
        deployment_profile: str,
        allow_insecure: bool,
    ) -> None:
        if deployment_profile == "production" and allow_insecure:
            raise ValueError("insecure identity is forbidden in production")
        if deployment_profile == "production" and not workload_token:
            raise ValueError("production requires AURAMCP_HANDS_WORKLOAD_TOKEN")
        self._workload_token = workload_token
        self._allow_insecure = allow_insecure and deployment_profile != "production"

    def authenticate(
        self,
        *,
        authorization: str | None,
        headers: Mapping[str, str],
        params: Mapping[str, Any],
        method: str,
        require_modern_meta: bool,
    ) -> TrustedContext:
        self._verify_workload(authorization)
        meta = params.get("_meta")
        meta_dict = meta if isinstance(meta, dict) else {}
        if require_modern_meta:
            self._verify_modern_meta(meta_dict)
        tenant_id = _aligned_value(
            headers.get("x-ct-tenant-id"),
            meta_dict.get(MCP_AURACLAW_TENANT_ID_META_KEY),
            "tenant",
        )
        user_id = _aligned_optional(
            headers.get("x-ct-user-id"),
            meta_dict.get(MCP_AURACLAW_USER_ID_META_KEY),
            "user",
        )
        dept_id = _aligned_optional(
            headers.get("x-ct-dept-id"),
            meta_dict.get(MCP_AURACLAW_DEPT_ID_META_KEY),
            "dept",
        )
        session_id = headers.get("x-ct-session-id") or None
        if not tenant_id:
            if self._allow_insecure:
                tenant_id = "local"
            else:
                raise IdentityDeniedError("trusted tenant context is missing")
        if method in {"tools/call", "resources/read", "prompts/get"} and not user_id:
            if self._allow_insecure:
                user_id = "local-user"
            else:
                raise IdentityDeniedError("trusted user context is missing")
        invocation = meta_dict.get(MCP_AURACLAW_INVOCATION_ID_META_KEY)
        return TrustedContext(
            tenant_id=tenant_id,
            user_id=user_id,
            dept_id=dept_id,
            session_id=session_id,
            invocation_id=None if invocation is None else str(invocation),
        )

    def _verify_workload(self, authorization: str | None) -> None:
        token = _bearer_token(authorization)
        if token is None:
            if self._allow_insecure:
                return
            raise IdentityDeniedError("workload credential is missing")
        if not self._workload_token or not hmac.compare_digest(token, self._workload_token):
            raise IdentityDeniedError("workload credential is invalid")

    def _verify_modern_meta(self, meta: Mapping[str, Any]) -> None:
        if meta.get(MCP_PROTOCOL_VERSION_META_KEY) != MCP_PROTOCOL_VERSION:
            raise IdentityDeniedError("modern MCP request metadata is missing or invalid")
        if not isinstance(meta.get(MCP_CLIENT_CAPABILITIES_META_KEY), dict):
            raise IdentityDeniedError("modern MCP request metadata is missing or invalid")


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, remainder = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not remainder:
        raise IdentityDeniedError("workload credential is invalid")
    return remainder.strip()


def _aligned_value(header: str | None, meta: Any, label: str) -> str | None:
    header_value = header.strip() if header else None
    meta_value = str(meta) if meta is not None and str(meta) else None
    if header_value and meta_value and header_value != meta_value:
        raise IdentityConflictError(f"{label} header and _meta conflict")
    return header_value or meta_value


def _aligned_optional(header: str | None, meta: Any, label: str) -> str | None:
    return _aligned_value(header, meta, label)
