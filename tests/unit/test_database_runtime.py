from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import asyncpg  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient
from tests.conftest import mcp_headers, rpc

from auramcp.composition.app import create_app
from auramcp.contracts.database import DatabaseQuery
from auramcp.infrastructure.analytics import AnalyticsConfig, PostgresAnalytics
from auramcp.infrastructure.settings import Settings


def config() -> AnalyticsConfig:
    return AnalyticsConfig(
        host="configured-only",
        database="capability",
        user="reader",
        password_file="secret",
        allowed_tenants=("tenant-a",),
        allowed_users=("user-a",),
        tables=[
            {
                "alias": "records",
                "schema_name": "public",
                "table_name": "records",
                "columns": ["id", "title"],
                "default_columns": ["id", "title"],
                "default_order": "id",
            }
        ],
    )


class Connection:
    def __init__(self, rows: list[dict[str, Any]], error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.readonly: bool | None = None
        self.sql = ""

    async def __aenter__(self) -> Connection:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def transaction(self, *, readonly: bool) -> Connection:
        self.readonly = readonly
        return self

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        assert self.readonly is True
        self.sql = sql
        if self.error:
            raise self.error
        return self.rows


class Pool:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.closed = False

    def acquire(self, **kwargs: Any) -> Connection:
        return self.connection

    async def close(self) -> None:
        self.closed = True


def reader(pool: Pool) -> PostgresAnalytics:
    return PostgresAnalytics(
        config(),
        pool,
        {
            "records": [
                {"name": "id", "kind": "int8", "type": "bigint", "comment": "key"},
                {"name": "title", "kind": "text", "type": "text", "comment": "title"},
            ]
        },
    )


@pytest.mark.asyncio
async def test_query_is_readonly_and_marks_row_and_text_truncation() -> None:
    conn = Connection([{"id": 1, "title": "x" * 5000}, {"id": 2, "title": "other"}])
    r = reader(Pool(conn))
    result = await r.query(DatabaseQuery(table="records", limit=1))
    assert conn.readonly is True and result["row_count"] == 1
    assert result["truncated"] is True and result["text_truncated"] is True
    assert len(result["rows"][0]["title"]) == 4000
    assert "configured-only" not in json.dumps(await r.describe())


@pytest.mark.asyncio
async def test_query_timeout_and_server_error_are_sanitized() -> None:
    q = DatabaseQuery(table="records")
    with pytest.raises(TimeoutError):
        await reader(Pool(Connection([], asyncpg.QueryCanceledError("private SQL")))).query(q)
    with pytest.raises(ValueError, match="数据库查询失败") as error:
        await reader(Pool(Connection([], asyncpg.PostgresError("password=secret")))).query(q)
    assert "secret" not in str(error.value)


def test_opt_in_database_tools_use_mcp_and_close_the_independent_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = Pool(Connection([{"id": 1, "title": "sample"}]))
    r = reader(pool)
    monkeypatch.setattr(PostgresAnalytics, "connect", AsyncMock(return_value=r))
    path = tmp_path / "analytics.json"
    path.write_text(config().model_dump_json())
    settings = Settings(
        _env_file=None,
        platform_store="memory",
        allow_insecure_identity=False,
        hands_workload_token="test-workload",
        analytics_config_file=str(path),
    )
    with TestClient(create_app(settings)) as client:
        tools = client.post("/mcp", json=rpc("tools/list"), headers=mcp_headers("tools/list"))
        names = [t["name"] for t in tools.json()["result"]["tools"]]
        assert "auramcp.database.describe" in names and "auramcp.database.query" in names
        for method, arguments in (("describe", {}), ("query", {"table": "records"})):
            name = "auramcp.database." + method
            response = client.post(
                "/mcp",
                json=rpc("tools/call", {"name": name, "arguments": arguments}),
                headers=mcp_headers("tools/call", name=name),
            )
            assert response.status_code == 200 and not response.json()["result"]["isError"]
        denied = client.post(
            "/mcp",
            json=rpc(
                "tools/call",
                {"name": "auramcp.database.query", "arguments": {"table": "records"}},
                tenant="other",
            ),
            headers={
                **mcp_headers("tools/call", name="auramcp.database.query"),
                "X-CT-Tenant-ID": "other",
            },
        )
        assert denied.json()["result"]["isError"] is True
    assert pool.closed is True
