from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from auramcp.contracts.base import ContractModel

MCP_PROTOCOL_VERSION = "2026-07-28"
MCP_JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
MCP_CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
MCP_CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
MCP_SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
MCP_AURACLAW_INVOCATION_ID_META_KEY = "io.auraclaw/invocationId"
MCP_AURACLAW_TENANT_ID_META_KEY = "io.auraclaw/tenantId"
MCP_AURACLAW_USER_ID_META_KEY = "io.auraclaw/userId"
MCP_AURACLAW_DEPT_ID_META_KEY = "io.auraclaw/deptId"

ALLOWED_MCP_METHODS = frozenset(
    {
        "server/discover",
        "ping",
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/templates/list",
        "resources/read",
        "prompts/list",
        "prompts/get",
    }
)


class McpJsonRpcRequest(ContractModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class McpJsonRpcError(ContractModel):
    code: int
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class McpJsonRpcResponse(ContractModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: dict[str, Any] | None = None
    error: McpJsonRpcError | None = None
