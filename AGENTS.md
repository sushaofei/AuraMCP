# AGENTS.md

AuraMCP is a standard MCP `2026-07-28` Server and an AuraClaw
extension service. Production identity stays AuraClaw Hands
workload + trusted context. Architecture tracking is
[GitHub Issue #1](https://github.com/sushaofei/AuraMCP/issues/1).

## Commands

```bash
uv sync --extra dev
uv run auramcp run
uv run pytest
uv run ruff check .
uv run mypy src/auramcp
uv run lint-imports
```

## Architecture rules

- `contracts` and `domain` contain no FastAPI or infrastructure imports.
- Entrypoints call `composition`; `mcp`, `admin`, and extensions never import `composition`.
- AuraMCP must not import AuraClaw or chaintower packages.
- `AURAMCP_DB_*` is the platform governance store only. Capability data uses a
  separate configuration when an extension is implemented.
- Relative imports are not used across top-level modules; import through `auramcp.*`.
- Never commit `.env`, secrets, virtualenvs or caches.
