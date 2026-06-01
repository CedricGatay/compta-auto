#!/usr/bin/env python3
"""Fetch Spotify invoices/receipts from the order history page.

Requires the `sp_dc` cookie from an authenticated Spotify session.
Set it via environment variable SPOTIFY_SP_DC or pass --sp-dc.

Usage:
    python fetch_invoices.py --output-dir ./invoices
    python fetch_invoices.py --sp-dc "AQXYZ..." --output-dir ./invoices
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import urllib.request
import urllib.error

BASE_URL = "https://www.spotify.com"
ORDER_HISTORY_URL = "https://www.spotify.com/fr/account/order-history/subscription/"

# French month abbreviations used in formattedSoldAt
FRENCH_MONTHS: dict[str, str] = {
    "janv.": "01", "févr.": "02", "mars": "03", "avr.": "04",
    "mai": "05", "juin": "06", "juil.": "07", "août": "08",
    "sept.": "09", "oct.": "10", "nov.": "11", "déc.": "12",
}


def build_headers(sp_dc: str, accept: str = "text/html") -> dict[str, str]:
    return {
        "Cookie": f"sp_dc={sp_dc}",
        "Accept": accept,
        "Accept-Encoding": "identity",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }


def fetch_invoices(sp_dc: str) -> list[dict]:
    """Fetch invoice list from Spotify order history page (__NEXT_DATA__)."""
    headers = build_headers(sp_dc, accept="text/html,application/xhtml+xml")
    req = urllib.request.Request(ORDER_HISTORY_URL, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            _auth_error()
        raise

    if "login" in html[:5000].lower() and "password" in html[:5000].lower():
        _auth_error()

    # Extract __NEXT_DATA__ JSON
    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        print("ERROR: Could not find __NEXT_DATA__ on page.", file=sys.stderr)
        print("The page structure may have changed.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(match.group(1))
    props = data.get("props", {}).get("pageProps", {})
    payment_history = props.get("paymentHistoryResult", {})
    invoices = payment_history.get("invoices", [])

    if not invoices:
        print("WARNING: No invoices found in paymentHistoryResult.", file=sys.stderr)

    return invoices


def parse_date(invoice: dict) -> str | None:
    """Parse date from formattedSoldAt like 'mai 18, 2026' → '2026_05_18'."""
    raw = invoice.get("formattedSoldAt", "")
    # Pattern: "month day, year"
    match = re.match(r"(\S+)\s+(\d{1,2}),\s+(\d{4})", raw)
    if not match:
        return None
    month_str, day, year = match.group(1), match.group(2), match.group(3)
    month = FRENCH_MONTHS.get(month_str)
    if not month:
        return None
    return f"{year}_{month}_{int(day):02d}"


def get_receipt_url(invoice: dict) -> str | None:
    """Extract receipt URL from invoice menu links."""
    for menu_item in invoice.get("menu", []):
        link = menu_item.get("link", {})
        if link.get("semanticId") == "original-receipt":
            return link.get("url")
    return None


def download_receipt(
    invoice: dict, sp_dc: str, output_dir: Path
) -> Path | None:
    """Download the receipt PDF for an invoice."""
    receipt_path = get_receipt_url(invoice)
    if not receipt_path:
        return None

    url = f"{BASE_URL}{receipt_path}" if not receipt_path.startswith("http") else receipt_path

    date_str = parse_date(invoice)
    invoice_id = invoice.get("id", "unknown")
    filename = f"{date_str}_spotify.pdf" if date_str else f"spotify_{invoice_id}.pdf"
    output_path = output_dir / filename

    if output_path.exists():
        print(f"  SKIP (exists): {filename}")
        return output_path

    headers = build_headers(sp_dc, accept="application/pdf,*/*")
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "")

            if "pdf" in content_type or content[:4] == b"%PDF":
                output_path.write_bytes(content)
                print(f"  SAVED: {filename} ({len(content):,} bytes)")
                return output_path
            else:
                print(f"  WARN: {filename} — not a PDF (Content-Type: {content_type})")
                return None
    except urllib.error.HTTPError as e:
        print(f"  ERROR: {filename} — HTTP {e.code}", file=sys.stderr)
        return None


def _auth_error() -> None:
    print(
        "ERROR: Authentication failed. Your sp_dc cookie may be expired.\n"
        "Please log in to spotify.com and copy a fresh sp_dc cookie.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Spotify invoices/receipts")
    parser.add_argument(
        "--sp-dc",
        default=os.environ.get("SPOTIFY_SP_DC", ""),
        help="Spotify sp_dc cookie value (or set SPOTIFY_SP_DC env var)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory to save downloaded invoices (default: data/raw)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list orders without downloading",
    )
    args = parser.parse_args()

    if not args.sp_dc:
        print(
            "ERROR: No sp_dc cookie provided.\n"
            "Set SPOTIFY_SP_DC environment variable or pass --sp-dc.\n\n"
            "To get your sp_dc cookie:\n"
            "  1. Log in to https://open.spotify.com in your browser\n"
            "  2. Open Developer Tools (F12) → Application → Cookies\n"
            "  3. Copy the value of the 'sp_dc' cookie",
            file=sys.stderr,
        )
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching Spotify order history...")
    invoices = fetch_invoices(args.sp_dc)

    if not invoices:
        print("No invoices found.")
        return

    print(f"Found {len(invoices)} invoice(s).\n")

    if args.list_only:
        for inv in invoices:
            date = parse_date(inv) or "unknown"
            amount = inv.get("formattedAmountSummary", "?")
            has_receipt = "✓" if get_receipt_url(inv) else "✗"
            print(f"  {date}  {amount:>10s}  receipt={has_receipt}  id={inv['id']}")
        return

    downloaded = 0
    skipped_no_receipt = 0
    for inv in invoices:
        date = parse_date(inv) or inv["id"][:8]
        receipt_url = get_receipt_url(inv)
        if not receipt_url:
            print(f"  SKIP (no receipt link): {date}")
            skipped_no_receipt += 1
            continue
        result = download_receipt(inv, args.sp_dc, args.output_dir)
        if result:
            downloaded += 1

    print(f"\nDone. Downloaded {downloaded} receipt(s) to {args.output_dir}")
    if skipped_no_receipt:
        print(f"  ({skipped_no_receipt} invoice(s) had no receipt link)")


if __name__ == "__main__":
    main()
