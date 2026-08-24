from __future__ import annotations

from datetime import UTC, datetime

from auramcp.contracts.errors import ExtensionNotFoundError, VersionConflictError
from auramcp.contracts.extensions import CatalogSnapshot, ExtensionStatus
from auramcp.domain.catalog import publish_catalog
from auramcp.domain.ports import PlatformStore
from auramcp.extensions.registry import ExtensionRegistry


class CatalogService:
    def __init__(self, registry: ExtensionRegistry, store: PlatformStore) -> None:
        self._registry = registry
        self._store = store
        self._last_digest: str | None = None

    @property
    def registry(self) -> ExtensionRegistry:
        return self._registry

    async def snapshot(self, tenant_id: str) -> CatalogSnapshot:
        statuses = await self._store.get_statuses()
        snapshot = publish_catalog(self._registry.packages, statuses, tenant_id=tenant_id)
        if snapshot.digest != self._last_digest:
            await self._store.publish_catalog(snapshot.digest, len(snapshot.records))
            self._last_digest = snapshot.digest
        return snapshot

    async def list_packages(self) -> list[dict[str, str | int]]:
        items: list[dict[str, str | int]] = []
        for package in self._registry.packages:
            status, version = await self._store.get_status(package.name)
            items.append(
                {
                    "name": package.name,
                    "title": package.title,
                    "version": package.version,
                    "status": str(status),
                    "expected_version": version,
                }
            )
        return items

    async def set_status(
        self,
        name: str,
        status: ExtensionStatus,
        *,
        actor: str,
        command_id: str,
        expected_version: int,
    ) -> int:
        try:
            self._registry.get(name)
        except KeyError as exc:
            raise ExtensionNotFoundError(name) from exc
        try:
            return await self._store.set_status(
                name,
                status,
                actor=actor,
                command_id=command_id,
                expected_version=expected_version,
            )
        except VersionConflictError:
            raise

    async def audit(
        self,
        *,
        tenant_id: str,
        capability: str | None,
        method: str,
        digest: str | None,
        decision: str,
        outcome: str,
        latency_ms: int,
        invocation_id: str | None,
    ) -> None:
        await self._store.record_audit(
            occurred_at=datetime.now(UTC),
            tenant_id=tenant_id,
            capability=capability,
            method=method,
            digest=digest,
            decision=decision,
            outcome=outcome,
            latency_ms=latency_ms,
            invocation_id=invocation_id,
        )
