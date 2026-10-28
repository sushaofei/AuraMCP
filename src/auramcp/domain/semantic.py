from __future__ import annotations

from typing import Any, Protocol

from auramcp.contracts.identity import TrustedContext
from auramcp.contracts.semantic import Describe, Discover, SemanticQuery


class SemanticError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class SemanticReader(Protocol):
    async def discover(self, request: Discover, trusted: TrustedContext) -> dict[str, Any]: ...
    async def describe(self, request: Describe, trusted: TrustedContext) -> dict[str, Any]: ...
    async def query(self, request: SemanticQuery, trusted: TrustedContext) -> dict[str, Any]: ...
    async def aclose(self) -> None: ...
