from __future__ import annotations

from typing import Any

from auramcp.contracts.extensions import (
    ExtensionPackage,
    RegisteredTool,
    ToolCallResult,
    ToolDescriptor,
)
from auramcp.contracts.identity import TrustedContext

AURACLAW_INTRO_TEXT = (
    "AuraClaw 是一个遵循 Managed Agent 架构的纯 Python 后端。"
    "它不把常驻 Agent 进程当作系统本身，而是把分钟级、小时级甚至需要人工审批的长期任务，"
    "建模为由持久事实、派生视图、运行时控制、Agent Runtime、工具执行和交付平面共同组成的"
    "受管分布式系统。\n\n"
    "核心命题是：Agent 是可替换的计算单元；任务是不可丢失的业务实体。"
    "「Managed」指的是由系统基础设施负责任务生命周期、状态、协作、安全、资源调度、"
    "失败恢复和结果交付，而不是去管理 Prompt。\n\n"
    "设计坚持三重外化。状态外化为记忆：Canonical Session Event Log 是唯一业务事实源，"
    "Projection 是可随时重建的查询副本。交互外化为协议：跨边界调用走 Command/Event 契约"
    "与 Gateway，身份与密钥不进入 Runtime。经验外化为技能：流程化 know-how 进入 Role Contract、"
    "Tool Gateway、MCP 扩展和 Skill Package。\n\n"
    "关键边界包括：Coordinator 负责语义拆分，Orchestrator 只调度资源；"
    "Runtime 状态不直接改写 Session 业务事实；Runtime Event 流不是结果交付保证，"
    "完成通知由持久 Outbox 驱动；Model、Tool、Credential 一律经 Gateway 访问，"
    "Agent Runtime 永不读取真实凭证。网页断线不会取消任务，重连可恢复可见事件。"
)

AURACLAW_TAGLINE = "Agent 是可替换的计算单元；任务是不可丢失的业务实体。"


async def introduce_auraclaw(
    _arguments: dict[str, Any],
    trusted: TrustedContext,
) -> ToolCallResult:
    del trusted
    return ToolCallResult(
        structured={
            "name": "AuraClaw",
            "tagline": AURACLAW_TAGLINE,
            "description": AURACLAW_INTRO_TEXT,
        },
        text=AURACLAW_INTRO_TEXT,
    )


def about_package() -> ExtensionPackage:
    return ExtensionPackage(
        name="about",
        title="AuraClaw about",
        version="1.0.0",
        description="Fixed introductions for AuraClaw",
        tools=(
            RegisteredTool(
                package="about",
                descriptor=ToolDescriptor(
                    name="auramcp.about.auraclaw",
                    description="Return a fixed introduction of AuraClaw",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "tagline": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "tagline", "description"],
                    },
                    read_only=True,
                ),
                handler=introduce_auraclaw,
            ),
        ),
    )
