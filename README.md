# AuraMCP

AuraMCP is a **standard MCP `2026-07-28` Server** that hosts extra Tools, Resources, and Prompts. AuraClaw Action Hands connects to it with a standard MCP client.

Production identity and access stay AuraClaw-specific: Hands workload plus trusted context. Runtime still holds only `AURACLAW_HANDS_URL`.

It is a separate project from chaintower: independently versioned, deployed, and evolved. AuraMCP does not adapt, federate, or depend on chaintower.

## Run

```bash
uv sync --extra dev
cp .env.example .env   # fill AURAMCP_DB_* ; never commit .env
uv run auramcp run
```

Default listen address is `127.0.0.1:8020`.

- AuraClaw Hands calls `POST /mcp` (MCP `2026-07-28`).
- Admin: `GET /internal/v1/health`, `GET /internal/v1/catalog`, enable/disable extensions.

## Persistence

`AURAMCP_DB_*` is the **platform governance database** (extension status, catalog publications, invocation audit). Create the database first (`CREATE DATABASE auramcp;`) and set `AURAMCP_DB_NAME`. Then:

```bash
uv run auramcp migrate
uv run auramcp run
```

Tool / Resource / Prompt **capability data must not** use this database. Configure a separate store when implementing that capability.

## Add an extension

See [docs/扩展包开发.md](docs/扩展包开发.md). AuraClaw registration is [docs/AuraClaw 接入.md](docs/AuraClaw%20接入.md).

## Check

```bash
uv run pytest
uv run ruff check .
uv run mypy src/auramcp
uv run lint-imports
```
