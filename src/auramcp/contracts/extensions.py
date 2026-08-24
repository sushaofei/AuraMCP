from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import Field

from auramcp.contracts.base import ContractModel
from auramcp.contracts.identity import TrustedContext


class CapabilityKind(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    RESOURCE_TEMPLATE = "resource_template"
    PROMPT = "prompt"


class ExtensionStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    QUARANTINED = "quarantined"


class ToolDescriptor(ContractModel):
    name: str
    description: str = ""
    version: str = "1"
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    read_only: bool = True
    destructive: bool = False


class ResourceDescriptor(ContractModel):
    name: str
    uri: str | None = None
    uri_template: str | None = None
    title: str | None = None
    description: str | None = None
    mime_type: str | None = None


class PromptArgument(ContractModel):
    name: str
    title: str | None = None
    description: str | None = None
    required: bool = False


class PromptDescriptor(ContractModel):
    name: str
    title: str | None = None
    description: str | None = None
    arguments: tuple[PromptArgument, ...] = ()


class ResourceContents(ContractModel):
    uri: str
    mime_type: str | None = None
    text: str | None = None
    blob: str | None = None


class ToolCallResult(ContractModel):
    is_error: bool = False
    structured: dict[str, Any] = Field(default_factory=dict)
    text: str = ""


ToolHandler = Callable[[dict[str, Any], TrustedContext], Awaitable[ToolCallResult]]
ResourceReader = Callable[[str, TrustedContext], Awaitable[tuple[ResourceContents, ...]]]
PromptRenderer = Callable[[dict[str, str], TrustedContext], Awaitable[dict[str, Any]]]


class RegisteredTool(ContractModel):
    package: str
    descriptor: ToolDescriptor
    handler: Any


class RegisteredResource(ContractModel):
    package: str
    descriptor: ResourceDescriptor
    reader: Any
    tenant_ids: tuple[str, ...] = ()


class RegisteredResourceTemplate(ContractModel):
    package: str
    descriptor: ResourceDescriptor
    reader: Any
    tenant_ids: tuple[str, ...] = ()


class RegisteredPrompt(ContractModel):
    package: str
    descriptor: PromptDescriptor
    renderer: Any
    tenant_ids: tuple[str, ...] = ()


class ExtensionPackage(ContractModel):
    name: str
    title: str
    version: str
    description: str = ""
    tools: tuple[RegisteredTool, ...] = ()
    resources: tuple[RegisteredResource, ...] = ()
    resource_templates: tuple[RegisteredResourceTemplate, ...] = ()
    prompts: tuple[RegisteredPrompt, ...] = ()


class CapabilityRecord(ContractModel):
    capability_id: str
    kind: CapabilityKind
    package: str
    canonical_name: str
    version: str
    digest: str
    status: ExtensionStatus
    title: str = ""
    description: str = ""


class CatalogSnapshot(ContractModel):
    digest: str
    records: tuple[CapabilityRecord, ...]
    tools: tuple[RegisteredTool, ...]
    resources: tuple[RegisteredResource, ...]
    resource_templates: tuple[RegisteredResourceTemplate, ...]
    prompts: tuple[RegisteredPrompt, ...]
