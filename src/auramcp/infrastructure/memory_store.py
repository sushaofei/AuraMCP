from __future__ import annotations

from datetime import UTC, datetime

from auramcp.contracts.errors import VersionConflictError
from auramcp.contracts.extensions import ExtensionStatus


class MemoryPlatformStore:
    def __init__(self) -> None:
        self._statuses: dict[str, tuple[ExtensionStatus, int]] = {}
        self._commands: set[str] = set()
        self.audits: list[dict[str, object]] = []
        self.publications: list[tuple[str, int]] = []

    async def get_statuses(self) -> dict[str, ExtensionStatus]:
        return {name: status for name, (status, _version) in self._statuses.items()}

    async def get_status(self, name: str) -> tuple[ExtensionStatus, int]:
        return self._statuses.get(name, (ExtensionStatus.ACTIVE, 1))

    async def set_status(
        self,
        name: str,
        status: ExtensionStatus,
        *,
        actor: str,
        command_id: str,
        expected_version: int,
    ) -> int:
        del actor
        current, version = self._statuses.get(name, (ExtensionStatus.ACTIVE, 1))
        if command_id in self._commands:
            return version
        if version != expected_version:
            raise VersionConflictError(
                f"expected version {expected_version} but found {version}"
            )
        next_version = version + 1
        self._statuses[name] = (status, next_version)
        self._commands.add(command_id)
        del current
        return next_version

    async def publish_catalog(self, digest: str, capability_count: int) -> None:
        self.publications.append((digest, capability_count))

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
        occurred = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        self.audits.append(
            {
                "occurred_at": occurred,
                "tenant_id": tenant_id,
                "capability": capability,
                "method": method,
                "digest": digest,
                "decision": decision,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "invocation_id": invocation_id,
            }
        )

    async def ping(self) -> None:
        return None

    async def aclose(self) -> None:
        return None
