from __future__ import annotations

import argparse
import asyncio
import json

from trend_harvester.config import get_settings
from trend_harvester.db import SessionLocal
from trend_harvester.migrations.runner import run_migrations
from trend_harvester.schemas import RunStartRequest
from trend_harvester.services.channel_metadata import ChannelMetadataService
from trend_harvester.services.harvester import harvester_service


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trend-harvester")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="run SQLite migrations")
    refresh = sub.add_parser("refresh-channel-metadata", help="refresh cached YouTube channel metadata")
    refresh.add_argument("--force", action="store_true")

    run = sub.add_parser("run", help="start and wait for one harvest run")
    run.add_argument("--size", choices=["small", "medium", "large"], default="small")
    run.add_argument("--region", default="US")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.cmd == "migrate":
        run_migrations()
        print("migrations applied")
        return

    if args.cmd == "run":
        run_migrations()
        payload = RunStartRequest(limits={"size": args.size}, region=args.region)
        with SessionLocal() as db:
            run_id = harvester_service.start_run(db, payload)
        print(json.dumps({"run_id": run_id}))

        async def _wait() -> None:
            while harvester_service.is_running(run_id):
                await asyncio.sleep(0.5)

        asyncio.run(_wait())
        print("run completed")
        return

    if args.cmd == "refresh-channel-metadata":
        run_migrations()

        async def _refresh() -> None:
            service = ChannelMetadataService(get_settings())
            with SessionLocal() as db:
                payload = await service.refresh_all(db, force=bool(args.force))
            print(json.dumps({"channels": payload}, ensure_ascii=True))

        asyncio.run(_refresh())


if __name__ == "__main__":
    main()
