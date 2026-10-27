"""An independent capability connection; never uses the governance database settings."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auramcp.contracts.database import DatabaseQuery


class Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    schema_name: str
    table_name: str
    columns: list[str] = Field(min_length=1, max_length=50)
    default_columns: list[str] = Field(min_length=1, max_length=20)
    default_order: str
    description: str = ""

    @model_validator(mode="after")
    def verify_defaults(self) -> Relation:
        if not set(self.default_columns + [self.default_order]) <= set(self.columns):
            raise ValueError("default projection and order must be allowed columns")
        return self


class AnalyticsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    database: str
    user: str
    password_file: str
    ssl: str = "prefer"
    allowed_tenants: tuple[str, ...] = Field(min_length=1)
    allowed_users: tuple[str, ...] = Field(min_length=1)
    tables: list[Relation] = Field(min_length=1, max_length=10)
    statement_timeout_ms: int = Field(default=5000, ge=100, le=30000)

    @model_validator(mode="after")
    def unique_tables(self) -> AnalyticsConfig:
        if len({r.alias for r in self.tables}) != len(self.tables):
            raise ValueError("table aliases must be unique")
        return self


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def convert(value: Any, kind: str) -> Any:
    if value is None:
        return None
    try:
        if kind in {"int2", "int4", "int8"}:
            if isinstance(value, bool) or str(int(str(value))) != str(value):
                raise ValueError
            return int(str(value))
        if kind in {"numeric", "float4", "float8"}:
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError
            return number if kind == "numeric" else float(number)
        if kind in {"timestamp", "timestamptz"}:
            result = datetime.fromisoformat(str(value))
            if (result.tzinfo is not None) != (kind == "timestamptz"):
                raise ValueError
            return result
        if kind == "date":
            return date.fromisoformat(str(value))
        if kind == "bool":
            if not isinstance(value, bool):
                raise ValueError
            return value
        if kind in {"text", "varchar", "bpchar"}:
            return str(value)
    except (ValueError, ArithmeticError):
        raise ValueError("筛选值与字段类型不符，请查看字段说明。") from None
    raise ValueError("该字段类型尚不支持筛选。")


def compile_query(
    request: DatabaseQuery, table: Relation, types: dict[str, str]
) -> tuple[str, list[Any], list[str]]:
    if request.table != table.alias:
        raise ValueError("该表不在允许查询范围内。")

    def column(name: str) -> str:
        if name not in table.columns:
            raise ValueError("字段不在允许查询范围内，请先查看表结构。")
        return quote(name)

    values: list[Any] = []
    predicates = []
    for item in request.filters:
        key = column(item.column)
        if item.operator == "is_null":
            if item.value is not None:
                raise ValueError("is_null 不接受 value。")
            predicates.append(f"{key} IS NULL")
        elif item.value is None:
            raise ValueError("空值筛选请使用 is_null。")
        elif item.operator == "contains":
            if types[item.column] not in {"text", "varchar", "bpchar"}:
                raise ValueError("contains 只支持文本字段。")
            text = str(item.value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append(f"%{text}%")
            predicates.append(f"{key} ILIKE ${len(values)} ESCAPE '\\'")
        else:
            operator = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[
                item.operator
            ]
            values.append(convert(item.value, types[item.column]))
            predicates.append(f"{key} {operator} ${len(values)}")
    if request.aggregates:
        projection = [column(c) for c in request.group_by]
        names = list(request.group_by)
        for aggregate in request.aggregates:
            target = "*" if aggregate.column is None else column(aggregate.column)
            if aggregate.function in {"sum", "avg"} and types[aggregate.column or ""] not in {
                "int2",
                "int4",
                "int8",
                "numeric",
                "float4",
                "float8",
            }:
                raise ValueError("sum/avg 只支持数值字段。")
            projection.append(
                f"pg_catalog.{aggregate.function}({target}) AS {quote(aggregate.alias)}"
            )
            names.append(aggregate.alias)
    else:
        names = request.columns or table.default_columns
        projection = [column(c) for c in names]
    sql = (
        f"SELECT {', '.join(projection)} FROM {quote(table.schema_name)}.{quote(table.table_name)}"
    )
    if predicates:
        sql += " WHERE " + " AND ".join(predicates)
    if request.group_by:
        sql += " GROUP BY " + ", ".join(column(c) for c in request.group_by)
    order = []
    for ordering in request.order_by:
        if request.aggregates:
            if ordering.column not in names:
                raise ValueError("统计排序只接受分组字段或聚合别名。")
            key = quote(ordering.column)
        else:
            key = column(ordering.column)
        order.append(f"{key} {ordering.direction.upper()} NULLS LAST")
    if not order and not request.aggregates:
        order = [column(table.default_order) + " DESC NULLS LAST"]
    if order:
        sql += " ORDER BY " + ", ".join(order)
    values.append(request.limit + 1)
    return sql + f" LIMIT ${len(values)}", values, names


def json_value(value: Any) -> Any:
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value[:4000] if isinstance(value, str) else value
    return str(value)[:4000]


class PostgresAnalytics:
    def __init__(self, config: AnalyticsConfig, pool: Any, metadata: dict[str, Any]) -> None:
        self.config = config
        self._pool = pool
        self._metadata = metadata

    @classmethod
    async def connect(cls, config: AnalyticsConfig) -> PostgresAnalytics:
        pool = await asyncpg.create_pool(
            host=config.host,
            port=config.port,
            database=config.database,
            user=config.user,
            password=(await asyncio.to_thread(Path(config.password_file).read_text)).strip(),
            ssl=config.ssl,
            min_size=1,
            max_size=2,
            timeout=5,
            server_settings={
                "default_transaction_read_only": "on",
                "search_path": "pg_catalog",
                "statement_timeout": str(config.statement_timeout_ms),
                "lock_timeout": "500",
            },
        )
        metadata = {}
        try:
            async with pool.acquire(timeout=5) as connection:
                for table in config.tables:
                    rows = await connection.fetch(
                        "SELECT a.attname AS name,t.typname AS kind,"
                        "pg_catalog.format_type(a.atttypid,a.atttypmod) AS type,"
                        "pg_catalog.col_description(a.attrelid,a.attnum) AS comment "
                        "FROM pg_catalog.pg_attribute a "
                        "JOIN pg_catalog.pg_type t ON t.oid=a.atttypid "
                        "WHERE a.attrelid=pg_catalog.to_regclass($1) AND a.attnum>0 "
                        "AND NOT a.attisdropped ORDER BY a.attnum",
                        f"{quote(table.schema_name)}.{quote(table.table_name)}",
                    )
                    selected = [dict(r) for r in rows if r["name"] in table.columns]
                    if {r["name"] for r in selected} != set(table.columns):
                        raise ValueError("Configured capability columns are unavailable")
                    metadata[table.alias] = selected
        except BaseException:
            await pool.close()
            raise
        return cls(config, pool, metadata)

    async def describe(self) -> dict[str, Any]:
        return {
            "tables": [
                {
                    "table": t.alias,
                    "description": t.description,
                    "columns": [
                        {k: v for k, v in c.items() if k != "kind"} for c in self._metadata[t.alias]
                    ],
                    "default_columns": t.default_columns,
                    "default_order": t.default_order,
                }
                for t in self.config.tables
            ],
            "limits": {"rows": 200, "query_timeout_ms": self.config.statement_timeout_ms},
            "read_only": True,
        }

    async def query(self, request: DatabaseQuery) -> dict[str, Any]:
        table = next((t for t in self.config.tables if t.alias == request.table), None)
        if table is None:
            raise ValueError("该表不在允许查询范围内。")
        types = {c["name"]: c["kind"] for c in self._metadata[table.alias]}
        sql, parameters, columns = compile_query(request, table, types)
        try:
            async with self._pool.acquire(timeout=5) as connection:
                async with connection.transaction(readonly=True):
                    records = await connection.fetch(sql, *parameters)
        except asyncpg.QueryCanceledError:
            raise TimeoutError from None
        except (asyncpg.PostgresError, OSError):
            raise ValueError("数据库查询失败，请缩小范围或检查字段类型。") from None
        rows = []
        size = 0
        text_truncated = False
        for record in records[: request.limit]:
            text_truncated |= any(isinstance(v, str) and len(v) > 4000 for v in record.values())
            row = {k: json_value(v) for k, v in record.items()}
            size += len(json.dumps(row, ensure_ascii=False).encode())
            if size > 128000:
                break
            rows.append(row)
        return {
            "table": table.alias,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": len(records) > len(rows),
            "text_truncated": text_truncated,
            "limit": request.limit,
            "read_only": True,
        }

    async def aclose(self) -> None:
        await self._pool.close()
