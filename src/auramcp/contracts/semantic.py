"""Bounded semantic queries. Identity, connections and SQL are never arguments."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Discover(StrictModel):
    search: str = Field(default="", max_length=100)
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=20, ge=1, le=50)


class Describe(StrictModel):
    dataset: Name


class SemanticFilter(StrictModel):
    member: Name
    operator: Literal["equals", "notEquals", "gt", "gte", "lt", "lte", "set", "notSet"]
    values: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def check_values(self) -> SemanticFilter:
        if self.operator in {"set", "notSet"}:
            if self.values:
                raise ValueError("null filters take no values")
        elif not self.values or (
            self.operator in {"gt", "gte", "lt", "lte"} and len(self.values) != 1
        ):
            raise ValueError("invalid filter values")
        return self


class SemanticOrder(StrictModel):
    member: Name
    direction: Literal["asc", "desc"] = "desc"


class TimeRange(StrictModel):
    dimension: Name
    start: str
    end_exclusive: str
    timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def bounds(self) -> TimeRange:
        # Phase one accepts local wall time for explicitly modeled timestamp-without-time-zone.
        start, end = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end_exclusive)
        if start.tzinfo or end.tzinfo or start >= end or (end - start).days > 366:
            raise ValueError("use increasing local ISO dates/times within 366 days")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown timezone") from exc
        return self


class SemanticQuery(Describe):
    model_version: str = Field(min_length=1, max_length=100)
    measures: list[Name] = Field(min_length=1, max_length=8)
    dimensions: list[Name] = Field(default_factory=list, max_length=4)
    filters: list[SemanticFilter] = Field(default_factory=list, max_length=12)
    time: TimeRange | None = None
    order_by: list[SemanticOrder] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("measures", "dimensions")
    @classmethod
    def unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate members")
        return values
