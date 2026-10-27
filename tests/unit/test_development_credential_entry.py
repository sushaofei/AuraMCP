from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest


def entry() -> dict[str, Any]:
    return runpy.run_path(str(Path(__file__).parents[2] / "deploy/development-credential-entry.py"))


def test_production_rejects_development_credential_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AURACLAW_DEPLOYMENT_PROFILE", "production")
    with pytest.raises(SystemExit, match="restricted to development"):
        entry()["main"]()


def test_credential_entry_preserves_other_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "credentials.json"
    source.write_text(json.dumps({"test/new": "test-value"}))
    monkeypatch.setenv("AURACLAW_DEPLOYMENT_PROFILE", "development")
    monkeypatch.setenv("AURAMCP_CREDENTIAL_MAP_FILE", str(source))
    monkeypatch.setenv("AURACLAW_DEBUG_VAULT_SECRETS_JSON", '{"test/old":"old-value"}')
    monkeypatch.setattr(sys, "argv", ["entry.py", "/eval/run_service.py", "credential-proxy"])
    module = entry()
    calls = []
    monkeypatch.setattr(module["os"], "execv", lambda *args: calls.append(args))
    module["main"]()
    values = json.loads(module["os"].environ["AURACLAW_DEBUG_VAULT_SECRETS_JSON"])
    assert values == {"test/old": "old-value", "test/new": "test-value"}
    assert calls[0][1][1:] == ["/eval/run_service.py", "credential-proxy"]


def test_credential_entry_rejects_overwriting_an_existing_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "credentials.json"
    source.write_text('{"test/ref":"new-value"}')
    monkeypatch.setenv("AURACLAW_DEPLOYMENT_PROFILE", "development")
    monkeypatch.setenv("AURAMCP_CREDENTIAL_MAP_FILE", str(source))
    monkeypatch.setenv("AURACLAW_DEBUG_VAULT_SECRETS_JSON", '{"test/ref":"old-value"}')
    monkeypatch.setattr(sys, "argv", ["entry.py", "/eval/run_service.py", "credential-proxy"])
    with pytest.raises(SystemExit, match="must not be overwritten"):
        entry()["main"]()
