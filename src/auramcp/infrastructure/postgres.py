from __future__ import annotations

from datetime import datetime
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]

from auramcp.contracts.errors import VersionConflictError
from auramcp.contracts.extensions import ExtensionStatus
from auramcp.infrastructure.settings import Settings

_MIGRATION_VERSION = "0001_platform_governance"
_MIGRATION_SQL = (
    Path(__file__).resolve().parents[3] / "migrations" / f"{_MIGRATION_VERSION}.sql"
).read_text(encoding="utf-8")


class PostgresPlatformStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, settings: Settings) -> PostgresPlatformStore:
        pool = await asyncpg.create_pool(dsn=settings.dsn, min_size=1, max_size=5)
        store = cls(pool)
        await store.migrate()
        return store

    async def migrate(self) -> None:
        sql = _MIGRATION_SQL
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                applied = await connection.fetchval(
                    "SELECT 1 FROM schema_migrations WHERE version = $1",
                    _MIGRATION_VERSION,
                )
                if applied:
                    return
                await connection.execute(sql)
                await connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES ($1)",
                    _MIGRATION_VERSION,
                )

    async def get_statuses(self) -> dict[str, ExtensionStatus]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch("SELECT name, status FROM extension_status")
        return {row["name"]: ExtensionStatus(row["status"]) for row in rows}

    async def get_status(self, name: str) -> tuple[ExtensionStatus, int]:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT status, expected_version FROM extension_status WHERE name = $1",
                name,
            )
        if row is None:
            return ExtensionStatus.ACTIVE, 1
        return ExtensionStatus(row["status"]), int(row["expected_version"])

    async def set_status(
        self,
        name: str,
        status: ExtensionStatus,
        *,
        actor: str,
        command_id: str,
        expected_version: int,
    ) -> int:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                existing = await connection.fetchrow(
                    "SELECT command_id, expected_version FROM extension_status WHERE name = $1",
                    name,
                )
                if existing is not None and existing["command_id"] == command_id:
                    return int(existing["expected_version"])
                current_version = 1 if existing is None else int(existing["expected_version"])
                if current_version != expected_version:
                    raise VersionConflictError(
                        f"expected version {expected_version} but found {current_version}"
                    )
                next_version = current_version + 1
                await connection.execute(
                    """
                    INSERT INTO extension_status (
                        name, status, expected_version, updated_by, command_id
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (name) DO UPDATE
                    SET status = EXCLUDED.status,
                        expected_version = EXCLUDED.expected_version,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now(),
                        command_id = EXCLUDED.command_id
                    """,
                    name,
                    status.value,
                    next_version,
                    actor,
                    command_id,
                )
                return next_version

    async def publish_catalog(self, digest: str, capability_count: int) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO catalog_publications (catalog_digest, capability_count)
                VALUES ($1, $2)
                """,
                digest,
                capability_count,
            )

    async def record_audit(
        self,
        *,
        occurred_at: datetime,
        tenant_id: str,
        capability: str | None,
        method: str,
        digest: str | None,
        decision: str,
        outcome: str,
        latency_ms: int,
        invocation_id: str | None,
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO invocation_audit (
                    occurred_at, tenant_id, capability, method, digest,
                    decision, outcome, latency_ms, invocation_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                occurred_at,
                tenant_id,
                capability,
                method,
                digest,
                decision,
                outcome,
                latency_ms,
                invocation_id,
            )

    async def ping(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute("SELECT 1")

    async def aclose(self) -> None:
        await self._pool.close()
