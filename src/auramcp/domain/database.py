from __future__ import annotations

from typing import Any, Protocol

from auramcp.contracts.database import DatabaseQuery


class DatabaseReader(Protocol):
    async def describe(self) -> dict[str, Any]: ...

    async def query(self, query: DatabaseQuery) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...
