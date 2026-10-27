"""Bounded database reads; callers never supply connection targets or SQL."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    column: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "is_null"] = "eq"
    value: str | int | float | bool | None = None

    @model_validator(mode="after")
    def bound_value(self) -> Filter:
        if isinstance(self.value, str) and len(self.value) > 2000:
            raise ValueError("filter text exceeds the limit")
        return self


class Aggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    function: Literal["count", "sum", "avg", "min", "max"]
    column: str | None = None
    alias: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")

    @model_validator(mode="after")
    def require_column(self) -> Aggregate:
        if self.function != "count" and self.column is None:
            raise ValueError("aggregation requires a column")
        return self


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    column: str
    direction: Literal["asc", "desc"] = "desc"


class DatabaseQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    table: str = Field(min_length=1, max_length=100)
    columns: list[str] = Field(default_factory=list, max_length=30)
    filters: list[Filter] = Field(default_factory=list, max_length=12)
    group_by: list[str] = Field(default_factory=list, max_length=4)
    aggregates: list[Aggregate] = Field(default_factory=list, max_length=8)
    order_by: list[Order] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def validate_projection(self) -> DatabaseQuery:
        if self.columns and (self.group_by or self.aggregates):
            raise ValueError("use columns for rows or group_by/aggregates for statistics")
        if self.group_by and not self.aggregates:
            raise ValueError("group_by requires aggregates")
        aliases = [a.alias for a in self.aggregates]
        if len(aliases) != len(set(aliases)) or set(aliases) & set(self.group_by):
            raise ValueError("result column names must be unique")
        return self
