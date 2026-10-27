from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from auramcp.contracts.database import DatabaseQuery
from auramcp.contracts.identity import TrustedContext
from auramcp.extensions.database import DatabaseExtension
from auramcp.infrastructure.analytics import Relation, compile_query, convert, json_value
from auramcp.infrastructure.settings import Settings


@pytest.fixture
def table() -> Relation:
    return Relation(
        alias="records",
        schema_name="public",
        table_name="records",
        columns=["id", "title", "amount", "created_at", "area"],
        default_columns=["id", "title"],
        default_order="id",
    )


TYPES = {
    "id": "int8",
    "title": "text",
    "amount": "numeric",
    "created_at": "timestamp",
    "area": "text",
}


def test_query_binds_values_and_quotes_only_configured_identifiers(table: Relation) -> None:
    attack = "'; DROP TABLE records; --%_"
    q = DatabaseQuery(
        table="records", filters=[{"column": "title", "operator": "contains", "value": attack}]
    )
    sql, values, columns = compile_query(q, table, TYPES)
    assert attack not in sql and "ILIKE $1" in sql and sql.endswith("LIMIT $2")
    assert values == ["%'; DROP TABLE records; --\\%\\_%", 51]
    assert columns == ["id", "title"]
    assert 'ORDER BY "id" DESC NULLS LAST' in sql


@pytest.mark.parametrize(
    "payload",
    [
        {"table": "private"},
        {"table": "records", "columns": ["password"]},
        {"table": "records", "filters": [{"column": "secret", "value": "x"}]},
        {"table": "records", "order_by": [{"column": "id; DELETE", "direction": "asc"}]},
        {
            "table": "records",
            "group_by": ["private"],
            "aggregates": [{"function": "count", "alias": "n"}],
        },
        {"table": "records", "aggregates": [{"function": "sum", "column": "title", "alias": "n"}]},
    ],
)
def test_forbidden_scope_rejected(table: Relation, payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        compile_query(DatabaseQuery.model_validate(payload), table, TYPES)


@pytest.mark.parametrize(
    "extra",
    [
        {"sql": "SELECT 1"},
        {"host": "localhost"},
        {"limit": 201},
        {"limit": True},
        {"limit": 0},
        {"aggregates": [{"function": "pg_sleep", "alias": "n"}]},
        {"columns": ["id"], "aggregates": [{"function": "count", "alias": "n"}]},
        {"aggregates": [{"function": "sum", "alias": "n"}]},
        {"aggregates": [{"function": "count", "alias": "n"}, {"function": "count", "alias": "n"}]},
    ],
)
def test_invalid_queries_do_not_reach_database(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DatabaseQuery.model_validate({"table": "records", **extra})


def test_typed_filters_and_grouped_statistics(table: Relation) -> None:
    q = DatabaseQuery.model_validate(
        {
            "table": "records",
            "filters": [
                {"column": "created_at", "operator": "gte", "value": "2026-10-01T00:00:00"},
                {"column": "amount", "operator": "gte", "value": "12.30"},
            ],
            "group_by": ["area"],
            "aggregates": [
                {"function": "count", "alias": "n"},
                {"function": "sum", "column": "amount", "alias": "total"},
            ],
            "order_by": [{"column": "n", "direction": "desc"}],
            "limit": 10,
        }
    )
    sql, values, names = compile_query(q, table, TYPES)
    assert 'pg_catalog.count(*) AS "n"' in sql
    assert 'pg_catalog.sum("amount") AS "total"' in sql
    assert 'GROUP BY "area" ORDER BY "n" DESC NULLS LAST' in sql
    assert values == [datetime(2026, 10, 1), Decimal("12.30"), 11]
    assert names == ["area", "n", "total"]


@pytest.mark.parametrize(
    "value,kind",
    [
        (True, "int8"),
        ("1.5", "int8"),
        ("NaN", "numeric"),
        ("yesterday", "timestamp"),
        ("yes", "bool"),
    ],
)
def test_invalid_filter_type_is_sanitized(value: Any, kind: str) -> None:
    with pytest.raises(ValueError, match="类型"):
        convert(value, kind)


def test_decimal_precision_and_timestamp_are_preserved() -> None:
    assert json_value(Decimal("123456789.12")) == "123456789.12"
    assert json_value(2**63 - 1) == str(2**63 - 1)
    assert json_value(datetime(2026, 10, 27, 1, 2)) == "2026-10-27T01:02:00"


class Reader:
    calls = 0

    async def describe(self) -> dict[str, Any]:
        self.calls += 1
        return {"tables": []}

    async def query(self, query: DatabaseQuery) -> dict[str, Any]:
        self.calls += 1
        return {"table": query.table, "rows": []}

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_unauthorized_identity_cannot_discover_or_query() -> None:
    reader = Reader()
    extension = DatabaseExtension(reader, tenants=("platform",), users=("local-user",))
    for trusted in (
        TrustedContext(tenant_id="other", user_id="local-user"),
        TrustedContext(tenant_id="platform", user_id="other"),
    ):
        assert (await extension.describe({}, trusted)).is_error
        assert (await extension.query({"table": "records"}, trusted)).is_error
    assert reader.calls == 0


@pytest.mark.asyncio
async def test_valid_input_reaches_port_and_target_injection_does_not() -> None:
    reader = Reader()
    extension = DatabaseExtension(reader, tenants=("platform",), users=("local-user",))
    trusted = TrustedContext(tenant_id="platform", user_id="local-user")
    assert not (await extension.query({"table": "records"}, trusted)).is_error
    assert (await extension.query({"table": "records", "sql": "DELETE"}, trusted)).is_error
    assert (await extension.describe({"host": "other"}, trusted)).is_error
    assert reader.calls == 1


def test_secret_files_and_escaped_governance_dsn(tmp_path: Any) -> None:
    secret = tmp_path / "secret"
    secret.write_text("test@secret#value\n")
    s = Settings(
        _env_file=None,
        platform_store="memory",
        hands_workload_token_file=str(secret),
        db_password_file=str(secret),
        db_user="user@name",
    )
    assert s.hands_workload_token == "test@secret#value"
    assert "user%40name:test%40secret%23value@" in s.dsn
    assert "test@secret" not in repr(s)
