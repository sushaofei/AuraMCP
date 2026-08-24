from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import mcp_headers, rpc


def test_admin_catalog_and_health(client: TestClient) -> None:
    health = client.get("/internal/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    catalog = client.get("/internal/v1/catalog", headers={"X-CT-Tenant-ID": "tenant-a"})
    names = [item["name"] for item in catalog.json()["packages"]]
    assert "builtin" in names
    assert "ops" in names
    assert all(
        record["canonical_name"].startswith("auramcp.")
        or record["canonical_name"].startswith("auramcp://")
        for record in catalog.json()["capabilities"]
    )


def test_disable_hides_tools_from_list_and_call(client: TestClient) -> None:
    disable = client.post(
        "/internal/v1/extensions/ops/disable",
        json={"actor": "tester", "commandId": "cmd-1", "expectedVersion": 1},
    )
    assert disable.status_code == 200
    assert disable.json()["status"] == "disabled"

    listed = client.post("/mcp", json=rpc("tools/list"), headers=mcp_headers("tools/list"))
    names = [item["name"] for item in listed.json()["result"]["tools"]]
    assert "auramcp.ops.catalog_snapshot" not in names
    assert "auramcp.health.ping" in names

    called = client.post(
        "/mcp",
        json=rpc("tools/call", {"name": "auramcp.ops.catalog_snapshot", "arguments": {}}),
        headers=mcp_headers("tools/call", name="auramcp.ops.catalog_snapshot"),
    )
    assert called.json()["error"]["message"] == "tool not found"

    enable = client.post(
        "/internal/v1/extensions/ops/enable",
        json={"actor": "tester", "commandId": "cmd-2", "expectedVersion": 2},
    )
    assert enable.json()["status"] == "active"
    listed_again = client.post("/mcp", json=rpc("tools/list"), headers=mcp_headers("tools/list"))
    names_again = [item["name"] for item in listed_again.json()["result"]["tools"]]
    assert "auramcp.ops.catalog_snapshot" in names_again


def test_version_conflict_and_idempotent_command(client: TestClient) -> None:
    first = client.post(
        "/internal/v1/extensions/builtin/disable",
        json={"actor": "tester", "commandId": "same", "expectedVersion": 1},
    )
    assert first.status_code == 200
    replay = client.post(
        "/internal/v1/extensions/builtin/disable",
        json={"actor": "tester", "commandId": "same", "expectedVersion": 1},
    )
    assert replay.status_code == 200
    conflict = client.post(
        "/internal/v1/extensions/builtin/enable",
        json={"actor": "tester", "commandId": "other", "expectedVersion": 1},
    )
    assert conflict.status_code == 409
