"""Spotify invoice fetcher — library interface for the web UI."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import urllib.error
import urllib.request

BASE_URL = "https://www.spotify.com"
ORDER_HISTORY_URL = "https://www.spotify.com/fr/account/order-history/subscription/"

FRENCH_MONTHS: dict[str, str] = {
    "janv.": "01", "févr.": "02", "mars": "03", "avr.": "04",
    "mai": "05", "juin": "06", "juil.": "07", "août": "08",
    "sept.": "09", "oct.": "10", "nov.": "11", "déc.": "12",
}


def fetch_spotify_invoices(sp_dc: str, output_dir: Path) -> dict:
    """Fetch all Spotify invoices and download PDFs.

    Returns a summary dict with keys: total, downloaded, skipped, errors.
    Raises SystemExit on authentication failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    invoices = _fetch_invoice_list(sp_dc)

    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for inv in invoices:
        receipt_path = _get_receipt_url(inv)
        if not receipt_path:
            skipped += 1
            continue

        date_str = _parse_date(inv)
        invoice_id = inv.get("id", "unknown")
        filename = f"{date_str}_spotify.pdf" if date_str else f"spotify_{invoice_id}.pdf"
        out_path = output_dir / filename

        if out_path.exists():
            skipped += 1
            continue

        url = f"{BASE_URL}{receipt_path}" if not receipt_path.startswith("http") else receipt_path
        headers = _build_headers(sp_dc, accept="application/pdf,*/*")
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req) as resp:
                content = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "pdf" in content_type or content[:4] == b"%PDF":
                    out_path.write_bytes(content)
                    downloaded += 1
                else:
                    errors.append(f"{filename}: not a PDF")
        except urllib.error.HTTPError as e:
            errors.append(f"{filename}: HTTP {e.code}")

    return {
        "total": len(invoices),
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }


def fetch_spotify_invoices_stream(sp_dc: str, output_dir: Path):
    """Generator that yields progress events while fetching invoices.

    Yields dicts with type: 'progress' | 'done'.
    Raises SystemExit on auth failure.
    """
    from collections.abc import Generator

    output_dir.mkdir(parents=True, exist_ok=True)
    invoices = _fetch_invoice_list(sp_dc)
    total = len(invoices)

    yield {"type": "progress", "message": f"Found {total} invoice(s)", "current": 0, "total": total}

    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for i, inv in enumerate(invoices, 1):
        receipt_path = _get_receipt_url(inv)
        date_str = _parse_date(inv) or inv.get("id", "?")[:8]

        if not receipt_path:
            skipped += 1
            yield {"type": "progress", "message": f"[{i}/{total}] {date_str} — no receipt link", "current": i, "total": total}
            continue

        invoice_id = inv.get("id", "unknown")
        filename = f"{date_str}_spotify.pdf" if _parse_date(inv) else f"spotify_{invoice_id}.pdf"
        out_path = output_dir / filename

        if out_path.exists():
            skipped += 1
            yield {"type": "progress", "message": f"[{i}/{total}] {date_str} — already exists", "current": i, "total": total}
            continue

        url = f"{BASE_URL}{receipt_path}" if not receipt_path.startswith("http") else receipt_path
        headers = _build_headers(sp_dc, accept="application/pdf,*/*")
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req) as resp:
                content = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "pdf" in content_type or content[:4] == b"%PDF":
                    out_path.write_bytes(content)
                    downloaded += 1
                    yield {"type": "progress", "message": f"[{i}/{total}] {date_str} — downloaded", "current": i, "total": total}
                else:
                    errors.append(f"{filename}: not a PDF")
                    yield {"type": "progress", "message": f"[{i}/{total}] {date_str} — not a PDF", "current": i, "total": total}
        except urllib.error.HTTPError as e:
            errors.append(f"{filename}: HTTP {e.code}")
            yield {"type": "progress", "message": f"[{i}/{total}] {date_str} — HTTP {e.code}", "current": i, "total": total}

    yield {"type": "done", "result": {"total": total, "downloaded": downloaded, "skipped": skipped, "errors": errors}}


def _fetch_invoice_list(sp_dc: str) -> list[dict]:
    """Fetch invoice list from Spotify order history page."""
    headers = _build_headers(sp_dc, accept="text/html,application/xhtml+xml")
    req = urllib.request.Request(ORDER_HISTORY_URL, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(1)
        raise

    if "login" in html[:5000].lower() and "password" in html[:5000].lower():
        sys.exit(1)

    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        raise RuntimeError("Could not find order data on Spotify page. Structure may have changed.")

    data = json.loads(match.group(1))
    props = data.get("props", {}).get("pageProps", {})

    # Detect login/auth page: presence of flowId or absence of paymentHistoryResult
    if "flowId" in props or "paymentHistoryResult" not in props:
        sys.exit(1)

    payment_history = props.get("paymentHistoryResult", {})
    return payment_history.get("invoices", [])


def _parse_date(invoice: dict) -> str | None:
    """Parse date from formattedSoldAt like 'mai 18, 2026' → '2026_05_18'."""
    raw = invoice.get("formattedSoldAt", "")
    match = re.match(r"(\S+)\s+(\d{1,2}),\s+(\d{4})", raw)
    if not match:
        return None
    month_str, day, year = match.group(1), match.group(2), match.group(3)
    month = FRENCH_MONTHS.get(month_str)
    if not month:
        return None
    return f"{year}_{month}_{int(day):02d}"


def _get_receipt_url(invoice: dict) -> str | None:
    """Extract receipt URL from invoice menu links."""
    for menu_item in invoice.get("menu", []):
        link = menu_item.get("link", {})
        if link.get("semanticId") == "original-receipt":
            return link.get("url")
    return None


def _build_headers(sp_dc: str, accept: str = "text/html") -> dict[str, str]:
    return {
        "Cookie": f"sp_dc={sp_dc}",
        "Accept": accept,
        "Accept-Encoding": "identity",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
