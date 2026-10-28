from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from auramcp.contracts.identity import TrustedContext
from auramcp.contracts.semantic import Describe, Discover, SemanticQuery
from auramcp.domain.semantic import SemanticError
from auramcp.extensions.semantic import SemanticExtension
from auramcp.infrastructure.semantic import CubeSemanticReader, SemanticConfig

TRUSTED = TrustedContext(tenant_id="t", user_id="u", invocation_id="inv")


@pytest.fixture
def config(tmp_path: Path) -> SemanticConfig:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    path = tmp_path / "key"
    path.write_bytes(pem)
    return SemanticConfig.model_validate(
        {
            "base_url": "http://cube/cubejs-api/v1/",
            "signing_key_file": str(path),
            "datasets": [
                {
                    "name": "records",
                    "title": "业务",
                    "description": "approved",
                    "cube": "records",
                    "model_version": "v1",
                    "allowed_tenants": ["t"],
                    "allowed_users": ["u"],
                    "members": {
                        "amount": {
                            "cube_member": "records.amount",
                            "title": "金额",
                            "description": "sum",
                            "kind": "measure",
                            "type": "number",
                            "unit": "万元",
                        },
                        "area": {
                            "cube_member": "records.area",
                            "title": "地区",
                            "description": "group",
                            "kind": "dimension",
                            "type": "string",
                        },
                        "id": {
                            "cube_member": "records.id",
                            "title": "ID",
                            "description": "ID",
                            "kind": "dimension",
                            "type": "number",
                        },
                        "time": {
                            "cube_member": "records.time",
                            "title": "时间",
                            "description": "local",
                            "kind": "dimension",
                            "type": "time",
                        },
                    },
                }
            ],
        }
    )


def query(**updates: Any) -> SemanticQuery:
    return SemanticQuery.model_validate(
        {"dataset": "records", "model_version": "v1", "measures": ["amount"], **updates}
    )


def meta(version: str = "v1") -> dict[str, Any]:
    return {
        "cubes": [
            {
                "name": "records",
                "meta": {"model_version": version},
                "measures": [{"name": "records.amount", "type": "number"}],
                "dimensions": [
                    {"name": "records." + n, "type": t}
                    for n, t in [("id", "number"), ("area", "string"), ("time", "time")]
                ],
            }
        ]
    }


def reader(config: SemanticConfig, handler: Any) -> CubeSemanticReader:
    return CubeSemanticReader(
        config, httpx.AsyncClient(base_url=config.base_url, transport=httpx.MockTransport(handler))
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "x"},
        {"sql": "SELECT 1"},
        {"limit": 201},
        {"limit": True},
        {"measures": ["amount", "amount"]},
        {"measures": []},
        {"filters": [{"member": "id", "operator": "gte", "values": []}]},
        {"time": {"dimension": "time", "start": "2026-02-01", "end_exclusive": "2026-01-01"}},
    ],
)
def test_strict_arguments(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        query(**changes)


async def test_denied_identity_never_reaches_cube(config: SemanticConfig) -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("unauthorized IO")

    r = reader(config, forbidden)
    denied = TrustedContext(tenant_id="other", user_id="u")
    assert (await r.discover(Discover(), denied))["datasets"] == []
    for action, request in [(r.describe, Describe(dataset="records")), (r.query, query())]:
        with pytest.raises(SemanticError, match="无权"):
            await action(request, denied)
    await r.aclose()


async def test_token_precision_limits_and_no_internal_columns(config: SemanticConfig) -> None:
    calls = []

    def respond(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        private = serialization.load_pem_private_key(
            Path(config.signing_key_file).read_bytes(), None
        )
        claims = jwt.decode(
            req.headers["authorization"].split()[1],
            private.public_key(),
            algorithms=["RS256"],
            audience=config.audience,
            issuer=config.issuer,
        )
        assert claims["tenant_id"] == "t" and claims["dataset"] == "records"
        assert claims["exp"] - claims["iat"] == 60
        if req.url.path.endswith("meta"):
            return httpx.Response(200, json=meta())
        assert json.loads(req.content)["query"]["limit"] == 2
        return httpx.Response(
            200,
            json={
                "data": [
                    {"records.amount": "9007199254740993.01", "private": "hidden"},
                    {"records.amount": None},
                ]
            },
        )

    r = reader(config, respond)
    result = await r.query(query(limit=1), TRUSTED)
    assert result["rows"] == [{"amount": "9007199254740993.01"}]
    assert result["truncated"] and result["data_as_of"] is None
    assert result["invocation_id"] == "inv" and len(calls) == 3
    assert "cube_member" not in str(result)
    await r.aclose()


@pytest.mark.parametrize(
    "payload",
    [
        {"model_version": "old"},
        {"measures": ["secret"]},
        {"dimensions": ["amount"]},
        {"filters": [{"member": "area", "operator": "gt", "values": ["x"]}]},
        {"filters": [{"member": "id", "operator": "equals", "values": ["NaN"]}]},
        {"order_by": [{"member": "area"}]},
    ],
)
async def test_invalid_semantics_do_not_execute(
    config: SemanticConfig, payload: dict[str, Any]
) -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("unexpected IO")

    r = reader(config, forbidden)
    with pytest.raises(SemanticError):
        await r.query(query(**payload), TRUSTED)
    await r.aclose()


async def test_model_change_after_execution_discards_rows(config: SemanticConfig) -> None:
    count = 0

    def respond(req: httpx.Request) -> httpx.Response:
        nonlocal count
        if req.url.path.endswith("meta"):
            count += 1
            return httpx.Response(200, json=meta("v1" if count == 1 else "v2"))
        return httpx.Response(200, json={"data": [{"records.amount": "10"}]})

    r = reader(config, respond)
    with pytest.raises(SemanticError) as e:
        await r.query(query(), TRUSTED)
    assert e.value.code == "MODEL_CHANGED"
    await r.aclose()


async def test_half_open_local_dates(config: SemanticConfig) -> None:
    r = reader(config, lambda _: httpx.Response(500))
    q = query(
        time={
            "dimension": "time",
            "start": "2026-10-01",
            "end_exclusive": "2026-11-01",
            "timezone": "Asia/Shanghai",
        }
    )
    result = r._compile(q, config.datasets[0])
    assert [f["operator"] for f in result["filters"]] == ["afterOrOnDate", "beforeDate"]
    assert result["timezone"] == "Asia/Shanghai"
    await r.aclose()


async def test_timeout_attempts_cancel_without_claiming_success(config: SemanticConfig) -> None:
    cancelled = []

    async def respond(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE":
            cancelled.append(req.url.path)
            return httpx.Response(200, json={})
        if req.url.path.endswith("meta"):
            return httpx.Response(200, json=meta())
        await asyncio.sleep(3)
        return httpx.Response(200, json={"data": []})

    r = reader(config.model_copy(update={"timeout_seconds": 1}), respond)
    with pytest.raises(SemanticError) as e:
        await r.query(query(), TRUSTED)
    assert e.value.code == "QUERY_TIMEOUT" and len(cancelled) == 1
    await r.aclose()


async def test_safe_tool_errors_and_annotations(config: SemanticConfig) -> None:
    r = reader(config, lambda _: httpx.Response(500, text="password=secret"))
    extension = SemanticExtension(r)
    response = await extension.describe({"dataset": "records"}, TRUSTED)
    assert response.is_error and "secret" not in response.text
    assert json.loads(response.text)["code"] == "UPSTREAM_UNAVAILABLE"
    assert all(t.descriptor.read_only for t in extension.package().tools)
    await r.aclose()


async def test_http_timeout_also_requests_cancellation(config: SemanticConfig) -> None:
    cancelled = []

    def respond(req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE":
            cancelled.append(req.url.path)
            return httpx.Response(200, json={})
        if req.url.path.endswith("meta"):
            return httpx.Response(200, json=meta())
        raise httpx.ReadTimeout("private endpoint", request=req)

    r = reader(config, respond)
    with pytest.raises(SemanticError) as e:
        await r.query(query(), TRUSTED)
    assert e.value.code == "QUERY_TIMEOUT" and cancelled
    await r.aclose()


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "not-a-number", 0.01])
async def test_invalid_or_imprecise_numbers_are_not_reported(
    config: SemanticConfig, value: Any
) -> None:
    r = reader(
        config,
        lambda req: httpx.Response(
            200,
            json=meta() if req.url.path.endswith("meta") else {"data": [{"records.amount": value}]},
        ),
    )
    with pytest.raises(SemanticError):
        await r.query(query(), TRUSTED)
    await r.aclose()


def test_semantic_front_door_uses_trusted_identity_and_closes_client(
    config: SemanticConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient
    from tests.conftest import mcp_headers, rpc

    from auramcp.composition.app import create_app
    from auramcp.infrastructure.settings import Settings

    config.datasets[0].allowed_tenants = ["tenant-a"]
    config.datasets[0].allowed_users = ["user-a"]
    calls = []

    def respond(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(
            200,
            json=meta()
            if req.url.path.endswith("meta")
            else {"data": [{"records.amount": "10.50"}]},
        )

    r = reader(config, respond)
    monkeypatch.setattr("auramcp.composition.app.CubeSemanticReader", lambda _: r)
    path = tmp_path / "semantic.json"
    path.write_text(config.model_dump_json())
    settings = Settings(
        _env_file=None,
        platform_store="memory",
        hands_workload_token="test-workload",
        allow_insecure_identity=False,
        semantic_config_file=str(path),
    )
    with TestClient(create_app(settings)) as client:
        for method, args in [
            ("discover", {}),
            ("describe", {"dataset": "records"}),
            ("query", query().model_dump()),
        ]:
            name = "auramcp.semantic." + method
            response = client.post(
                "/mcp",
                json=rpc("tools/call", {"name": name, "arguments": args}),
                headers=mcp_headers("tools/call", name=name),
            )
            assert response.status_code == 200 and not response.json()["result"]["isError"]
        before = len(calls)
        name = "auramcp.semantic.query"
        response = client.post(
            "/mcp",
            json=rpc(
                "tools/call", {"name": name, "arguments": query().model_dump()}, tenant="other"
            ),
            headers={**mcp_headers("tools/call", name=name), "X-CT-Tenant-ID": "other"},
        )
        assert response.json()["result"]["isError"] and len(calls) == before
    assert r._client.is_closed
