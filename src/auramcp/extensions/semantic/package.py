from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from auramcp.contracts.extensions import (
    ExtensionPackage,
    RegisteredTool,
    ToolCallResult,
    ToolDescriptor,
    ToolHandler,
)
from auramcp.contracts.identity import TrustedContext
from auramcp.contracts.semantic import Describe, Discover, SemanticQuery
from auramcp.domain.semantic import SemanticError, SemanticReader


class SemanticExtension:
    def __init__(self, reader: SemanticReader) -> None:
        self._reader = reader

    async def discover(self, args: dict[str, Any], trusted: TrustedContext) -> ToolCallResult:
        return await self._call("discover", args, trusted)

    async def describe(self, args: dict[str, Any], trusted: TrustedContext) -> ToolCallResult:
        return await self._call("describe", args, trusted)

    async def query(self, args: dict[str, Any], trusted: TrustedContext) -> ToolCallResult:
        return await self._call("query", args, trusted)

    async def _call(
        self, action: str, args: dict[str, Any], trusted: TrustedContext
    ) -> ToolCallResult:
        try:
            if action == "discover":
                data = await self._reader.discover(Discover.model_validate(args), trusted)
            elif action == "describe":
                data = await self._reader.describe(Describe.model_validate(args), trusted)
            else:
                data = await self._reader.query(SemanticQuery.model_validate(args), trusted)
            return ToolCallResult(structured=data)
        except ValidationError:
            code, message = "INVALID_QUERY", "参数无效，请按 describe 返回的模型和工具合同查询。"
        except SemanticError as exc:
            code, message = exc.code, exc.message
        return ToolCallResult(
            is_error=True, text=json.dumps({"code": code, "message": message}, ensure_ascii=False)
        )

    def package(self) -> ExtensionPackage:
        specs: list[tuple[str, type[BaseModel], ToolHandler, str]] = [
            (
                "discover",
                Discover,
                self.discover,
                "发现当前身份可访问的业务语义数据集；支持搜索和分页，不返回未授权模型。",
            ),
            (
                "describe",
                Describe,
                self.describe,
                "查询前读取指标口径、维度、单位、筛选限制与 model_version；不要猜测指标名。",
            ),
            (
                "query",
                SemanticQuery,
                self.query,
                "通过 Cube Core 执行只读业务指标查询。先 describe；指标已定义计算口径，"
                "不要传 SQL、连接或身份。时间为业务当地时间，start 包含、end_exclusive 不包含。"
                "金额保持原单位；limit 限制分组结果而非统计输入，按需限定筛选范围。",
            ),
        ]
        return ExtensionPackage(
            name="semantic",
            title="业务语义查询",
            version="1.0.0",
            description="Cube Core 业务指标、维度发现与受控只读聚合。",
            tools=tuple(
                RegisteredTool(
                    package="semantic",
                    descriptor=ToolDescriptor(
                        name=f"auramcp.semantic.{name}",
                        description=description,
                        version="1.0.0",
                        input_schema=model.model_json_schema(),
                        read_only=True,
                    ),
                    handler=handler,
                )
                for name, model, handler, description in specs
            ),
        )
