from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import mcp_headers, rpc

from auramcp.extensions.about.package import AURACLAW_INTRO_TEXT, AURACLAW_TAGLINE


def test_discover_lists_supported_version(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=rpc("server/discover"),
        headers=mcp_headers("server/discover"),
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert "2026-07-28" in result["supportedVersions"]
    assert result["capabilities"]["tools"] == {}
    assert result["serverInfo"]["name"] == "auramcp"


def test_tools_list_contains_builtin_and_ops(client: TestClient) -> None:
    response = client.post("/mcp", json=rpc("tools/list"), headers=mcp_headers("tools/list"))
    names = [item["name"] for item in response.json()["result"]["tools"]]
    assert "auramcp.health.ping" in names
    assert "auramcp.example.echo" in names
    assert "auramcp.about.auraclaw" in names
    assert "auramcp.ops.catalog_snapshot" in names
    assert all(name.startswith("auramcp.") for name in names)


def test_about_auraclaw_tool(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=rpc("tools/call", {"name": "auramcp.about.auraclaw", "arguments": {}}),
        headers=mcp_headers("tools/call", name="auramcp.about.auraclaw"),
    )
    body = response.json()["result"]
    assert body["isError"] is False
    structured = body["structuredContent"]
    assert structured["name"] == "AuraClaw"
    assert structured["tagline"] == AURACLAW_TAGLINE
    assert structured["description"] == AURACLAW_INTRO_TEXT
    assert AURACLAW_INTRO_TEXT in body["content"][0]["text"]


def test_echo_and_ping_tools(client: TestClient) -> None:
    ping = client.post(
        "/mcp",
        json=rpc("tools/call", {"name": "auramcp.health.ping", "arguments": {}}),
        headers=mcp_headers("tools/call", name="auramcp.health.ping"),
    )
    assert ping.json()["result"]["isError"] is False
    assert ping.json()["result"]["structuredContent"]["ok"] is True

    echo = client.post(
        "/mcp",
        json=rpc("tools/call", {"name": "auramcp.example.echo", "arguments": {"message": "hi"}}),
        headers=mcp_headers("tools/call", name="auramcp.example.echo"),
    )
    body = echo.json()["result"]
    assert body["isError"] is False
    assert body["structuredContent"]["echo"] == "hi"


def test_tool_business_error_uses_is_error(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=rpc("tools/call", {"name": "auramcp.example.echo", "arguments": {}}),
        headers=mcp_headers("tools/call", name="auramcp.example.echo"),
    )
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True


def test_argument_identity_conflict_is_forbidden(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=rpc(
            "tools/call",
            {
                "name": "auramcp.example.echo",
                "arguments": {"message": "hi", "tenant_id": "other"},
            },
        ),
        headers=mcp_headers("tools/call", name="auramcp.example.echo"),
    )
    assert response.json()["error"]["message"] == (
        "tool argument tenant_id is not an authorization source"
    )


def test_resources_and_prompts(client: TestClient) -> None:
    listed = client.post("/mcp", json=rpc("resources/list"), headers=mcp_headers("resources/list"))
    uris = [item["uri"] for item in listed.json()["result"]["resources"]]
    assert "auramcp://builtin/about" in uris
    assert "auramcp://ops/handbook" in uris

    read = client.post(
        "/mcp",
        json=rpc("resources/read", {"uri": "auramcp://builtin/about"}),
        headers=mcp_headers("resources/read", name="auramcp://builtin/about"),
    )
    contents = read.json()["result"]["contents"]
    assert contents[0]["text"].startswith("AuraMCP")

    template = client.post(
        "/mcp",
        json=rpc("resources/templates/list"),
        headers=mcp_headers("resources/templates/list"),
    )
    assert template.json()["result"]["resourceTemplates"][0]["uriTemplate"].startswith("auramcp://")

    prompt = client.post(
        "/mcp",
        json=rpc(
            "prompts/get",
            {"name": "auramcp.ops.diagnose", "arguments": {"symptom": "timeout"}},
        ),
        headers=mcp_headers("prompts/get", name="auramcp.ops.diagnose"),
    )
    assert "timeout" in prompt.json()["result"]["messages"][0]["content"]["text"]


def test_invalid_workload_is_unauthorized(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=rpc("tools/list"),
        headers=mcp_headers("tools/list", token="wrong-workload"),
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_method_is_jsonrpc_error(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=rpc("tasks/list"),
        headers=mcp_headers("tasks/list"),
    )
    assert response.json()["error"]["code"] == -32601
