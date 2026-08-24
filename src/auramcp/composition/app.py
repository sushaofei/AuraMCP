from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from auramcp.admin.http import create_admin_router
from auramcp.catalog.service import CatalogService
from auramcp.contracts.extensions import ExtensionPackage
from auramcp.domain.ports import PlatformStore
from auramcp.extensions.builtin import builtin_package
from auramcp.extensions.ops import OpsExtension
from auramcp.extensions.registry import ExtensionRegistry
from auramcp.identity.guard import IdentityGuard
from auramcp.infrastructure.memory_store import MemoryPlatformStore
from auramcp.infrastructure.postgres import PostgresPlatformStore
from auramcp.infrastructure.settings import Settings
from auramcp.mcp.front_door import McpFrontDoor
from auramcp.mcp.http import create_mcp_router
from auramcp.observability.metrics import Metrics


@dataclass
class Runtime:
    settings: Settings
    store: PlatformStore
    catalog: CatalogService
    identity: IdentityGuard
    metrics: Metrics
    front_door: McpFrontDoor


async def build_runtime(settings: Settings) -> Runtime:
    store: PlatformStore
    if settings.platform_store == "memory":
        store = MemoryPlatformStore()
    else:
        store = await PostgresPlatformStore.connect(settings)
    packages: list[ExtensionPackage] = []
    ops = OpsExtension(store, lambda: tuple(packages))
    packages.extend((builtin_package(), ops.package()))
    registry = ExtensionRegistry(tuple(packages))
    catalog = CatalogService(registry, store)
    identity = IdentityGuard(
        workload_token=settings.hands_workload_token,
        deployment_profile=settings.deployment_profile,
        allow_insecure=settings.allow_insecure_identity,
    )
    metrics = Metrics()
    front_door = McpFrontDoor(
        catalog,
        metrics,
        page_size=settings.page_size,
        max_response_bytes=settings.max_response_bytes,
    )
    return Runtime(
        settings=settings,
        store=store,
        catalog=catalog,
        identity=identity,
        metrics=metrics,
        front_door=front_door,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = await build_runtime(resolved)
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.store.aclose()

    app = FastAPI(title="AuraMCP", version="0.1.0", lifespan=lifespan)
    app.include_router(create_mcp_router())
    app.include_router(create_admin_router())
    return app
