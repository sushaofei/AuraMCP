from __future__ import annotations

from datetime import datetime
from typing import Protocol

from auramcp.contracts.extensions import ExtensionStatus


class PlatformStore(Protocol):
    async def get_statuses(self) -> dict[str, ExtensionStatus]: ...

    async def get_status(self, name: str) -> tuple[ExtensionStatus, int]: ...

    async def set_status(
        self,
        name: str,
        status: ExtensionStatus,
        *,
        actor: str,
        command_id: str,
        expected_version: int,
    ) -> int: ...

    async def publish_catalog(self, digest: str, capability_count: int) -> None: ...

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
    ) -> None: ...

    async def ping(self) -> None: ...

    async def aclose(self) -> None: ...
