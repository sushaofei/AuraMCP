from __future__ import annotations

from typing import Any

from auramcp.contracts.extensions import (
    ExtensionPackage,
    PromptArgument,
    PromptDescriptor,
    RegisteredPrompt,
    RegisteredResource,
    RegisteredTool,
    ResourceContents,
    ResourceDescriptor,
    ToolCallResult,
    ToolDescriptor,
)
from auramcp.contracts.identity import TrustedContext


async def ping(_arguments: dict[str, Any], trusted: TrustedContext) -> ToolCallResult:
    del trusted
    return ToolCallResult(structured={"ok": True, "service": "auramcp"}, text="pong")


async def echo(arguments: dict[str, Any], trusted: TrustedContext) -> ToolCallResult:
    message = arguments.get("message")
    if not isinstance(message, str) or not message:
        return ToolCallResult(is_error=True, text="message is required")
    echoed = {"echo": message, "tenant": trusted.tenant_id}
    return ToolCallResult(structured=echoed, text=message)


async def read_about(uri: str, trusted: TrustedContext) -> tuple[ResourceContents, ...]:
    del trusted
    return (
        ResourceContents(
            uri=uri,
            mime_type="text/plain",
            text=(
                "AuraMCP is an AuraClaw extension service. It hosts extra Tools, "
                "Resources, and Prompts. It does not implement task facts, approval, "
                "or user identity."
            ),
        ),
    )


async def render_usage(arguments: dict[str, str], trusted: TrustedContext) -> dict[str, Any]:
    task = arguments.get("task") or "the current AuraClaw task"
    return {
        "description": "How to use AuraMCP extensions from AuraClaw",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        f"Use only auramcp.* capabilities for {task} in tenant "
                        f"{trusted.tenant_id}. Do not invent server URLs or secrets."
                    ),
                },
            }
        ],
    }


def builtin_package() -> ExtensionPackage:
    return ExtensionPackage(
        name="builtin",
        title="AuraMCP Builtin",
        version="1.0.0",
        description="Health, echo, and contract-test capabilities",
        tools=(
            RegisteredTool(
                package="builtin",
                descriptor=ToolDescriptor(
                    name="auramcp.health.ping",
                    description="Return extension service liveness",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "ok": {"type": "boolean"},
                            "service": {"type": "string"},
                        },
                    },
                    read_only=True,
                ),
                handler=ping,
            ),
            RegisteredTool(
                package="builtin",
                descriptor=ToolDescriptor(
                    name="auramcp.example.echo",
                    description="Echo a message for contract tests",
                    input_schema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                        "additionalProperties": False,
                    },
                    output_schema={
                        "type": "object",
                        "properties": {
                            "echo": {"type": "string"},
                            "tenant": {"type": "string"},
                        },
                    },
                    read_only=True,
                ),
                handler=echo,
            ),
        ),
        resources=(
            RegisteredResource(
                package="builtin",
                descriptor=ResourceDescriptor(
                    name="about",
                    uri="auramcp://builtin/about",
                    title="About AuraMCP",
                    mime_type="text/plain",
                ),
                reader=read_about,
            ),
        ),
        prompts=(
            RegisteredPrompt(
                package="builtin",
                descriptor=PromptDescriptor(
                    name="auramcp.example.usage",
                    title="AuraMCP usage",
                    description="Prompt template for using AuraMCP extensions",
                    arguments=(
                        PromptArgument(
                            name="task",
                            description="Current AuraClaw task",
                            required=False,
                        ),
                    ),
                ),
                renderer=render_usage,
            ),
        ),
    )
