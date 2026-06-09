"""Orange/Sosh invoice fetcher using Playwright (headless browser).

Orange uses DataDome bot protection which blocks urllib/requests.
Playwright authenticates via the real login form, then uses fetch()
from within the authenticated browser context to call the bills API.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Generator

from .providers.base import AuthError


LOGIN_URL = "https://login.orange.fr"
EC_BASE = "https://espace-client.orange.fr"

# Headers required by the Orange bills API
_API_HEADERS = {
    "X-Orange-Caller-Id": "ECQ",
    "X-Orange-Origin-Id": "ECQ",
    "X-App-Device-Type": "desktop",
    "Accept": "application/json",
}


def _launch_and_login(username: str, password: str):
    """Launch Playwright, authenticate, return (page, browser, pw).

    Raises AuthError on login failure.
    Returns a tuple (page, browser, playwright_instance) — caller must close.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    try:
        page.goto(
            f"{LOGIN_URL}/?service=ec"
            f"&return_url=https%3A%2F%2Fespace-client.orange.fr%2F",
            wait_until="networkidle",
        )

        # Fill username
        page.fill('input[type="text"]', username)
        page.click('button[type="submit"]')
        page.wait_for_timeout(2000)

        # Check for error (bad username)
        error_el = page.query_selector('[class*="error"], [role="alert"]')
        if error_el:
            text = error_el.inner_text().strip()
            if text:
                raise AuthError(f"Login failed: {text}")

        # Fill password
        try:
            page.wait_for_selector('input[type="password"]', timeout=5000)
        except PwTimeout:
            raise AuthError("Password field did not appear. Username may be invalid.")
        page.fill('input[type="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_timeout(3000)

        # Dismiss any promo/interstitial screens
        for _ in range(5):
            dismissed = False
            buttons = page.query_selector_all("button")
            for btn in buttons:
                try:
                    text = btn.inner_text().strip().lower()
                except Exception:
                    continue
                if any(w in text for w in ("continuer", "plus tard", "passer", "fermer")):
                    btn.click()
                    page.wait_for_timeout(2000)
                    dismissed = True
                    break
            if not dismissed:
                break

        # Verify we reached espace-client
        page.wait_for_timeout(2000)
        if "login.orange.fr" in page.url:
            # Still on login page — check for OTP or error
            if page.query_selector('input[name="otc"], input[aria-label*="code"]'):
                raise AuthError("OTP_REQUIRED")
            raise AuthError("Authentication did not complete. Check credentials.")

    except AuthError:
        raise
    except Exception as exc:
        browser.close()
        pw.stop()
        raise AuthError(f"Browser login failed: {exc}") from exc

    return page, browser, pw


def _get_contract_id(page) -> str:
    """Extract contract ID from portfolio API or URL."""
    session_id = str(uuid.uuid4())
    headers = {**_API_HEADERS, "X-Orange-Session-Id": session_id,
               "X-Orange-Request-Id": str(uuid.uuid4()),
               "Accept": "application/json;version=1"}
    portfolio = page.evaluate(
        """(headers) => fetch('/ecd_wp/portfoliomanager/portfolio'
            + '?filter=telco,security&includeContracts=true&includeFamilies=true'
            + '&includeServices=true', {headers})
            .then(r => r.json())""",
        headers,
    )
    # Extract first contract ID from the contracts list
    contracts = portfolio.get("contracts", [])
    for contract in contracts:
        cid = contract.get("cid") or contract.get("contractId") or contract.get("id")
        if cid:
            return str(cid)

    # Fallback: extract from the current URL
    url = page.url
    parts = url.rstrip("/").split("/")
    for part in reversed(parts):
        if part.isdigit() and len(part) >= 8:
            return part

    raise AuthError("Could not determine contract ID from Orange account.")


def _fetch_bills(page, contract_id: str) -> list[dict]:
    """Fetch the bill list from the Orange API."""
    session_id = str(uuid.uuid4())
    headers = {**_API_HEADERS, "X-Orange-Session-Id": session_id,
               "X-Orange-Request-Id": str(uuid.uuid4())}

    url = (f"/ecd_wp/facture/v2.0/billsAndPaymentInfos/users/current"
           f"/contracts/{contract_id}?detail=true")

    data = page.evaluate(
        "(args) => fetch(args.url, {headers: args.headers}).then(r => r.json())",
        {"url": url, "headers": headers},
    )

    if "error" in data:
        raise AuthError(f"Bills API error: {data['error'].get('technicalDescription', 'unknown')}")

    bills = data.get("billsHistory", {}).get("billList", [])
    return bills


def _download_pdf(page, href_pdf: str) -> bytes:
    """Download a PDF using the hrefPdf query string."""
    url = f"/ecd_wp/facture/v1.0/pdf{href_pdf}"
    headers = {**_API_HEADERS, "X-Orange-Session-Id": str(uuid.uuid4()),
               "X-Orange-Request-Id": str(uuid.uuid4())}
    # Use arraybuffer to get binary data
    b64 = page.evaluate(
        """(args) => fetch(args.url, {headers: args.headers})
            .then(r => r.arrayBuffer())
            .then(buf => {
                const bytes = new Uint8Array(buf);
                let binary = '';
                for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                return btoa(binary);
            })""",
        {"url": url, "headers": headers},
    )
    import base64
    return base64.b64decode(b64)


def login(username: str, password: str) -> tuple[str, str | None]:
    """Login to Orange. Returns ("authenticated", None) or raises AuthError.

    The actual session lives in the browser — we do the full fetch in one go.
    This function just validates credentials quickly.
    """
    page, browser, pw = _launch_and_login(username, password)
    browser.close()
    pw.stop()
    # No OTP flow for now (account doesn't require it).
    # Return a sentinel; the actual fetch uses its own browser session.
    return "playwright_session", None


def fetch_orange_invoices_stream(
    session_cookies: str,
    otp_code: str,
    otp_id: str | None,
    output_dir: Path,
) -> Generator[dict, None, None]:
    """Kept for API compat. Not used with Playwright flow."""
    yield {"type": "error", "error": "OTP flow not supported yet for Orange."}


def fetch_orange_invoices_no_otp_stream(
    username: str,
    password: str,
    output_dir: Path,
    prefix: str = "orange",
) -> Generator[dict, None, None]:
    """Authenticate via Playwright and download all Orange/Sosh invoices.

    Yields progress events as SSE-compatible dicts.
    """
    yield {"type": "status", "message": "Launching browser and authenticating…"}

    try:
        page, browser, pw = _launch_and_login(username, password)
    except AuthError as e:
        yield {"type": "error", "error": str(e)}
        return

    try:
        yield {"type": "status", "message": "Fetching contract info…"}
        contract_id = _get_contract_id(page)

        yield {"type": "status", "message": "Fetching invoices list…"}
        bills = _fetch_bills(page, contract_id)

        if not bills:
            yield {"type": "done", "result": {
                "total": 0, "downloaded": 0, "skipped": 0, "errors": [],
                "message": "No invoices found in your Orange account.",
            }}
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        total = len(bills)
        downloaded = 0
        skipped = 0
        errors: list[str] = []

        for i, bill in enumerate(bills, 1):
            date_str = bill.get("date", "unknown")
            amount = bill.get("amount", 0) / 100
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "message": f"Downloading invoice {i}/{total} ({date_str}, {amount:.2f}€)…",
            }

            # Build filename
            filename = f"{prefix}_{date_str.replace('-', '_')}.pdf"
            output_path = output_dir / filename

            if output_path.exists():
                skipped += 1
                continue

            href_pdf = bill.get("hrefPdf")
            if not href_pdf:
                errors.append(f"No PDF link for invoice {date_str}")
                continue

            try:
                pdf_bytes = _download_pdf(page, href_pdf)
                if pdf_bytes[:4] != b"%PDF":
                    errors.append(f"Invalid PDF content for {date_str}")
                    continue
                output_path.write_bytes(pdf_bytes)
                downloaded += 1
            except Exception as exc:
                errors.append(f"Failed to download {date_str}: {exc}")

        yield {"type": "done", "result": {
            "total": total,
            "downloaded": downloaded,
            "skipped": skipped,
            "errors": errors,
        }}

    finally:
        browser.close()
        pw.stop()
