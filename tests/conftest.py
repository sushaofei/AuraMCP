from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auramcp.composition.app import create_app
from auramcp.contracts.mcp import (
    MCP_AURACLAW_DEPT_ID_META_KEY,
    MCP_AURACLAW_TENANT_ID_META_KEY,
    MCP_AURACLAW_USER_ID_META_KEY,
    MCP_CLIENT_CAPABILITIES_META_KEY,
    MCP_CLIENT_INFO_META_KEY,
    MCP_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION_META_KEY,
)
from auramcp.infrastructure.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        deployment_profile="development",
        platform_store="memory",
        allow_insecure_identity=True,
        hands_workload_token="test-workload",
        admin_token="",
        db_host="",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def modern_meta(
    *,
    tenant: str = "tenant-a",
    user: str = "user-a",
    dept: str | None = "9",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        MCP_PROTOCOL_VERSION_META_KEY: MCP_PROTOCOL_VERSION,
        MCP_CLIENT_INFO_META_KEY: {"name": "auraclaw-action-hands", "version": "1"},
        MCP_CLIENT_CAPABILITIES_META_KEY: {},
        MCP_AURACLAW_TENANT_ID_META_KEY: tenant,
        MCP_AURACLAW_USER_ID_META_KEY: user,
    }
    if dept is not None:
        meta[MCP_AURACLAW_DEPT_ID_META_KEY] = dept
    return meta


def rpc(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    tenant: str = "tenant-a",
    user: str = "user-a",
) -> dict[str, Any]:
    payload = dict(params or {})
    payload.setdefault("_meta", modern_meta(tenant=tenant, user=user))
    return {"jsonrpc": "2.0", "id": "1", "method": method, "params": payload}


def mcp_headers(
    method: str,
    *,
    name: str | None = None,
    token: str = "test-workload",
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
        "X-CT-Tenant-ID": "tenant-a",
        "X-CT-User-ID": "user-a",
        "X-CT-Dept-ID": "9",
        "X-CT-Session-ID": "ses-1",
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers
