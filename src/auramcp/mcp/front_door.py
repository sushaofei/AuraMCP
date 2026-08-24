from __future__ import annotations

import base64
import json
import time
from collections.abc import Mapping
from typing import Any

from auramcp.catalog.service import CatalogService
from auramcp.contracts.errors import IdentityConflictError
from auramcp.contracts.extensions import (
    CatalogSnapshot,
    RegisteredPrompt,
    RegisteredResource,
    RegisteredResourceTemplate,
    RegisteredTool,
    ToolCallResult,
)
from auramcp.contracts.identity import TrustedContext
from auramcp.contracts.mcp import ALLOWED_MCP_METHODS, MCP_PROTOCOL_VERSION, McpJsonRpcRequest
from auramcp.domain.acl import arguments_identity_conflicts
from auramcp.observability.metrics import Metrics

_JSONRPC_PARSE = -32700
_JSONRPC_INVALID_REQUEST = -32600
_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_INVALID_PARAMS = -32602
_JSONRPC_INTERNAL = -32603
_JSONRPC_APP = -32000


class McpProtocolError(Exception):
    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class McpFrontDoor:
    def __init__(
        self,
        catalog: CatalogService,
        metrics: Metrics,
        *,
        page_size: int,
        max_response_bytes: int,
    ) -> None:
        self._catalog = catalog
        self._metrics = metrics
        self._page_size = page_size
        self._max_response_bytes = max_response_bytes

    async def dispatch(
        self,
        request: McpJsonRpcRequest,
        trusted: TrustedContext,
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        capability: str | None = None
        decision = "allow"
        outcome = "success"
        digest: str | None = None
        try:
            _validate_routing_headers(request, headers)
            if request.method not in ALLOWED_MCP_METHODS:
                raise McpProtocolError(_JSONRPC_METHOD_NOT_FOUND, "method not found")
            snapshot = await self._catalog.snapshot(trusted.tenant_id)
            digest = snapshot.digest
            result = await self._handle(request, trusted, snapshot)
            capability = _capability_name(request)
            encoded = json.dumps(result, separators=(",", ":")).encode()
            if len(encoded) > self._max_response_bytes:
                self._metrics.increment("response_bytes_rejected")
                raise McpProtocolError(_JSONRPC_APP, "response exceeds the configured limit")
            return result
        except IdentityConflictError as exc:
            decision = "deny"
            outcome = "conflict"
            self._metrics.increment("tenant_mismatch")
            raise McpProtocolError(_JSONRPC_APP, exc.message) from exc
        except McpProtocolError as exc:
            decision = "deny" if exc.code in {_JSONRPC_APP, _JSONRPC_INVALID_PARAMS} else decision
            outcome = "error"
            if "not found" in exc.message:
                self._metrics.increment("handler_error_rate")
            raise
        except Exception:
            decision = "deny"
            outcome = "error"
            self._metrics.increment("handler_error_rate")
            raise McpProtocolError(_JSONRPC_INTERNAL, "internal error") from None
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            self._metrics.observe_ms("mcp_call_latency", latency_ms)
            if request.method == "server/discover":
                self._metrics.observe_ms("mcp_discover_latency", latency_ms)
            await self._catalog.audit(
                tenant_id=trusted.tenant_id,
                capability=capability,
                method=request.method,
                digest=digest,
                decision=decision,
                outcome=outcome,
                latency_ms=latency_ms,
                invocation_id=trusted.invocation_id,
            )

    async def _handle(
        self,
        request: McpJsonRpcRequest,
        trusted: TrustedContext,
        snapshot: CatalogSnapshot,
    ) -> dict[str, Any]:
        method = request.method
        params = request.params
        if method == "server/discover":
            return _discover(snapshot)
        if method == "ping":
            return {}
        if method == "tools/list":
            return _page(
                [_tool_payload(item) for item in snapshot.tools],
                params,
                self._page_size,
                key="tools",
            )
        if method == "resources/list":
            return _page(
                [_resource_payload(item) for item in snapshot.resources],
                params,
                self._page_size,
                key="resources",
            )
        if method == "resources/templates/list":
            return _page(
                [_template_payload(item) for item in snapshot.resource_templates],
                params,
                self._page_size,
                key="resourceTemplates",
            )
        if method == "prompts/list":
            return _page(
                [_prompt_payload(item) for item in snapshot.prompts],
                params,
                self._page_size,
                key="prompts",
            )
        if method == "tools/call":
            return await self._call_tool(params, trusted, snapshot)
        if method == "resources/read":
            return await self._read_resource(params, trusted, snapshot)
        if method == "prompts/get":
            return await self._get_prompt(params, trusted, snapshot)
        raise McpProtocolError(_JSONRPC_METHOD_NOT_FOUND, "method not found")

    async def _call_tool(
        self,
        params: Mapping[str, Any],
        trusted: TrustedContext,
        snapshot: CatalogSnapshot,
    ) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise McpProtocolError(_JSONRPC_INVALID_PARAMS, "tool name is required")
        if not isinstance(arguments, dict):
            raise McpProtocolError(_JSONRPC_INVALID_PARAMS, "tool arguments must be an object")
        arguments_identity_conflicts(arguments, trusted)
        tool = next((item for item in snapshot.tools if item.descriptor.name == name), None)
        if tool is None:
            raise McpProtocolError(_JSONRPC_APP, "tool not found")
        missing = _missing_required(tool.descriptor.input_schema, arguments)
        if missing:
            return _tool_error(f"missing required argument: {missing}")
        result = await tool.handler(arguments, trusted)
        if not isinstance(result, ToolCallResult):
            raise McpProtocolError(_JSONRPC_INTERNAL, "tool handler returned an invalid result")
        if result.is_error:
            return _tool_error(result.text or "tool execution error")
        payload: dict[str, Any] = {
            "content": [{"type": "text", "text": result.text or json.dumps(result.structured)}],
            "isError": False,
        }
        if result.structured:
            payload["structuredContent"] = result.structured
        return payload

    async def _read_resource(
        self,
        params: Mapping[str, Any],
        trusted: TrustedContext,
        snapshot: CatalogSnapshot,
    ) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri:
            raise McpProtocolError(_JSONRPC_INVALID_PARAMS, "resource uri is required")
        resource = next(
            (item for item in snapshot.resources if item.descriptor.uri == uri),
            None,
        )
        reader = resource.reader if resource is not None else None
        if reader is None:
            for template in snapshot.resource_templates:
                if _template_matches(template, uri):
                    reader = template.reader
                    break
        if reader is None:
            raise McpProtocolError(_JSONRPC_APP, "resource not found")
        contents = await reader(uri, trusted)
        return {
            "contents": [
                {
                    "uri": item.uri,
                    "mimeType": item.mime_type,
                    **({"text": item.text} if item.text is not None else {}),
                    **({"blob": item.blob} if item.blob is not None else {}),
                }
                for item in contents
            ]
        }

    async def _get_prompt(
        self,
        params: Mapping[str, Any],
        trusted: TrustedContext,
        snapshot: CatalogSnapshot,
    ) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise McpProtocolError(_JSONRPC_INVALID_PARAMS, "prompt name is required")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise McpProtocolError(_JSONRPC_INVALID_PARAMS, "prompt arguments must be an object")
        prompt = next(
            (item for item in snapshot.prompts if item.descriptor.name == name),
            None,
        )
        if prompt is None:
            raise McpProtocolError(_JSONRPC_APP, "prompt not found")
        rendered = await prompt.renderer(
            {str(key): str(value) for key, value in arguments.items()},
            trusted,
        )
        if not isinstance(rendered, dict):
            raise McpProtocolError(_JSONRPC_INTERNAL, "prompt renderer returned an invalid result")
        return dict(rendered)


def parse_jsonrpc(raw: bytes) -> McpJsonRpcRequest:
    try:
        payload = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise McpProtocolError(_JSONRPC_PARSE, "parse error") from exc
    if not isinstance(payload, dict):
        raise McpProtocolError(_JSONRPC_INVALID_REQUEST, "invalid request")
    try:
        return McpJsonRpcRequest.model_validate(payload)
    except Exception as exc:
        raise McpProtocolError(_JSONRPC_INVALID_REQUEST, "invalid request") from exc


def jsonrpc_error(code: int, message: str, request_id: str | int | None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def jsonrpc_result(result: dict[str, Any], request_id: str | int | None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _discover(snapshot: CatalogSnapshot) -> dict[str, Any]:
    return {
        "serverInfo": {"name": "auramcp", "version": "0.1.0"},
        "supportedVersions": [MCP_PROTOCOL_VERSION],
        "capabilities": {
            "tools": {},
            "resources": {},
            "prompts": {},
        },
        "catalogDigest": snapshot.digest,
    }


def _tool_payload(item: RegisteredTool) -> dict[str, Any]:
    descriptor = item.descriptor
    return {
        "name": descriptor.name,
        "description": descriptor.description,
        "inputSchema": descriptor.input_schema,
        "outputSchema": descriptor.output_schema,
        "annotations": {
            "readOnlyHint": descriptor.read_only,
            "destructiveHint": descriptor.destructive,
        },
        "_meta": {"auraclaw": {"version": descriptor.version}},
    }


def _resource_payload(item: RegisteredResource) -> dict[str, Any]:
    descriptor = item.descriptor
    return {
        "uri": descriptor.uri,
        "name": descriptor.name,
        "title": descriptor.title,
        "description": descriptor.description,
        "mimeType": descriptor.mime_type,
    }


def _template_payload(item: RegisteredResourceTemplate) -> dict[str, Any]:
    descriptor = item.descriptor
    return {
        "uriTemplate": descriptor.uri_template,
        "name": descriptor.name,
        "title": descriptor.title,
        "description": descriptor.description,
        "mimeType": descriptor.mime_type,
    }


def _prompt_payload(item: RegisteredPrompt) -> dict[str, Any]:
    descriptor = item.descriptor
    return {
        "name": descriptor.name,
        "title": descriptor.title,
        "description": descriptor.description,
        "arguments": [
            {
                "name": argument.name,
                "title": argument.title,
                "description": argument.description,
                "required": argument.required,
            }
            for argument in descriptor.arguments
        ],
    }


def _page(
    items: list[dict[str, Any]],
    params: Mapping[str, Any],
    page_size: int,
    *,
    key: str,
) -> dict[str, Any]:
    cursor = params.get("cursor")
    offset = 0
    if cursor is not None:
        try:
            offset = int(base64.urlsafe_b64decode(str(cursor) + "==").decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise McpProtocolError(_JSONRPC_INVALID_PARAMS, "invalid cursor") from exc
    page = items[offset : offset + page_size]
    payload: dict[str, Any] = {key: page}
    nxt = offset + page_size
    if nxt < len(items):
        payload["nextCursor"] = base64.urlsafe_b64encode(str(nxt).encode()).decode()
    return payload


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _missing_required(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> str | None:
    required = schema.get("required", [])
    if not isinstance(required, list):
        return None
    for name in required:
        if not isinstance(name, str) or name not in arguments:
            return str(name)
    return None


def _template_matches(template: RegisteredResourceTemplate, uri: str) -> bool:
    pattern = template.descriptor.uri_template or ""
    if "{name}" in pattern:
        prefix, _, suffix = pattern.partition("{name}")
        return uri.startswith(prefix) and uri.endswith(suffix) and uri != pattern
    return False


def _capability_name(request: McpJsonRpcRequest) -> str | None:
    key = {
        "tools/call": "name",
        "prompts/get": "name",
        "resources/read": "uri",
    }.get(request.method)
    if key is None:
        return None
    value = request.params.get(key)
    return str(value) if value is not None else None


def _validate_routing_headers(request: McpJsonRpcRequest, headers: Mapping[str, str]) -> None:
    protocol = headers.get("mcp-protocol-version")
    if protocol is not None and protocol != MCP_PROTOCOL_VERSION:
        raise McpProtocolError(_JSONRPC_INVALID_REQUEST, "unsupported MCP protocol version")
    method_header = headers.get("mcp-method")
    if method_header is not None and method_header != request.method:
        raise McpProtocolError(_JSONRPC_INVALID_REQUEST, "Mcp-Method does not match request")
    name_header = headers.get("mcp-name")
    expected = _capability_name(request)
    if name_header is not None and expected is not None and name_header != expected:
        raise McpProtocolError(_JSONRPC_INVALID_REQUEST, "Mcp-Name does not match request")
