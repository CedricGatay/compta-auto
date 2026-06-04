"""Free Mobile invoice fetcher via account portal with OTP."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
import base64
from pathlib import Path
from typing import Generator

FREE_MOBILE_BASE = "https://mobile.free.fr/account/v2"
SEND_MAIL_ACTION_ID = "7fdbd72cf9658e42cc86a2a6059a70d7c600a44b05"


class AuthError(Exception):
    """Raised when authentication fails."""


def _build_opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return opener, cj


def _get_csrf_token(opener: urllib.request.OpenerDirector) -> str:
    """Get CSRF token from NextAuth, first visiting login page for required cookies."""
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

    # Visit login page first to get session cookies (csrf-token, callback-url)
    page_req = urllib.request.Request(f"{FREE_MOBILE_BASE}/login", headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        with opener.open(page_req) as resp:
            resp.read()  # consume body
    except urllib.error.HTTPError:
        pass  # non-critical, proceed anyway

    # Get CSRF token from API
    url = f"{FREE_MOBILE_BASE}/api/auth/csrf"
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "application/json",
        "Referer": f"{FREE_MOBILE_BASE}/login",
    })
    with opener.open(req) as resp:
        data = json.loads(resp.read().decode())
    return data["csrfToken"]


def _serialize_cookies(cj: http.cookiejar.CookieJar) -> str:
    """Serialize cookie jar to a JSON string for storage between steps."""
    cookies = []
    for c in cj:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
        })
    return json.dumps(cookies)


def _restore_cookies(opener: urllib.request.OpenerDirector, cj: http.cookiejar.CookieJar, serialized: str):
    """Restore cookies from serialized JSON string."""
    cookies = json.loads(serialized)
    for c in cookies:
        cookie = http.cookiejar.Cookie(
            version=0, name=c["name"], value=c["value"],
            port=None, port_specified=False,
            domain=c["domain"], domain_specified=True, domain_initial_dot=c["domain"].startswith("."),
            path=c["path"], path_specified=True,
            secure=True, expires=None, discard=True,
            comment=None, comment_url=None, rest={},
        )
        cj.set_cookie(cookie)


def login(username: str, password: str) -> tuple[str, str, int]:
    """
    Step 1: Login with credentials. Triggers OTP via email.
    Returns (session_cookies, csrf_token, otp_id).
    Raises AuthError if credentials are invalid or email OTP fails.
    """
    opener, cj = _build_opener()
    csrf_token = _get_csrf_token(opener)

    payload = urllib.parse.urlencode({
        "username": username,
        "password": password,
        "redirect": "false",
        "csrfToken": csrf_token,
        "callbackUrl": f"{FREE_MOBILE_BASE}/",
        "json": "true",
    }).encode()

    req = urllib.request.Request(
        f"{FREE_MOBILE_BASE}/api/auth/callback/credentials",
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://mobile.free.fr",
            "Referer": f"{FREE_MOBILE_BASE}/login",
            "Accept": "*/*",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
    )

    try:
        with opener.open(req) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            body = e.read().decode()
            error_match = re.search(r"error=([A-Z_]+)", body)
            error_type = error_match.group(1) if error_match else "UNKNOWN"
            error_messages = {
                "INVALID_CREDENTIALS": "Invalid credentials",
                "ACCOUNT_BLOCKED": "Account temporarily blocked (too many failed attempts). Try again in 15 minutes.",
                "TWO_ATTEMPTS_LEFT": "Invalid credentials (2 attempts left before block)",
                "ONE_ATTEMPT_LEFT": "Invalid credentials (1 attempt left before block)",
            }
            raise AuthError(error_messages.get(error_type, f"Login failed: {error_type}"))
        raise

    if "error" in result:
        error_type = result["error"]
        error_messages = {
            "INVALID_CREDENTIALS": "Invalid credentials",
            "ACCOUNT_BLOCKED": "Account temporarily blocked. Try again in 15 minutes.",
            "INTERNAL_ERROR": "Free Mobile service error. Try again later.",
        }
        raise AuthError(error_messages.get(error_type, f"Login failed: {error_type}"))

    # Verify session indicates OTP is needed
    session_req = urllib.request.Request(
        f"{FREE_MOBILE_BASE}/api/auth/session",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with opener.open(session_req) as resp:
        session = json.loads(resp.read().decode())

    if not session.get("user"):
        raise AuthError("Login failed: no session created")

    otp_id = session["user"].get("otpId")

    # Send OTP via email — discover action ID and login prop from OTP page
    action_ids, rsc_login = _discover_action_ids(opener)

    # Build login candidates: RSC prop > username > phone-prefixed variants
    login_candidates = []
    if rsc_login:
        login_candidates.append(rsc_login)
    if username not in login_candidates:
        login_candidates.append(username)

    mail_otp_id = None
    last_raw_response = ""
    for action_id in action_ids:
        for login_val in login_candidates:
            mail_otp_id, raw = _request_email_otp(opener, login_val, action_id)
            if raw:
                last_raw_response = raw
            if mail_otp_id:
                break
        if mail_otp_id:
            break

    if not mail_otp_id:
        raise AuthError(
            "Failed to send OTP via email. The Free Mobile portal may have changed "
            f"(tried {len(action_ids)} action ID(s) with {len(login_candidates)} login variant(s)). "
            f"Last response: {last_raw_response[:200]}. "
            "Check that your Free Mobile account has email configured for 2FA."
        )
    otp_id = mail_otp_id

    # Get a fresh CSRF token for the OTP step
    csrf_token = _get_csrf_token(opener)
    return _serialize_cookies(cj), csrf_token, otp_id


def _discover_action_ids(opener: urllib.request.OpenerDirector) -> tuple[list[str], str | None]:
    """
    Discover the sendMailAction ID and login prop from the OTP page.
    Returns (action_id_candidates, login_prop_from_rsc).
    """
    candidates = []
    login_prop = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html",
    }
    try:
        req = urllib.request.Request(f"{FREE_MOBILE_BASE}/otp", headers=headers)
        with opener.open(req) as resp:
            html = resp.read().decode()

        # Extract login prop from RSC flight data embedded in the page
        # The component receives {hasOtpSentBySMS, login} props
        # In RSC format these can appear as: "login":"value" or in positional args
        login_matches = re.findall(r'"login"\s*:\s*"([^"]+)"', html)
        if login_matches:
            login_prop = login_matches[0]
        else:
            # RSC flight data may use positional encoding - look for subscriber number pattern
            # Free Mobile subscriber numbers are 8-digit numeric
            numeric_matches = re.findall(r'(?<![a-f0-9])[0-9]{8}(?![0-9a-f])', html)
            if numeric_matches:
                login_prop = numeric_matches[0]

        # Find OTP page-specific JS chunk
        script_srcs = re.findall(r'src="([^"]+\.js)"', html)
        otp_chunk = None
        for src in script_srcs:
            if "otp" in src.lower() and "page" in src.lower():
                otp_chunk = src
                break

        if otp_chunk:
            base = "https://mobile.free.fr"
            url = f"{base}{otp_chunk}" if otp_chunk.startswith("/") else otp_chunk
            try:
                js_req = urllib.request.Request(url, headers={"User-Agent": headers["User-Agent"]})
                with opener.open(js_req) as resp:
                    js_content = resp.read().decode()
                # Find createServerReference("...", ..., "sendMailAction")
                m = re.search(r'createServerReference\("([a-f0-9]{40,})"[^)]*"sendMailAction"', js_content)
                if m:
                    candidates.append(m.group(1))
                else:
                    # Fallback: find any long hex ID near sendMailAction
                    m = re.search(r'"([a-f0-9]{40,})"[^;]*sendMailAction', js_content)
                    if m:
                        candidates.append(m.group(1))
            except Exception:
                pass

        # Also try extracting hex IDs from RSC data on the page (less targeted)
        rsc_hex_ids = re.findall(r'"([a-f0-9]{40,})"', html)
        for hid in rsc_hex_ids:
            if hid not in candidates:
                candidates.append(hid)

    except Exception:
        pass

    # Deduplicate, hardcoded fallback last
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    if SEND_MAIL_ACTION_ID not in seen:
        unique.append(SEND_MAIL_ACTION_ID)
    return unique, login_prop


def _request_email_otp(opener: urllib.request.OpenerDirector, login: str, action_id: str) -> tuple[int | None, str]:
    """Call the sendMailAction server action to send OTP via email. Returns (otpId, raw_response)."""
    body = json.dumps([login])
    req = urllib.request.Request(
        f"{FREE_MOBILE_BASE}/otp",
        data=body.encode(),
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "Next-Action": action_id,
            "Origin": "https://mobile.free.fr",
            "Referer": f"{FREE_MOBILE_BASE}/otp",
        },
    )
    try:
        with opener.open(req) as resp:
            result = resp.read().decode()
            # Parse RSC flight response lines (format: "index:json_value")
            for line in result.split("\n"):
                if not line or line.startswith("0:"):
                    continue  # skip metadata line
                parts = line.split(":", 1)
                if len(parts) != 2:
                    continue
                payload = parts[1].strip()
                if payload == "null" or payload == "":
                    continue
                try:
                    data = json.loads(payload)
                    # New format: {"id": 12345}
                    if isinstance(data, dict) and "id" in data:
                        return data["id"], result
                    # Old format: {"transport": "mail", "id": 12345}
                    if isinstance(data, dict) and data.get("transport") == "mail":
                        return data.get("id"), result
                except (json.JSONDecodeError, TypeError):
                    continue
            return None, result
    except Exception as e:
        return None, str(e)


def validate_otp(session_cookies: str, csrf_token: str, otp_code: str, otp_id: int | None = None) -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    """
    Step 2: Validate OTP code.
    Returns authenticated opener + cookie jar.
    Raises AuthError if OTP is invalid.
    """
    opener, cj = _build_opener()
    _restore_cookies(opener, cj, session_cookies)

    params = {
        "codeOtp": otp_code,
        "redirect": "false",
        "isTrusted": "false",
        "csrfToken": csrf_token,
        "callbackUrl": f"{FREE_MOBILE_BASE}/",
        "json": "true",
    }
    if otp_id:
        params["otpId"] = str(otp_id)

    payload = urllib.parse.urlencode(params).encode()

    req = urllib.request.Request(
        f"{FREE_MOBILE_BASE}/api/auth/callback/credentials",
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://mobile.free.fr",
            "Referer": f"{FREE_MOBILE_BASE}/otp",
            "Accept": "*/*",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
    )

    try:
        with opener.open(req) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            body = e.read().decode()
            # Parse error type from response
            error_match = re.search(r"error=([A-Z_]+)", body)
            error_type = error_match.group(1) if error_match else "UNKNOWN"
            error_messages = {
                "INVALID_OTP": "Invalid OTP code",
                "INVALID_CREDENTIALS": "Invalid OTP code or session expired",
                "ACCOUNT_BLOCKED": "Account temporarily blocked (too many attempts)",
                "TWO_ATTEMPTS_LEFT": "Invalid OTP code (2 attempts left before block)",
                "ONE_ATTEMPT_LEFT": "Invalid OTP code (1 attempt left before block)",
            }
            raise AuthError(error_messages.get(error_type, f"OTP validation failed: {error_type}"))
        raise

    if "error" in result:
        raise AuthError(f"OTP validation failed: {result['error']}")

    # Verify the token is now validated
    user_token = None
    for c in cj:
        if c.name == "X_USER_TOKEN":
            user_token = c.value
            break

    if user_token:
        try:
            parts = user_token.split(".")
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            jwt_data = json.loads(base64.urlsafe_b64decode(payload_b64))
            access_token = jwt_data.get("data", {}).get("accessToken", "")
            if access_token:
                inner_parts = access_token.split(".")
                inner_b64 = inner_parts[1] + "=" * (4 - len(inner_parts[1]) % 4)
                inner = json.loads(base64.urlsafe_b64decode(inner_b64))
                if not inner.get("data", {}).get("isValidated"):
                    raise AuthError("OTP validation did not succeed (token still unvalidated)")
        except (IndexError, json.JSONDecodeError, KeyError):
            pass

    return opener, cj


def _fetch_invoices_page(opener: urllib.request.OpenerDirector) -> str:
    """Fetch the home page which contains invoice data in RSC payload."""
    req = urllib.request.Request(
        f"{FREE_MOBILE_BASE}/",
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with opener.open(req) as resp:
        return resp.read().decode()


def _extract_invoice_links(html: str) -> list[dict]:
    """Extract invoice data from the home page RSC payload."""
    invoices = []

    # Extract RSC inline data
    rsc_lines = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    full_rsc = "\n".join(
        r.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        for r in rsc_lines
    )

    # Parse the invoices JSON array from RSC data
    # Format: "invoices":[{"id":..., "name":"...", "fileUrl":"...", "date":"...", ...}]
    invoice_match = re.search(r'"invoices":\[(.*?)\]', full_rsc)
    if invoice_match:
        try:
            invoices_data = json.loads("[" + invoice_match.group(1) + "]")
            for inv in invoices_data:
                if inv.get("fileState") == "done":
                    invoices.append({
                        "id": inv["id"],
                        "name": inv.get("name", ""),
                        "date": inv.get("date", ""),
                        "amount": inv.get("amount", ""),
                        "url": f"{FREE_MOBILE_BASE}/api/SI/invoice/{inv['id']}",
                    })
        except (json.JSONDecodeError, KeyError):
            pass

    # Also pick up any /api/SI/invoice/ links not in the invoices list
    # (e.g. the current month's invoice shown separately)
    known_ids = {inv["id"] for inv in invoices}
    si_ids = set(re.findall(r'/api/SI/invoice/(\d+)', full_rsc + html))
    for inv_id_str in si_ids:
        inv_id = int(inv_id_str)
        if inv_id not in known_ids:
            invoices.append({
                "id": inv_id,
                "name": "",
                "date": "",
                "amount": "",
                "url": f"{FREE_MOBILE_BASE}/api/SI/invoice/{inv_id}",
            })

    # Fallback: if no invoices found from JSON, use the SI links
    if not invoices:
        for inv_id_str in si_ids:
            invoices.append({
                "id": int(inv_id_str),
                "name": "",
                "date": "",
                "amount": "",
                "url": f"{FREE_MOBILE_BASE}/api/SI/invoice/{inv_id_str}",
            })

    return invoices


def _download_invoice(opener: urllib.request.OpenerDirector, invoice: dict, output_dir: Path) -> str | None:
    """Download a single invoice PDF. Returns filename or None if skipped."""
    url = invoice["url"]

    # Build filename from invoice date and name
    date_str = ""
    if invoice.get("date"):
        # date format: "2026-04-15T00:00:00+02:00"
        date_str = invoice["date"][:10].replace("-", "_")

    name = invoice.get("name", "").replace(" ", "_")
    if date_str and name:
        filename = f"free_mobile_{date_str}_{name}.pdf"
    elif date_str:
        filename = f"free_mobile_{date_str}_{invoice.get('id', 'unknown')}.pdf"
    else:
        filename = f"free_mobile_{invoice.get('id', 'unknown')}.pdf"

    output_path = output_dir / filename
    if output_path.exists():
        return None

    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    })

    with opener.open(req) as resp:
        content = resp.read()
        # Verify it's actually a PDF
        if not content[:4] == b"%PDF":
            return None

        output_path.write_bytes(content)
        return filename


def fetch_free_invoices_stream(
    session_cookies: str,
    csrf_token: str,
    otp_code: str,
    otp_id: int | None,
    output_dir: Path,
) -> Generator[dict, None, None]:
    """
    Validate OTP and download all Free Mobile invoices.
    Yields progress events.
    """
    yield {"type": "status", "message": "Validating OTP code…"}

    try:
        opener, cj = validate_otp(session_cookies, csrf_token, otp_code, otp_id)
    except AuthError as e:
        yield {"type": "error", "error": str(e)}
        return

    yield {"type": "status", "message": "Fetching invoices page…"}

    try:
        html = _fetch_invoices_page(opener)
    except urllib.error.HTTPError as e:
        yield {"type": "error", "error": f"Failed to access invoices page: HTTP {e.code}"}
        return

    invoices = _extract_invoice_links(html)

    if not invoices:
        yield {"type": "done", "result": {
            "total": 0, "downloaded": 0, "skipped": 0, "errors": [],
            "message": "No invoices found. The page format may have changed.",
        }}
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(invoices)
    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for i, inv in enumerate(invoices, 1):
        inv_label = inv.get("name") or str(inv.get("id", "?"))
        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "message": f"Downloading invoice {i}/{total} ({inv_label})…",
        }
        try:
            filename = _download_invoice(opener, inv, output_dir)
            if filename:
                downloaded += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"Failed to download {inv_label}: {e}")

    yield {"type": "done", "result": {
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }}
