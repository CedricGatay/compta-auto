"""Freebox ISP invoice fetcher via subscribe.free.fr subscriber portal."""

from __future__ import annotations

import http.cookiejar
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Generator


FREEBOX_LOGIN_URL = "https://subscribe.free.fr/login/do_login.pl"
ADSL_BASE = "https://adsl.free.fr"


class AuthError(Exception):
    """Raised when authentication fails."""


def _build_opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPRedirectHandler(),
    )
    return opener, cj


def login(username: str, password: str) -> tuple[urllib.request.OpenerDirector, str, str]:
    """
    Login to the Freebox subscriber portal.
    Returns (opener, account_id, idt_token).
    Raises AuthError on failure.
    """
    opener, cj = _build_opener()

    payload = urllib.parse.urlencode({
        "login": username,
        "pass": password,
        "link": "",
    }).encode()

    req = urllib.request.Request(
        FREEBOX_LOGIN_URL,
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://subscribe.free.fr",
            "Referer": "https://subscribe.free.fr/login/",
        },
    )

    try:
        with opener.open(req) as resp:
            body = resp.read().decode("latin-1")
            final_url = resp.url
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("Identifiant ou mot de passe incorrect.")
        raise AuthError(f"Login failed: HTTP {e.code}")

    # After successful login, we get redirected to adsl.free.fr/home.pl?id=...&idt=...
    parsed = urllib.parse.urlparse(final_url)
    params = urllib.parse.parse_qs(parsed.query)
    account_id = params.get("id", [""])[0]
    idt = params.get("idt", [""])[0]

    if not account_id or not idt:
        # Check for error indicators in the body
        if "identification" in body.lower() and "chou" in body.lower():
            raise AuthError("Identifiant ou mot de passe incorrect.")
        raise AuthError("Login failed: could not extract session token from redirect.")

    return opener, account_id, idt


def _fetch_invoice_list(
    opener: urllib.request.OpenerDirector, account_id: str, idt: str
) -> list[dict]:
    """
    Fetch the full invoice list page and extract all invoice entries.
    Each invoice has: mois (YYYYMM) and no_facture.
    """
    # The home page already shows recent invoices, but facture_liste.pl has all of them
    url = f"{ADSL_BASE}/facture_liste.pl?id={account_id}&idt={idt}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": f"{ADSL_BASE}/home.pl?id={account_id}&idt={idt}",
    })

    try:
        with opener.open(req) as resp:
            html = resp.read().decode("latin-1")
    except urllib.error.HTTPError as e:
        raise AuthError(f"Failed to fetch invoice list: HTTP {e.code}")

    # Extract facture_pdf.pl links with mois and no_facture params
    invoices = []
    pattern = re.compile(
        r'facture_pdf\.pl\?[^"]*mois=(\d{6})[^"]*no_facture=(\d+)',
        re.IGNORECASE,
    )
    seen = set()
    for match in pattern.finditer(html):
        mois = match.group(1)
        no_facture = match.group(2)
        key = (mois, no_facture)
        if key in seen:
            continue
        seen.add(key)
        invoices.append({
            "mois": mois,
            "no_facture": no_facture,
            "year": mois[:4],
            "month": mois[4:6],
        })

    # Sort by date descending
    invoices.sort(key=lambda x: x["mois"], reverse=True)
    return invoices


def _download_invoice(
    opener: urllib.request.OpenerDirector,
    account_id: str,
    idt: str,
    invoice: dict,
    output_dir: Path,
) -> str | None:
    """Download a single invoice PDF. Returns filename or None if skipped."""
    year = invoice["year"]
    month = invoice["month"]
    filename = f"freebox_{year}_{month}.pdf"

    output_path = output_dir / filename
    if output_path.exists():
        return None  # Already downloaded

    url = (
        f"{ADSL_BASE}/facture_pdf.pl?"
        f"id={account_id}&idt={idt}"
        f"&mois={invoice['mois']}&no_facture={invoice['no_facture']}"
    )

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": f"{ADSL_BASE}/facture_liste.pl?id={account_id}&idt={idt}",
    })

    try:
        with opener.open(req) as resp:
            content = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} downloading invoice {year}-{month}")

    # Verify it's a PDF
    if content[:4] != b"%PDF":
        return None

    output_path.write_bytes(content)
    return filename


def fetch_freebox_invoices_stream(
    username: str,
    password: str,
    output_dir: Path,
) -> Generator[dict, None, None]:
    """
    Login and download all Freebox ISP invoices.
    Yields progress events (same protocol as other fetchers).
    """
    yield {"type": "status", "message": "Logging in to Freebox subscriber portal…"}

    try:
        opener, account_id, idt = login(username, password)
    except AuthError as e:
        yield {"type": "error", "error": str(e)}
        return

    yield {"type": "status", "message": "Fetching invoice list…"}

    try:
        invoices = _fetch_invoice_list(opener, account_id, idt)
    except AuthError as e:
        yield {"type": "error", "error": str(e)}
        return

    if not invoices:
        yield {"type": "done", "result": {
            "total": 0, "downloaded": 0, "skipped": 0, "errors": [],
            "message": "No invoices found on the portal.",
        }}
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(invoices)
    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for i, inv in enumerate(invoices, 1):
        label = f"{inv['year']}-{inv['month']}"
        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "message": f"Downloading invoice {i}/{total} ({label})…",
        }
        try:
            filename = _download_invoice(opener, account_id, idt, inv, output_dir)
            if filename:
                downloaded += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"Failed to download {label}: {e}")

    yield {"type": "done", "result": {
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }}
