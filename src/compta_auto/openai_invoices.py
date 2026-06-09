"""ChatGPT subscription invoice fetcher via Stripe billing portal."""

from __future__ import annotations

import json
import re
import html as html_mod
import urllib.error
import urllib.request
from pathlib import Path
from typing import Generator

from .providers.base import AuthError

CHATGPT_BACKEND = "https://chatgpt.com/backend-api"
STRIPE_API_VERSION = "2026-04-22.dahlia"


def _get_portal_session_url(bearer_token: str) -> str:
    """Get Stripe billing portal session URL from ChatGPT backend."""
    url = f"{CHATGPT_BACKEND}/payments/customer_portal"
    token = bearer_token.removeprefix("Bearer ").strip()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://chatgpt.com/",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data["url"]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("Bearer token is invalid or expired.")
        raise


def _extract_portal_credentials(portal_url: str) -> tuple[str, str]:
    """Fetch Stripe portal page and extract session_api_key and portal_session_id."""
    req = urllib.request.Request(portal_url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode()

    scripts = re.findall(r'<script[^>]*>(.*?)</script>', body, re.DOTALL)
    for s in scripts:
        decoded = html_mod.unescape(s)
        if "session_api_key" in decoded:
            try:
                data = json.loads(decoded)
            except json.JSONDecodeError:
                continue
            api_key = data.get("session_api_key")
            session_id = data.get("portal_session_id")
            if data.get("portal_session_expired"):
                raise AuthError("Stripe portal session has expired. Please try again.")
            if api_key and session_id:
                return api_key, session_id

    raise AuthError("Could not extract Stripe portal credentials from page.")


def _fetch_invoices_page(
    api_key: str, session_id: str, page_cursor: str | None = None
) -> dict:
    """Fetch one page of invoices from the Stripe portal API."""
    base = f"https://pay.openai.com/v1/billing_portal/sessions/{session_id}/exp/invoices"
    if page_cursor:
        base += f"?page={page_cursor}"

    req = urllib.request.Request(base, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Stripe-Version": STRIPE_API_VERSION,
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def _fetch_all_invoices(api_key: str, session_id: str) -> list[dict]:
    """Fetch all invoices across pages."""
    all_invoices: list[dict] = []
    cursor = None
    while True:
        page = _fetch_invoices_page(api_key, session_id, cursor)
        all_invoices.extend(page.get("data", []))
        cursor = page.get("next_page")
        if not cursor:
            break
    return all_invoices


def _download_pdf(url: str) -> bytes:
    """Download PDF from a Stripe invoice URL."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def fetch_chatgpt_invoices(bearer_token: str, output_dir: Path) -> dict:
    """Fetch all ChatGPT subscription invoices and download PDFs.

    Returns a summary dict with keys: total, downloaded, skipped, errors.
    Raises AuthError on authentication failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    portal_url = _get_portal_session_url(bearer_token)
    api_key, session_id = _extract_portal_credentials(portal_url)
    invoices = _fetch_all_invoices(api_key, session_id)

    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for inv in invoices:
        invoice_number = inv.get("invoice_number", inv["id"])
        filename = f"chatgpt_{invoice_number}.pdf"
        out_path = output_dir / filename

        if out_path.exists():
            skipped += 1
            continue

        dl_action = inv.get("allowed_actions", {}).get("download_invoice")
        if not dl_action or not dl_action.get("url"):
            errors.append(f"{filename}: no download URL")
            continue

        try:
            content = _download_pdf(dl_action["url"])
            if content[:4] == b"%PDF":
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


def fetch_chatgpt_invoices_stream(
    bearer_token: str, output_dir: Path
) -> Generator[dict, None, None]:
    """Generator that yields progress events while fetching invoices.

    Yields dicts with type: 'progress' | 'done' | 'error'.
    Raises AuthError on auth failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    yield {"type": "progress", "message": "Authenticating with ChatGPT…", "current": 0, "total": 0}

    portal_url = _get_portal_session_url(bearer_token)

    yield {"type": "progress", "message": "Connecting to Stripe billing portal…", "current": 0, "total": 0}

    api_key, session_id = _extract_portal_credentials(portal_url)

    yield {"type": "progress", "message": "Fetching invoice list…", "current": 0, "total": 0}

    invoices = _fetch_all_invoices(api_key, session_id)
    total = len(invoices)

    yield {"type": "progress", "message": f"Found {total} invoices", "current": 0, "total": total}

    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for i, inv in enumerate(invoices, 1):
        invoice_number = inv.get("invoice_number", inv["id"])
        filename = f"chatgpt_{invoice_number}.pdf"
        out_path = output_dir / filename

        if out_path.exists():
            skipped += 1
            yield {"type": "progress", "message": f"Skipped {filename} (exists)",
                   "current": i, "total": total}
            continue

        dl_action = inv.get("allowed_actions", {}).get("download_invoice")
        if not dl_action or not dl_action.get("url"):
            errors.append(f"{filename}: no download URL")
            yield {"type": "progress", "message": f"No download URL for {filename}",
                   "current": i, "total": total}
            continue

        try:
            content = _download_pdf(dl_action["url"])
            if content[:4] == b"%PDF":
                out_path.write_bytes(content)
                downloaded += 1
                yield {"type": "progress", "message": f"Downloaded {filename}",
                       "current": i, "total": total}
            else:
                errors.append(f"{filename}: not a PDF")
                yield {"type": "progress", "message": f"Not a PDF: {filename}",
                       "current": i, "total": total}
        except urllib.error.HTTPError as e:
            errors.append(f"{filename}: HTTP {e.code}")
            yield {"type": "progress", "message": f"Error {filename}: HTTP {e.code}",
                   "current": i, "total": total}

    yield {
        "type": "done",
        "result": {
            "total": total,
            "downloaded": downloaded,
            "skipped": skipped,
            "errors": errors,
        },
    }
