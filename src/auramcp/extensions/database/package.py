from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from auramcp.contracts.database import DatabaseQuery
from auramcp.contracts.extensions import (
    ExtensionPackage,
    RegisteredTool,
    ToolCallResult,
    ToolDescriptor,
)
from auramcp.contracts.identity import TrustedContext
from auramcp.domain.database import DatabaseReader


class DatabaseExtension:
    def __init__(
        self, reader: DatabaseReader, *, tenants: tuple[str, ...], users: tuple[str, ...]
    ) -> None:
        self._reader = reader
        self._tenants = tenants
        self._users = users

    def _authorized(self, trusted: TrustedContext) -> bool:
        return trusted.tenant_id in self._tenants and trusted.user_id in self._users

    async def describe(self, arguments: dict[str, Any], trusted: TrustedContext) -> ToolCallResult:
        if not self._authorized(trusted):
            return ToolCallResult(is_error=True, text="无权访问此数据源。")
        if arguments:
            return ToolCallResult(is_error=True, text="表结构查询不接受额外参数。")
        return ToolCallResult(structured=await self._reader.describe())

    async def query(self, arguments: dict[str, Any], trusted: TrustedContext) -> ToolCallResult:
        if not self._authorized(trusted):
            return ToolCallResult(is_error=True, text="无权访问此数据源。")
        try:
            query = DatabaseQuery.model_validate(arguments)
            result = await self._reader.query(query)
        except ValidationError:
            return ToolCallResult(
                is_error=True,
                text="查询参数无效。请先查看表结构，按参数化筛选、列名及聚合合同重新提交。",
            )
        except ValueError as exc:
            return ToolCallResult(is_error=True, text=str(exc))
        except TimeoutError:
            return ToolCallResult(is_error=True, text="查询超时，请缩小时间或筛选范围。")
        return ToolCallResult(structured=result)

    def package(self) -> ExtensionPackage:
        return ExtensionPackage(
            name="database",
            title="数据库查询与分析",
            version="1.0.0",
            description="查询已授权数据表，提供字段、只读筛选及分组统计。",
            tools=(
                RegisteredTool(
                    package="database",
                    descriptor=ToolDescriptor(
                        name="auramcp.database.describe",
                        description="先调用此工具获取可查询表的别名、字段、类型、注释和数值单位。",
                        input_schema={
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    ),
                    handler=self.describe,
                ),
                RegisteredTool(
                    package="database",
                    descriptor=ToolDescriptor(
                        name="auramcp.database.query",
                        description=(
                            "查询已授权表。table 使用 describe 返回的别名；"
                            "列、筛选、排序均用字段名。明细用 columns；"
                            "统计用 group_by 和 aggregates（count/sum/avg/min/max）。"
                            "filters 以 AND 组合，contains 为字面子串，不是 SQL 模式。"
                            "日期为 ISO 格式。金额按字段注释中的原单位返回，不擅自换算。"
                            "最多 200 行；优先用有索引的筛选和小时间范围。禁止传 SQL 或连接信息。"
                        ),
                        input_schema=DatabaseQuery.model_json_schema(),
                    ),
                    handler=self.query,
                ),
            ),
        )
