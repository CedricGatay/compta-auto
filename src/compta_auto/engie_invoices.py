"""Engie Pro invoice fetcher via espace-client.pro.engie.fr (Okta MFA)."""

from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Generator


ENGIE_BASE = "https://espace-client.pro.engie.fr"


class AuthError(Exception):
    """Raised when authentication fails."""


def _build_opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPRedirectHandler(),
    )
    return opener, cj


def _serialize_cookies(cj: http.cookiejar.CookieJar) -> str:
    """Serialize cookie jar to JSON for storage between steps."""
    cookies = []
    for c in cj:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
        })
    return json.dumps(cookies)


def _restore_cookies(cj: http.cookiejar.CookieJar, serialized: str):
    """Restore cookies from serialized JSON."""
    cookies = json.loads(serialized)
    for c in cookies:
        cookie = http.cookiejar.Cookie(
            version=0, name=c["name"], value=c["value"],
            port=None, port_specified=False,
            domain=c["domain"], domain_specified=True,
            domain_initial_dot=c["domain"].startswith("."),
            path=c["path"], path_specified=True,
            secure=True, expires=None, discard=True,
            comment=None, comment_url=None, rest={},
        )
        cj.set_cookie(cookie)


def login(email: str, password: str) -> tuple[str, str, str, str]:
    """
    Step 1: Login with credentials. Triggers MFA code send via email.
    Returns (session_cookies, factor_id, user_id, form_build_id) for the OTP step.
    Raises AuthError if credentials are invalid.
    """
    opener, cj = _build_opener()

    # Get login page for form_build_id and session cookie
    req = urllib.request.Request(f"{ENGIE_BASE}/user/auth", headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html",
    })
    with opener.open(req) as resp:
        html = resp.read().decode("utf-8")

    form_build_match = re.search(r'name="form_build_id"\s+value="([^"]+)"', html)
    if not form_build_match:
        raise AuthError("Could not find form_build_id on login page.")
    form_build_id = form_build_match.group(1)

    # POST login via AJAX
    payload = urllib.parse.urlencode({
        "email_login": email,
        "mdp_login": password,
        "form_build_id": form_build_id,
        "form_id": "login_form_page",
        "op": "Me connecter",
        "_triggering_element_name": "op",
        "_triggering_element_value": "Me connecter",
    }).encode()

    req = urllib.request.Request(
        f"{ENGIE_BASE}/user/auth?ajax_form=1",
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": ENGIE_BASE,
            "Referer": f"{ENGIE_BASE}/user/auth",
        },
    )

    try:
        with opener.open(req) as resp:
            ajax_body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise AuthError(f"Login failed: HTTP {e.code}")

    # Check for login success in AJAX response
    try:
        ajax_data = json.loads(ajax_body)
    except json.JSONDecodeError:
        raise AuthError("Unexpected response from login endpoint.")

    has_success = any(
        item.get("command") == "tagCommander"
        and "connexion-success" in json.dumps(item.get("parameters", {}))
        for item in ajax_data
    )
    if not has_success:
        raise AuthError("Identifiant ou mot de passe incorrect.")

    # Check if there's a redirect to verification (MFA)
    redirect_item = next(
        (item for item in ajax_data if item.get("command") == "redirect"), None
    )

    if redirect_item and "verification" in redirect_item.get("url", ""):
        # MFA required — get the verification page
        verif_url = redirect_item["url"]
        if verif_url.startswith("/"):
            verif_url = f"{ENGIE_BASE}{verif_url}"

        req = urllib.request.Request(verif_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html",
            "Referer": f"{ENGIE_BASE}/user/auth",
        })
        with opener.open(req) as resp:
            verif_page = resp.read().decode("utf-8")

        # Extract factor_id and user_id
        factor_match = re.search(r'name="factor_id"[^>]*value="([^"]+)"', verif_page)
        user_match = re.search(r'name="user_id"[^>]*value="([^"]+)"', verif_page)
        fb_match = re.search(r'name="form_build_id"[^>]*value="([^"]+)"', verif_page)

        if not factor_match or not user_match or not fb_match:
            raise AuthError("Could not extract MFA parameters from verification page.")

        factor_id = factor_match.group(1)
        user_id = user_match.group(1)
        verif_form_build_id = fb_match.group(1)

        # Send the code (POST to trigger email)
        payload = urllib.parse.urlencode({
            "factor_id": factor_id,
            "user_id": user_id,
            "form_build_id": verif_form_build_id,
            "form_id": "engie_oktamfa_factors_form",
            "op": "Send code",
        }).encode()

        req = urllib.request.Request(
            f"{ENGIE_BASE}/user/verification-compte1",
            data=payload,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": ENGIE_BASE,
                "Referer": f"{ENGIE_BASE}/user/verification-compte1",
            },
        )
        with opener.open(req) as resp:
            code_page = resp.read().decode("utf-8")

        # Extract form_build_id for the code verification step
        code_fb_match = re.search(r'name="form_build_id"[^>]*value="([^"]+)"', code_page)
        if not code_fb_match:
            raise AuthError("Could not find form on code verification page.")

        return _serialize_cookies(cj), factor_id, user_id, code_fb_match.group(1)
    else:
        # No MFA needed (device already trusted)
        return _serialize_cookies(cj), "", "", ""


def validate_otp(
    session_cookies: str, factor_id: str, user_id: str, form_build_id: str, otp_code: str
) -> urllib.request.OpenerDirector:
    """
    Step 2: Validate the 6-digit OTP code.
    Returns an authenticated opener.
    Raises AuthError if OTP is invalid.
    """
    opener, cj = _build_opener()
    _restore_cookies(cj, session_cookies)

    # Split the 6-digit code into individual boxes
    if len(otp_code) != 6 or not otp_code.isdigit():
        raise AuthError("OTP code must be exactly 6 digits.")

    payload = urllib.parse.urlencode({
        "factor_id": factor_id,
        "user_id": user_id,
        "box1": otp_code[0],
        "box2": otp_code[1],
        "box3": otp_code[2],
        "box4": otp_code[3],
        "box5": otp_code[4],
        "box6": otp_code[5],
        "otp_error_wrapper": "",
        "save_device": "1",
        "form_build_id": form_build_id,
        "form_id": "engie_oktamfa_factor_verify_form",
        "op": "Valider",
    }).encode()

    req = urllib.request.Request(
        f"{ENGIE_BASE}/user/verification-facteur",
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": ENGIE_BASE,
            "Referer": f"{ENGIE_BASE}/user/verification-facteur",
        },
    )

    try:
        with opener.open(req) as resp:
            body = resp.read().decode("utf-8")
            final_url = resp.url
    except urllib.error.HTTPError as e:
        raise AuthError(f"OTP validation failed: HTTP {e.code}")

    # If we're redirected back to verification, the code was wrong
    if "verification" in final_url:
        if "incorrect" in body.lower() or "invalide" in body.lower() or "error" in body.lower():
            raise AuthError("Code de sécurité incorrect.")
        raise AuthError("OTP validation failed. Please try again.")

    return opener


def _fetch_invoices_page(opener: urllib.request.OpenerDirector) -> str:
    """Fetch the invoices page from the Engie Pro portal."""
    req = urllib.request.Request(f"{ENGIE_BASE}/mes-factures-pro", headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html",
        "Referer": ENGIE_BASE,
    })
    try:
        with opener.open(req) as resp:
            body = resp.read().decode("utf-8")
            if "auth" in resp.url and "destination" in resp.url:
                raise AuthError("Session expired after OTP validation.")
            return body
    except urllib.error.HTTPError as e:
        raise AuthError(f"Failed to access invoices page: HTTP {e.code}")


def _extract_invoice_links(page_html: str) -> list[dict]:
    """Extract invoice PDF download links from the page."""
    invoices = []

    # Pattern: /download/facture-electronique/{id}?date=YYYY-MM-DD
    pattern = re.compile(
        r'/download/facture-electronique/(\d+)\?date=(\d{4})-(\d{2})-(\d{2})'
    )

    seen = set()
    for match in pattern.finditer(page_html):
        inv_id = match.group(1)
        year = match.group(2)
        month = match.group(3)
        day = match.group(4)
        if inv_id in seen:
            continue
        seen.add(inv_id)

        invoices.append({
            "id": inv_id,
            "url": f"{ENGIE_BASE}/download/facture-electronique/{inv_id}?date={year}-{month}-{day}",
            "year": year,
            "month": month,
            "day": day,
            "label": f"{year}-{month}-{day}",
        })

    # Sort by date descending
    invoices.sort(key=lambda x: f"{x['year']}{x['month']}{x['day']}", reverse=True)
    return invoices


def _download_invoice(
    opener: urllib.request.OpenerDirector, invoice: dict, output_dir: Path
) -> str | None:
    """Download a single invoice PDF. Returns filename or None if skipped."""
    url = invoice["url"]
    year = invoice["year"]
    month = invoice["month"]
    filename = f"engie_pro_{year}_{month}.pdf"

    output_path = output_dir / filename
    if output_path.exists():
        return None

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": f"{ENGIE_BASE}/mes-factures-pro",
    })

    try:
        with opener.open(req) as resp:
            content = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} downloading {url}")

    if content[:4] != b"%PDF":
        return None

    output_path.write_bytes(content)
    return filename


def fetch_engie_invoices_stream(
    session_cookies: str,
    factor_id: str,
    user_id: str,
    form_build_id: str,
    otp_code: str,
    output_dir: Path,
) -> Generator[dict, None, None]:
    """
    Validate OTP and download all Engie Pro invoices.
    Yields progress events.
    """
    yield {"type": "status", "message": "Validating security code…"}

    try:
        opener = validate_otp(session_cookies, factor_id, user_id, form_build_id, otp_code)
    except AuthError as e:
        yield {"type": "error", "error": str(e)}
        return

    yield {"type": "status", "message": "Fetching invoices page…"}

    try:
        page_html = _fetch_invoices_page(opener)
    except Exception as e:
        yield {"type": "error", "error": f"Failed to access invoices: {e}"}
        return

    invoices = _extract_invoice_links(page_html)

    if not invoices:
        yield {"type": "done", "result": {
            "total": 0, "downloaded": 0, "skipped": 0, "errors": [],
            "message": "No invoice download links found. The portal structure may need inspection.",
        }}
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(invoices)
    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for i, inv in enumerate(invoices, 1):
        label = inv.get("label", "?")
        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "message": f"Downloading invoice {i}/{total} ({label})…",
        }
        try:
            filename = _download_invoice(opener, inv, output_dir)
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
