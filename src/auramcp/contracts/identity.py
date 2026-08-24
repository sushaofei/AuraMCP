from __future__ import annotations

from auramcp.contracts.base import ContractModel


class TrustedContext(ContractModel):
    tenant_id: str
    user_id: str | None = None
    dept_id: str | None = None
    session_id: str | None = None
    invocation_id: str | None = None
