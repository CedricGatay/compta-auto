from __future__ import annotations

import argparse
import json
import signal
import sys

import uvicorn

from .app import create_app
from .config import get_settings
from .db import Database
from .pipeline import AccountingPipeline
from .repositories import Repository


def main() -> None:
    parser = argparse.ArgumentParser(prog="compta-auto")
    subparsers = parser.add_subparsers(dest="command", required=True)

    web = subparsers.add_parser("web")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", default=8765, type=int)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--months", default=1, type=int)

    provider = subparsers.add_parser("add-provider")
    provider.add_argument("--vendor", required=True)
    provider.add_argument("--url", required=True)
    provider.add_argument("--notes", default="")

    inqom_explore = subparsers.add_parser("inqom-explore", help="Explore Inqom UI interactively")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "inqom-explore":
        from .inqom_uploader import explore_inqom_ui
        if not settings.inqom_email or not settings.inqom_password:
            print("Error: Set COMPTA_INQOM_EMAIL and COMPTA_INQOM_PASSWORD in .env")
            sys.exit(1)
        explore_inqom_ui(settings.inqom_email, settings.inqom_password)
        return

    db = Database(settings.db_path)
    db.init()

    if args.command == "web":
        # Force immediate exit on second CTRL+C
        original_sigint = signal.getsignal(signal.SIGINT)

        def _force_exit(*_args):
            sys.exit(0)

        def _first_sigint(*_args):
            signal.signal(signal.SIGINT, _force_exit)
            if callable(original_sigint) and original_sigint is not signal.SIG_DFL:
                original_sigint(*_args)
            else:
                raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _first_sigint)
        uvicorn.run(
            create_app(settings),
            host=args.host,
            port=args.port,
            timeout_graceful_shutdown=0,
        )
        return

    with db.connect() as conn:
        repo = Repository(conn)
        if args.command == "scan":
            summary = AccountingPipeline(settings, repo).run_mail_scan(months=args.months)
            print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
        elif args.command == "add-provider":
            task_id, created = repo.add_provider_task(
                args.vendor, args.url, None, "provider_manual_link", args.notes
            )
            print(json.dumps({"id": task_id, "created": created}, indent=2, sort_keys=True))
        conn.commit()


if __name__ == "__main__":
    main()

