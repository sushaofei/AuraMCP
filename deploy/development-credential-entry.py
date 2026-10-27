"""Load a protected development credential map before the existing service runner."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> None:
    if os.environ.get("AURACLAW_DEPLOYMENT_PROFILE") != "development":
        raise SystemExit("This credential entrypoint is restricted to development")
    if sys.argv[1:] != ["/eval/run_service.py", "credential-proxy"]:
        raise SystemExit("Only the existing credential-proxy runner is supported")
    filename = os.environ["AURAMCP_CREDENTIAL_MAP_FILE"]
    path = Path(filename)
    if path.stat().st_size > 65536:
        raise SystemExit("Credential map exceeds the configured limit")
    additions = json.loads(path.read_text())
    values = json.loads(os.environ.get("AURACLAW_DEBUG_VAULT_SECRETS_JSON", "{}"))
    if not isinstance(additions, dict) or not isinstance(values, dict):
        raise SystemExit("Credential maps must be objects")
    for key, value in additions.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise SystemExit("Invalid credential reference entry")
        if key in values and values[key] != value:
            raise SystemExit("Existing credential reference must not be overwritten")
    values.update(additions)
    os.environ["AURACLAW_DEBUG_VAULT_SECRETS_JSON"] = json.dumps(values)
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])


if __name__ == "__main__":
    main()
