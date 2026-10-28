"""Private Cube adapter. No business rows or credentials use the platform store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auramcp.contracts.identity import TrustedContext
from auramcp.contracts.semantic import Describe, Discover, SemanticQuery
from auramcp.domain.semantic import SemanticError


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cube_member: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$")
    title: str
    description: str
    kind: Literal["measure", "dimension"]
    type: Literal["number", "string", "time", "boolean"]
    unit: str | None = None


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str
    description: str
    cube: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    model_version: str
    allowed_tenants: list[str] = Field(min_length=1)
    allowed_users: list[str] = Field(min_length=1)
    timezone: str = "Asia/Shanghai"
    members: dict[str, Member]

    @model_validator(mode="after")
    def validate_members(self) -> Dataset:
        if not self.members or any(
            not m.cube_member.startswith(self.cube + ".") for m in self.members.values()
        ):
            raise ValueError("members must belong to the configured view")
        if len({m.cube_member for m in self.members.values()}) != len(self.members):
            raise ValueError("duplicate member mapping")
        return self

    def authorized(self, trusted: TrustedContext) -> bool:
        return trusted.tenant_id in self.allowed_tenants and trusted.user_id in self.allowed_users


class SemanticConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str
    signing_key_file: str
    issuer: str = "auramcp-semantic"
    audience: str = "cube-semantic"
    timeout_seconds: float = Field(default=12, ge=1, le=20)
    max_response_bytes: int = Field(default=2_000_000, ge=1024, le=4_000_000)
    datasets: list[Dataset] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_endpoint(self) -> SemanticConfig:
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("invalid configured Cube endpoint")
        if len({d.name for d in self.datasets}) != len(self.datasets):
            raise ValueError("duplicate datasets")
        return self


class CubeSemanticReader:
    def __init__(self, config: SemanticConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._key = Path(config.signing_key_file).read_text()
        # Validate key at startup; never fall back to unsigned/HS256 tokens.
        jwt.encode({"probe": True}, self._key, algorithm="RS256")
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url.rstrip("/") + "/",
            trust_env=False,
            follow_redirects=False,
            timeout=config.timeout_seconds,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    def _dataset(self, name: str, trusted: TrustedContext) -> Dataset:
        for dataset in self.config.datasets:
            if dataset.name == name and dataset.authorized(trusted):
                return dataset
        raise SemanticError("ACCESS_DENIED", "无权访问此数据集。")

    def _token(self, dataset: Dataset, trusted: TrustedContext) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": self.config.issuer,
                "aud": self.config.audience,
                "iat": now,
                "exp": now + 60,
                "tenant_id": trusted.tenant_id,
                "user_id": trusted.user_id,
                "dept_id": trusted.dept_id,
                "dataset": dataset.name,
                "model_version": dataset.model_version,
            },
            self._key,
            algorithm="RS256",
        )

    async def _request(
        self,
        path: str,
        dataset: Dataset,
        trusted: TrustedContext,
        request_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": "Bearer " + self._token(dataset, trusted),
            "x-request-id": request_id,
        }
        try:
            async with self._client.stream(
                "GET" if body is None else "POST",
                path,
                headers=headers,
                json=body,
            ) as response:
                if response.status_code in {401, 403}:
                    raise SemanticError("ACCESS_DENIED", "语义服务拒绝当前身份，请联系管理员。")
                if response.status_code != 200:
                    raise SemanticError("UPSTREAM_UNAVAILABLE", "语义服务暂不可用，请稍后重试。")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > self.config.max_response_bytes:
                        raise SemanticError("RESULT_TOO_LARGE", "结果过大，请缩小范围。")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("invalid response")
            if data.get("error") and data["error"] != "Continue wait":
                raise SemanticError(
                    "QUERY_FAILED", "查询未完成，请核对模型、筛选范围或联系管理员。"
                )
            return data
        except httpx.TimeoutException:
            raise SemanticError("QUERY_TIMEOUT", "查询超时，请缩小范围。") from None
        except (httpx.HTTPError, ValueError):
            raise SemanticError("UPSTREAM_UNAVAILABLE", "语义服务响应异常。") from None

    async def _meta(self, dataset: Dataset, trusted: TrustedContext, rid: str) -> None:
        data = await self._request("meta", dataset, trusted, rid)
        cubes = data.get("cubes", [])
        if not isinstance(cubes, list) or any(not isinstance(v, dict) for v in cubes):
            raise SemanticError("UPSTREAM_UNAVAILABLE", "语义服务模型响应异常。")
        view = next((v for v in cubes if v.get("name") == dataset.cube), None)
        if (
            not view
            or not isinstance(view.get("meta"), dict)
            or view["meta"].get("model_version") != dataset.model_version
        ):
            raise SemanticError(
                "MODEL_CHANGED", "模型版本已变化，请联系管理员同步模型后重新 describe。"
            )
        for key in ("measures", "dimensions"):
            items = view.get(key)
            if not isinstance(items, list) or any(
                not isinstance(m, dict) or not isinstance(m.get("name"), str) for m in items
            ):
                raise SemanticError("UPSTREAM_UNAVAILABLE", "语义服务模型字段异常。")
        available = {
            m["name"]: (kind, m.get("type"))
            for kind, key in [("measure", "measures"), ("dimension", "dimensions")]
            for m in view.get(key, [])
        }
        if any(available.get(m.cube_member) != (m.kind, m.type) for m in dataset.members.values()):
            raise SemanticError("MODEL_CHANGED", "模型字段或类型已变化，请同步模型配置。")

    async def discover(self, request: Discover, trusted: TrustedContext) -> dict[str, Any]:
        # Static approved catalog avoids leaking Cube's physical metadata and cross-identity caches.
        visible = [
            d
            for d in self.config.datasets
            if d.authorized(trusted)
            and request.search.casefold() in (d.name + d.title + d.description).casefold()
        ]
        selected = visible[request.offset : request.offset + request.limit]
        return {
            "datasets": [
                {"dataset": d.name, "title": d.title, "description": d.description}
                for d in selected
            ],
            "next_offset": request.offset + request.limit
            if len(visible) > request.offset + request.limit
            else None,
        }

    async def describe(self, request: Describe, trusted: TrustedContext) -> dict[str, Any]:
        d = self._dataset(request.dataset, trusted)
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                await self._meta(d, trusted, uuid.uuid4().hex)
        except TimeoutError:
            raise SemanticError("QUERY_TIMEOUT", "模型查询超时。") from None
        return {
            "dataset": d.name,
            "title": d.title,
            "description": d.description,
            "model_version": d.model_version,
            "timezone": d.timezone,
            "members": {
                name: m.model_dump(exclude={"cube_member"}) for name, m in d.members.items()
            },
            "limits": {"rows": 200, "filters": 12, "timeout_seconds": self.config.timeout_seconds},
            "time_semantics": "start inclusive; end_exclusive exclusive; local wall time",
            "read_only": True,
        }

    def _compile(self, query: SemanticQuery, d: Dataset) -> dict[str, Any]:
        if query.model_version != d.model_version:
            raise SemanticError("MODEL_CHANGED", "请重新 describe 并使用当前 model_version。")

        def member(name: str, kind: str | None = None) -> Member:
            value = d.members.get(name)
            if not value or (kind and value.kind != kind):
                raise SemanticError("INVALID_QUERY", "指标或维度不在允许范围内。")
            return value

        measures = [member(n, "measure").cube_member for n in query.measures]
        dimensions = [member(n, "dimension").cube_member for n in query.dimensions]
        filters: list[dict[str, Any]] = []
        for f in query.filters:
            m = member(f.member, "dimension")
            if m.type == "time":
                raise SemanticError("INVALID_QUERY", "时间字段请使用 time 范围。")
            if f.operator in {"gt", "gte", "lt", "lte"} and m.type != "number":
                raise SemanticError("INVALID_QUERY", "范围比较仅支持数值字段。")
            if m.type == "number":
                try:
                    if any(not Decimal(v).is_finite() for v in f.values):
                        raise InvalidOperation
                except InvalidOperation:
                    raise SemanticError("INVALID_QUERY", "数值筛选必须是有限十进制数。") from None
            filters.append(
                {
                    "member": m.cube_member,
                    "operator": f.operator,
                    **({"values": f.values} if f.values else {}),
                }
            )
        if query.time:
            t = query.time
            m = member(t.dimension, "dimension")
            if m.type != "time" or t.timezone != d.timezone:
                raise SemanticError("INVALID_QUERY", "请选择时间维度并使用模型业务时区。")
            filters.extend(
                [
                    {"member": m.cube_member, "operator": "afterOrOnDate", "values": [t.start]},
                    {
                        "member": m.cube_member,
                        "operator": "beforeDate",
                        "values": [t.end_exclusive],
                    },
                ]
            )
        selected = set(query.measures + query.dimensions)
        if any(o.member not in selected for o in query.order_by):
            raise SemanticError("INVALID_QUERY", "排序字段必须出现在结果中。")
        order = [[member(o.member).cube_member, o.direction] for o in query.order_by]
        if not order:
            order = [[n, "asc"] for n in dimensions]
        return {
            "measures": measures,
            "dimensions": dimensions,
            "filters": filters,
            "order": order,
            "limit": query.limit + 1,
            "timezone": d.timezone,
        }

    async def query(self, request: SemanticQuery, trusted: TrustedContext) -> dict[str, Any]:
        d = self._dataset(request.dataset, trusted)
        query = self._compile(request, d)
        rid = uuid.uuid4().hex
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                await self._meta(d, trusted, rid + "-meta")
                for attempt in range(5):
                    result = await self._request("load", d, trusted, rid, {"query": query})
                    if result.get("error") != "Continue wait":
                        break
                    await asyncio.sleep(min(0.2 * 2**attempt, 1))
                else:
                    raise TimeoutError
                # Immutable release + postcheck detects model changes during execution.
                await self._meta(d, trusted, rid + "-post")
        except (TimeoutError, asyncio.CancelledError, SemanticError) as exc:
            if isinstance(exc, SemanticError) and exc.code != "QUERY_TIMEOUT":
                raise
            # Best effort: closing HTTP alone does not cancel database execution.
            try:
                async with asyncio.timeout(1):
                    await self._client.delete(
                        "running-query/" + rid,
                        headers={"Authorization": "Bearer " + self._token(d, trusted)},
                    )
            except (TimeoutError, httpx.HTTPError):
                pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise SemanticError("QUERY_TIMEOUT", "查询超时，已请求取消；请缩小范围。") from None
        rows = result.get("data")
        if not isinstance(rows, list):
            raise SemanticError("UPSTREAM_UNAVAILABLE", "语义服务未返回有效结果。")
        names = request.dimensions + request.measures
        output: list[dict[str, Any]] = []
        size, text_truncated = 0, False
        for row in rows[: request.limit]:
            if not isinstance(row, dict) or any(d.members[n].cube_member not in row for n in names):
                raise SemanticError("UPSTREAM_UNAVAILABLE", "语义服务返回列与请求不符。")
            normalized = {}
            for name in names:
                value = row[d.members[name].cube_member]
                if isinstance(value, (dict, list)):
                    raise SemanticError("UPSTREAM_UNAVAILABLE", "语义服务字段类型异常。")
                if d.members[name].type == "number" and value is not None:
                    if isinstance(value, float):
                        raise SemanticError(
                            "PRECISION_UNVERIFIED", "数值精度无法确认，请联系管理员。"
                        )
                    try:
                        if isinstance(value, bool) or not Decimal(str(value)).is_finite():
                            raise InvalidOperation
                    except InvalidOperation:
                        raise SemanticError(
                            "UPSTREAM_UNAVAILABLE", "语义服务返回无效数值。"
                        ) from None
                    value = str(value)
                if isinstance(value, str) and len(value) > 4000:
                    text_truncated = True
                    value = value[:4000]
                normalized[name] = value
            size += len(json.dumps(normalized, ensure_ascii=False).encode())
            if size > 128000:
                break
            output.append(normalized)
        return {
            "dataset": d.name,
            "model_version": d.model_version,
            "query": request.model_dump(),
            "rows": output,
            "row_count": len(output),
            "columns": {n: d.members[n].model_dump(exclude={"cube_member"}) for n in names},
            "truncated": len(rows) > len(output),
            "text_truncated": text_truncated,
            "completed_at": datetime.now(UTC).isoformat(),
            "cache_refreshed_at": result.get("lastRefreshTime"),
            "data_as_of": None,
            "used_pre_aggregation": bool(result.get("usedPreAggregations")),
            "request_id": rid,
            "invocation_id": trusted.invocation_id,
            "query_digest": hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest(),
            "read_only": True,
        }

    async def aclose(self) -> None:
        await self._client.aclose()
