"""Inqom document uploader — authenticates via Playwright, uploads via HTTP API."""

from __future__ import annotations

import calendar
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Generator

import requests
from playwright.sync_api import sync_playwright, Page, BrowserContext

from .config import get_settings

logger = logging.getLogger(__name__)

INQOM_LOGIN_URL = "https://home.inqom.com/login"
INQOM_HOME_URL = "https://home.inqom.com"
INQOM_API_BASE = "https://api.inqom.com"
INQOM_UPLOAD_ENDPOINT = "/api/v1/accounting/enterprises/{enterprise_id}/documents"


class InqomUploadError(Exception):
    """Raised when upload to Inqom fails."""


class InqomUploader:
    """Upload accounting documents to Inqom via HTTP API (auth via Playwright)."""

    def __init__(
        self,
        email: str,
        password: str,
        client_id: str = "INQOM_CLIENT_ID_PLACEHOLDER",
        state_dir: Path = Path("data"),
        headless: bool = True,
    ):
        self.email = email
        self.password = password
        self.client_id = client_id
        self.state_dir = state_dir
        self.state_file = state_dir / ".inqom_session.json"
        self.token_file = state_dir / ".inqom_token.json"
        self.headless = headless
        self._token: str | None = None

    def __enter__(self):
        self.authenticate()
        return self

    def __exit__(self, *args):
        pass

    def authenticate(self):
        """Obtain a valid Bearer token, reusing cached if still valid."""
        # Try cached token first
        if self._try_cached_token():
            return
        # Perform browser login and intercept token
        self._login_and_capture_token()

    def _try_cached_token(self) -> bool:
        """Try to use a previously cached token."""
        if not self.token_file.exists():
            return False
        try:
            data = json.loads(self.token_file.read_text())
            token = data.get("token", "")
            if not token:
                return False
            # Validate token with a lightweight API call
            resp = requests.get(
                f"{INQOM_API_BASE}/api/app/enterprises/{self.client_id}/rights",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                self._token = token
                logger.info("Reused cached Inqom token")
                return True
            logger.info(f"Cached token expired (status {resp.status_code})")
            return False
        except Exception as e:
            logger.warning(f"Failed to validate cached token: {e}")
            return False

    def _login_and_capture_token(self):
        """Login via Playwright and intercept the Bearer token from API requests."""
        logger.info("Logging in to Inqom via browser to capture auth token...")
        captured_tokens: list[str] = []

        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context(
                storage_state=str(self.state_file) if self.state_file.exists() else None
            )
            page = context.new_page()

            # Intercept API requests to capture Bearer token
            def _on_request(request):
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and "inqom" in request.url:
                    token = auth[7:]
                    if token and token not in captured_tokens:
                        captured_tokens.append(token)

            page.on("request", _on_request)

            # Check if stored session is still valid
            page.goto(INQOM_HOME_URL, wait_until="networkidle", timeout=20000)
            self._dismiss_cookie_banner(page)

            if "/login" in page.url:
                # Need fresh login
                self._perform_login(page)

            # Trigger an API call to capture the token
            page.wait_for_timeout(3000)
            # Navigate to a page that triggers API calls
            begin_date, end_date = self._fiscal_year_dates()
            page.evaluate(
                f"window.location.assign('https://home.inqom.com/clients/{self.client_id}"
                f"/gestion/accounting-documents?begin_date={begin_date}&end_date={end_date}')"
            )
            page.wait_for_timeout(5000)

            # Save browser state for faster re-auth next time
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(self.state_file))

            context.close()
            browser.close()
        finally:
            pw.stop()

        if not captured_tokens:
            raise InqomUploadError("Failed to capture Bearer token during login")

        # Use the last captured token (most recent)
        self._token = captured_tokens[-1]
        self._save_token()
        logger.info("Successfully captured Inqom Bearer token")

    def _perform_login(self, page: Page):
        """Fill login form and submit."""
        page.wait_for_selector(
            "input[type='email'], input[name='email'], input[type='text']", timeout=15000
        )

        email_input = page.locator("input[type='email'], input[name='email'], input[type='text']").first
        email_input.fill(self.email)

        password_input = page.locator("input[type='password']").first
        if password_input.is_visible():
            password_input.fill(self.password)
        else:
            page.locator(
                "button[type='submit'], button:has-text('Suivant'), button:has-text('Next')"
            ).first.click()
            page.wait_for_selector("input[type='password']", timeout=10000)
            page.locator("input[type='password']").first.fill(self.password)

        page.locator(
            "button[type='submit'], button:has-text('Connexion'), "
            "button:has-text('Se connecter'), button:has-text('Log in')"
        ).first.click()

        page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(3000)
        logger.info(f"Login successful, landed on: {page.url}")

    def _dismiss_cookie_banner(self, page: Page):
        """Dismiss cookie consent banner."""
        selectors = [
            "button:has-text('Tout accepter')",
            "button:has-text('Accept all')",
            "button:has-text('Accepter')",
            "button:has-text('OK')",
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    def _save_token(self):
        """Persist token to disk."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({"token": self._token}))

    def _fiscal_year_dates(self) -> tuple[str, str]:
        """Return the current fiscal year boundaries as ISO dates."""
        today = date.today()
        start_month = get_settings().inqom_fiscal_year_start_month
        start_year = today.year if today.month >= start_month else today.year - 1

        end_month = 12 if start_month == 1 else start_month - 1
        end_year = start_year if start_month == 1 else start_year + 1
        end_day = calendar.monthrange(end_year, end_month)[1]

        begin_date = date(start_year, start_month, 1)
        end_date = date(end_year, end_month, end_day)
        return begin_date.isoformat(), end_date.isoformat()

    def upload_document(self, file_path: Path, doc_type: str = "SupplierBill") -> dict:
        """
        Upload a single document to Inqom via HTTP API.

        Args:
            file_path: Path to the file to upload.
            doc_type: AccountingFileType (SupplierBill, ClientBill, ExpenseReport, Other).

        Returns:
            Dict with upload result info.
        """
        if not file_path.exists():
            raise InqomUploadError(f"File not found: {file_path}")
        if not self._token:
            raise InqomUploadError("Not authenticated — call authenticate() first")

        url = f"{INQOM_API_BASE}{INQOM_UPLOAD_ENDPOINT.format(enterprise_id=self.client_id)}"

        with open(file_path, "rb") as f:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                data={"AccountingFileType": doc_type},
                files={"Documents": (file_path.name, f)},
                timeout=60,
            )

        if resp.status_code in (200, 201):
            logger.info(f"Uploaded '{file_path.name}' as {doc_type} — HTTP {resp.status_code}")
            return {
                "file": file_path.name,
                "status": "uploaded",
                "response": resp.json() if resp.content else {},
            }
        elif resp.status_code == 401:
            # Token expired mid-session — retry once
            logger.warning("Token expired during upload, re-authenticating...")
            self._login_and_capture_token()
            return self.upload_document(file_path, doc_type)
        else:
            raise InqomUploadError(
                f"Upload failed for '{file_path.name}': HTTP {resp.status_code} — {resp.text[:200]}"
            )

    def upload_documents_stream(
        self, file_paths: list[Path], doc_type: str = "SupplierBill"
    ) -> Generator[dict, None, None]:
        """
        Upload multiple documents with progress events.

        Yields progress dicts compatible with the existing SSE stream format.
        """
        total = len(file_paths)
        uploaded = 0
        uploaded_files: list[str] = []
        errors: list[str] = []

        yield {"type": "status", "message": f"Uploading {total} document(s) to Inqom API…"}

        for i, file_path in enumerate(file_paths, 1):
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "message": f"Uploading {file_path.name} ({i}/{total})…",
            }
            try:
                self.upload_document(file_path, doc_type)
                uploaded += 1
                uploaded_files.append(str(file_path))
                yield {
                    "type": "uploaded",
                    "current": i,
                    "total": total,
                    "file": file_path.name,
                    "file_path": str(file_path),
                }
            except Exception as e:
                errors.append(f"{file_path.name}: {e}")
                logger.warning(f"Failed to upload {file_path.name}: {e}")

        yield {"type": "done", "result": {
            "total": total,
            "uploaded": uploaded,
            "uploaded_files": uploaded_files,
            "errors": errors,
        }}


def explore_inqom_ui(email: str, password: str):
    """
    Interactive exploration helper — authenticates and tests token capture.
    """
    uploader = InqomUploader(email, password, headless=False)
    uploader.authenticate()
    print(f"\n✅ Authenticated. Token captured: {uploader._token[:20]}...")

    # Test a lightweight API call
    resp = requests.get(
        f"{INQOM_API_BASE}/api/app/enterprises/{uploader.client_id}/rights",
        headers={"Authorization": f"Bearer {uploader._token}"},
        timeout=10,
    )
    print(f"API test call: HTTP {resp.status_code}")
    if resp.status_code == 200:
        print("✅ Token is valid and API is accessible")
    else:
        print(f"❌ API returned: {resp.text[:200]}")
