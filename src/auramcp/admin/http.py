from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auramcp.contracts.errors import ExtensionNotFoundError, VersionConflictError
from auramcp.contracts.extensions import ExtensionStatus


class ExtensionWriteRequest(BaseModel):
    actor: str = Field(min_length=1)
    command_id: str = Field(min_length=1, alias="commandId")
    expected_version: int = Field(ge=1, alias="expectedVersion")

    model_config = {"populate_by_name": True}


def create_admin_router() -> APIRouter:
    router = APIRouter(prefix="/internal/v1")

    @router.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        runtime = request.app.state.runtime
        await runtime.store.ping()
        packages = await runtime.catalog.list_packages()
        runtime.metrics.counters["catalog_size"] = sum(
            1 for item in packages if item["status"] == "active"
        )
        return {"status": "ok", "packages": len(packages)}

    @router.get("/metrics")
    async def metrics_endpoint(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _authorize(request, authorization)
        return dict(request.app.state.runtime.metrics.snapshot())

    @router.get("/catalog")
    async def get_catalog(
        request: Request,
        authorization: str | None = Header(default=None),
        x_tenant_id: str | None = Header(default=None, alias="X-CT-Tenant-ID"),
    ) -> dict[str, Any]:
        _authorize(request, authorization)
        runtime = request.app.state.runtime
        tenant_id = x_tenant_id or "local"
        snapshot = await runtime.catalog.snapshot(tenant_id)
        packages = await runtime.catalog.list_packages()
        return {
            "digest": snapshot.digest,
            "packages": packages,
            "capabilities": [item.model_dump(mode="json") for item in snapshot.records],
        }

    @router.post("/extensions/{name}/disable")
    async def disable_extension(
        name: str,
        body: ExtensionWriteRequest,
        request: Request,
    ) -> dict[str, Any]:
        return await _set_status(name, ExtensionStatus.DISABLED, body, request)

    @router.post("/extensions/{name}/enable")
    async def enable_extension(
        name: str,
        body: ExtensionWriteRequest,
        request: Request,
    ) -> dict[str, Any]:
        return await _set_status(name, ExtensionStatus.ACTIVE, body, request)

    return router


async def _set_status(
    name: str,
    status: ExtensionStatus,
    body: ExtensionWriteRequest,
    request: Request,
) -> dict[str, Any]:
    _authorize(request, request.headers.get("authorization"))
    catalog = request.app.state.runtime.catalog
    try:
        version = await catalog.set_status(
            name,
            status,
            actor=body.actor,
            command_id=body.command_id,
            expected_version=body.expected_version,
        )
    except ExtensionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"extension {exc.name} not found") from exc
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return {"name": name, "status": status.value, "expectedVersion": version}


def _authorize(request: Request, authorization: str | None) -> None:
    settings = request.app.state.runtime.settings
    if settings.allow_insecure_identity and not settings.admin_token:
        return
    token = _bearer(authorization)
    if (
        not settings.admin_token
        or token is None
        or not hmac.compare_digest(token, settings.admin_token)
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


def _bearer(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, remainder = authorization.partition(" ")
    if scheme.casefold() != "bearer":
        return None
    return remainder.strip() or None
