"""OVH invoice fetcher via the official OVH API (eu.api.ovh.com)."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Generator

from .providers.base import AuthError

OVH_API_BASE = "https://eu.api.ovh.com/1.0"


def _get_server_time() -> int:
    """Get OVH server timestamp for request signing."""
    url = f"{OVH_API_BASE}/auth/time"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return int(resp.read().decode())


def _sign_request(
    application_secret: str,
    consumer_key: str,
    method: str,
    url: str,
    body: str,
    timestamp: str,
) -> str:
    """Compute X-Ovh-Signature header value."""
    to_sign = "+".join([
        application_secret,
        consumer_key,
        method,
        url,
        body,
        timestamp,
    ])
    signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()
    return f"$1${signature}"


def _api_request(
    method: str,
    path: str,
    application_key: str,
    application_secret: str,
    consumer_key: str,
    body: str = "",
) -> bytes:
    """Make a signed OVH API request. Returns raw response bytes."""
    url = f"{OVH_API_BASE}{path}"
    timestamp = str(_get_server_time())
    signature = _sign_request(
        application_secret, consumer_key, method, url, body, timestamp
    )

    headers = {
        "X-Ovh-Application": application_key,
        "X-Ovh-Consumer": consumer_key,
        "X-Ovh-Timestamp": timestamp,
        "X-Ovh-Signature": signature,
        "Accept": "application/json",
        "Content-Type": "application/json;charset=utf-8",
    }

    req = urllib.request.Request(url, method=method, headers=headers)
    if body:
        req.data = body.encode("utf-8")

    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise AuthError("OVH API: forbidden — check your consumer key permissions.")
        if e.code == 401:
            raise AuthError("OVH API: invalid credentials (application key or consumer key expired).")
        error_body = e.read().decode()
        raise AuthError(f"OVH API error {e.code}: {error_body[:200]}")


def _api_json(
    path: str,
    application_key: str,
    application_secret: str,
    consumer_key: str,
):
    """GET JSON from OVH API."""
    raw = _api_request("GET", path, application_key, application_secret, consumer_key)
    return json.loads(raw.decode())


def fetch_ovh_invoices_stream(
    application_key: str,
    application_secret: str,
    consumer_key: str,
    output_dir: Path,
) -> Generator[dict, None, None]:
    """
    Fetch all OVH invoices as PDFs.
    Yields progress events (same protocol as other fetchers).
    """
    yield {"type": "status", "message": "Connecting to OVH API…"}

    try:
        bill_ids = _api_json("/me/bill", application_key, application_secret, consumer_key)
    except AuthError as e:
        yield {"type": "error", "error": str(e)}
        return

    if not bill_ids:
        yield {"type": "done", "result": {
            "total": 0, "downloaded": 0, "skipped": 0, "errors": [],
            "message": "No invoices found on OVH account.",
        }}
        return

    yield {"type": "status", "message": f"Found {len(bill_ids)} invoice(s), fetching details…"}

    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(bill_ids)
    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for i, bill_id in enumerate(bill_ids, 1):
        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "message": f"Processing invoice {i}/{total} ({bill_id})…",
        }

        try:
            bill_detail = _api_json(
                f"/me/bill/{urllib.parse.quote(bill_id, safe='')}",
                application_key, application_secret, consumer_key,
            )

            # Extract date for filename (format: 2024-01-15T10:00:00+01:00)
            bill_date = bill_detail.get("date", "")
            year = bill_date[:4] if len(bill_date) >= 4 else "unknown"
            month = bill_date[5:7] if len(bill_date) >= 7 else "00"

            # Build filename: ovh_YYYY_MM_billId.pdf
            safe_id = bill_id.replace("/", "_").replace("\\", "_")
            filename = f"ovh_{year}_{month}_{safe_id}.pdf"
            output_path = output_dir / filename

            if output_path.exists():
                skipped += 1
                continue

            # Get PDF download URL
            pdf_url = bill_detail.get("pdfUrl")
            if not pdf_url:
                errors.append(f"No PDF URL for invoice {bill_id}")
                continue

            # Download PDF (pdfUrl is a direct download link, no auth needed)
            pdf_req = urllib.request.Request(pdf_url, headers={
                "User-Agent": "Mozilla/5.0",
            })
            with urllib.request.urlopen(pdf_req) as resp:
                content = resp.read()

            if content[:4] != b"%PDF":
                errors.append(f"Invoice {bill_id}: response is not a PDF")
                continue

            output_path.write_bytes(content)
            downloaded += 1

        except AuthError:
            raise
        except Exception as e:
            errors.append(f"Failed {bill_id}: {e}")

    yield {"type": "done", "result": {
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }}
