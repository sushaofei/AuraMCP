from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from auramcp.admin.http import create_admin_router
from auramcp.catalog.service import CatalogService
from auramcp.contracts.extensions import ExtensionPackage
from auramcp.domain.database import DatabaseReader
from auramcp.domain.ports import PlatformStore
from auramcp.extensions.about import about_package
from auramcp.extensions.builtin import builtin_package
from auramcp.extensions.database import DatabaseExtension
from auramcp.extensions.ops import OpsExtension
from auramcp.extensions.registry import ExtensionRegistry
from auramcp.identity.guard import IdentityGuard
from auramcp.infrastructure.analytics import AnalyticsConfig, PostgresAnalytics
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
    database: DatabaseReader | None = None


async def build_runtime(settings: Settings) -> Runtime:
    store: PlatformStore
    if settings.platform_store == "memory":
        store = MemoryPlatformStore()
    else:
        store = await PostgresPlatformStore.connect(settings)
    packages: list[ExtensionPackage] = []
    ops = OpsExtension(store, lambda: tuple(packages))
    packages.extend((builtin_package(), about_package(), ops.package()))
    database = None
    if settings.analytics_config_file:
        try:
            config = AnalyticsConfig.model_validate_json(
                await asyncio.to_thread(Path(settings.analytics_config_file).read_bytes)
            )
            database = await PostgresAnalytics.connect(config)
            packages.append(
                DatabaseExtension(
                    database, tenants=config.allowed_tenants, users=config.allowed_users
                ).package()
            )
        except BaseException:
            await store.aclose()
            raise
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
        database=database,
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
            try:
                if runtime.database is not None:
                    await runtime.database.aclose()
            finally:
                await runtime.store.aclose()

    app = FastAPI(title="AuraMCP", version="0.1.0", lifespan=lifespan)
    app.include_router(create_mcp_router())
    app.include_router(create_admin_router())
    return app
