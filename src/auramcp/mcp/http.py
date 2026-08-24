from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from auramcp.contracts.errors import IdentityConflictError, IdentityDeniedError
from auramcp.contracts.mcp import MCP_PROTOCOL_VERSION
from auramcp.mcp.front_door import McpProtocolError, jsonrpc_error, jsonrpc_result, parse_jsonrpc


def create_mcp_router() -> APIRouter:
    router = APIRouter()

    @router.post("/mcp")
    async def mcp_endpoint(request: Request) -> Response:
        runtime = request.app.state.runtime
        raw = await request.body()
        headers = _normalized_headers(request.headers)
        try:
            payload = parse_jsonrpc(raw)
        except McpProtocolError as exc:
            return JSONResponse(jsonrpc_error(exc.code, exc.message, None), status_code=200)
        if payload.method.startswith("notifications/"):
            return Response(status_code=204)
        try:
            trusted = runtime.identity.authenticate(
                authorization=request.headers.get("authorization"),
                headers=headers,
                params=payload.params,
                method=payload.method,
                require_modern_meta=True,
            )
        except IdentityDeniedError as exc:
            runtime.metrics.increment("auth_denied")
            return JSONResponse(
                {"error": {"code": "unauthorized", "message": exc.message}},
                status_code=401,
            )
        except IdentityConflictError as exc:
            runtime.metrics.increment("tenant_mismatch")
            return JSONResponse(
                {"error": {"code": "forbidden", "message": exc.message}},
                status_code=403,
            )
        try:
            result = await runtime.front_door.dispatch(payload, trusted, headers)
        except McpProtocolError as exc:
            return JSONResponse(jsonrpc_error(exc.code, exc.message, payload.id))
        return JSONResponse(
            jsonrpc_result(result, payload.id),
            headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION},
        )

    return router


def _normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}
