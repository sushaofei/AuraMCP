from __future__ import annotations

import argparse

import uvicorn

from auramcp.infrastructure.settings import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="auramcp")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the AuraMCP extension service")
    run.add_argument("--host")
    run.add_argument("--port", type=int)
    sub.add_parser("migrate", help="Apply platform governance migrations")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "migrate":
        import asyncio

        from auramcp.infrastructure.postgres import PostgresPlatformStore

        async def _migrate() -> None:
            store = await PostgresPlatformStore.connect(settings)
            await store.aclose()

        asyncio.run(_migrate())
        return
    uvicorn.run(
        "auramcp.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_level=settings.log_level.lower(),
    )
