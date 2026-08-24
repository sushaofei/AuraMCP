from __future__ import annotations

from pathlib import Path

import pytest

from auramcp.contracts.errors import CatalogConflictError
from auramcp.contracts.extensions import ExtensionPackage, RegisteredTool, ToolDescriptor
from auramcp.extensions.registry import ExtensionRegistry
from auramcp.infrastructure.settings import Settings


def test_source_tree_does_not_import_chaintower() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "auramcp"
    matches = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "chaintower" in text.casefold() or "auraclaw." in text:
            matches.append(str(path.relative_to(root.parent.parent)))
    assert matches == []


def test_duplicate_canonical_name_is_rejected() -> None:
    tool = RegisteredTool(
        package="dup",
        descriptor=ToolDescriptor(name="auramcp.health.ping"),
        handler=lambda arguments, trusted: None,
    )
    with pytest.raises(CatalogConflictError):
        ExtensionRegistry(
            (
                ExtensionPackage(name="a", title="a", version="1", tools=(tool,)),
                ExtensionPackage(name="b", title="b", version="1", tools=(tool,)),
            )
        )


def test_production_settings_require_tokens() -> None:
    with pytest.raises(ValueError, match="HANDS_WORKLOAD_TOKEN"):
        Settings(
            deployment_profile="production",
            allow_insecure_identity=False,
            hands_workload_token="",
            admin_token="admin",
            platform_store="memory",
        )
