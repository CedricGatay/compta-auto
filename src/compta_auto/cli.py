from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

import uvicorn

from .app import create_app
from .config import get_settings
from .db import Database
from .inqom_upload import list_inqom_upload_candidates, stream_inqom_upload
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

    subparsers.add_parser("categorize")

    provider = subparsers.add_parser("add-provider")
    provider.add_argument("--vendor", required=True)
    provider.add_argument("--url", required=True)
    provider.add_argument("--notes", default="")

    inqom_explore = subparsers.add_parser("inqom-explore", help="Explore Inqom UI interactively")
    inqom_upload = subparsers.add_parser("inqom-upload", help="Upload ready documents to Inqom")
    inqom_upload.add_argument("--dry-run", action="store_true")
    inqom_upload.add_argument("--type", choices=["purchase", "sale", "all"], default="all")

    henrri = subparsers.add_parser("henrri-invoices", help="List invoices from Henrri")
    henrri.add_argument("--limit", type=int, default=50)
    henrri.add_argument("--from-date", default=None, help="Filter from date (YYYY-MM-DD)")
    henrri.add_argument("--to-date", default=None, help="Filter to date (YYYY-MM-DD)")
    henrri.add_argument(
        "--type", default="Invoice", dest="doc_type",
        help="Document type filter (Invoice, Quotation, CreditNote, all). Default: Invoice",
    )
    henrri.add_argument(
        "--download-pdf", default=None, metavar="DIR",
        help="Download PDFs for listed documents into this directory",
    )

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "inqom-explore":
        from .inqom_uploader import explore_inqom_ui
        if not settings.inqom_email or not settings.inqom_password:
            print("Error: Set COMPTA_INQOM_EMAIL and COMPTA_INQOM_PASSWORD in .env")
            sys.exit(1)
        explore_inqom_ui(settings.inqom_email, settings.inqom_password)
        return

    if args.command == "henrri-invoices":
        from .henrri_invoices import HenrriClient
        if not settings.henrri_client_id or not settings.henrri_client_secret:
            print("Error: Set COMPTA_HENRRI_CLIENT_ID and COMPTA_HENRRI_CLIENT_SECRET in .env")
            sys.exit(1)
        client = HenrriClient(settings.henrri_client_id, settings.henrri_client_secret, base_url=settings.henrri_base_url)
        doc_types = None if args.doc_type == "all" else [args.doc_type]
        result = client.list_documents(
            limit=args.limit,
            document_types=doc_types,
            from_date=args.from_date,
            to_date=args.to_date,
            sort_by="date",
            sort_order="descending",
        )
        elements = result.get("elements", [])
        if not elements:
            print("No documents found.")
        else:
            print(f"{'Number':<14} {'Date':<12} {'Type':<12} {'Customer':<28} {'HT':>10} {'TTC':>10}")
            print("-" * 90)
            for doc in elements:
                customer = doc.get("customer") or {}
                date_str = (doc.get("date") or "")[:10]
                cust_name = (customer.get("name") or "N/A")[:26]
                ht = f"{doc['priceBeforeTax']:.2f}" if doc.get("priceBeforeTax") is not None else "-"
                ttc = f"{doc['priceAfterTax']:.2f}" if doc.get("priceAfterTax") is not None else "-"
                doc_type = (doc.get("type") or "-")[:10]
                print(
                    f"{doc.get('identity') or '-':<14} {date_str:<12} {doc_type:<12} "
                    f"{cust_name:<28} {ht:>10} {ttc:>10}"
                )
            if args.download_pdf:
                pdf_dir = Path(args.download_pdf)
                print(f"\nDownloading PDFs to {pdf_dir}/...")
                for doc in elements:
                    doc_id = doc["id"]
                    identity = doc.get("identity") or f"doc-{doc_id}"
                    safe_name = identity.replace("/", "-").replace(" ", "_")
                    out_path = pdf_dir / f"{safe_name}.pdf"
                    try:
                        client.download_pdf(doc_id, out_path)
                        print(f"  ✓ {out_path}")
                    except Exception as e:
                        print(f"  ✗ {identity}: {e}", file=sys.stderr)
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
        elif args.command == "categorize":
            categorized = AccountingPipeline(settings, repo).categorize_uncategorized_documents()
            print(json.dumps({"categorized": categorized}, indent=2, sort_keys=True))
        elif args.command == "add-provider":
            task_id, created = repo.add_provider_task(
                args.vendor, args.url, None, "provider_manual_link", args.notes
            )
            print(json.dumps({"id": task_id, "created": created}, indent=2, sort_keys=True))
        elif args.command == "inqom-upload":
            documents = list_inqom_upload_candidates(repo, args.type)
            if not documents:
                print("No documents ready for Inqom upload.")
            else:
                print("Documents selected for Inqom upload:")
                for document in documents:
                    filename = document.get("final_filename") or Path(document["upload_path"]).name
                    print(
                        f"- #{document['id']} [{document['accounting_type']}] {filename} "
                        f"({document['status']}) -> {document['upload_path']}"
                    )

            if args.dry_run:
                print(f"Dry run complete: {len(documents)} document(s) would be uploaded.")
            elif documents:
                had_errors = False
                for event in stream_inqom_upload(repo, settings, documents):
                    event_type = event["type"]
                    if event_type == "status":
                        print(event["message"])
                    elif event_type == "progress":
                        print(event["message"])
                    elif event_type == "group_start":
                        print(
                            f"Uploading {event['count']} {event['accounting_type']} "
                            f"document(s) as {event['doc_type']}..."
                        )
                    elif event_type == "uploaded":
                        print(f"Uploaded #{event['document_id']} {event['file']} -> {event['status']}")
                    elif event_type == "error":
                        had_errors = True
                        print(f"Error: {event['error']}", file=sys.stderr)
                    elif event_type in {"group_done", "done"}:
                        if event["result"].get("errors"):
                            had_errors = True
                        print(json.dumps(event["result"], indent=2, sort_keys=True))

                if had_errors:
                    conn.commit()
                    sys.exit(1)
        conn.commit()


if __name__ == "__main__":
    main()
