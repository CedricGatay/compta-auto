"""Inqom document uploader using Playwright browser automation."""

from __future__ import annotations

import calendar
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Generator

from playwright.sync_api import sync_playwright, Page, BrowserContext

from .config import get_settings

logger = logging.getLogger(__name__)

INQOM_LOGIN_URL = "https://home.inqom.com/login"
INQOM_HOME_URL = "https://home.inqom.com"
INQOM_PIECES_URL_TEMPLATE = "https://home.inqom.com/clients/{client_id}/gestion/accounting-documents"
STATE_FILE = Path("data/.inqom_session.json")


class InqomUploadError(Exception):
    """Raised when upload to Inqom fails."""


class InqomUploader:
    """Upload accounting documents to Inqom via browser automation."""

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
        self.state_file = state_dir / ".inqom_session.json"
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()

    def start(self):
        """Launch browser and restore or create session."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

        # Try to restore previous session
        if self.state_file.exists():
            try:
                self._context = self._browser.new_context(
                    storage_state=str(self.state_file)
                )
                self._page = self._context.new_page()
                if self._is_session_valid():
                    logger.info("Reused existing Inqom session")
                    return
                else:
                    logger.info("Stored session expired, re-authenticating")
                    self._context.close()
            except Exception as e:
                logger.warning(f"Failed to restore session: {e}")

        # Fresh login
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._login()

    def close(self):
        """Save session state and close browser."""
        if self._context:
            try:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                self._context.storage_state(path=str(self.state_file))
            except Exception as e:
                logger.warning(f"Failed to save session state: {e}")
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _is_session_valid(self) -> bool:
        """Check if the stored session is still valid."""
        try:
            self._page.goto(INQOM_HOME_URL, wait_until="networkidle", timeout=15000)
            self._dismiss_cookie_banner()
            # If we're redirected to login, session is expired
            return "/login" not in self._page.url
        except Exception:
            return False

    def _dismiss_cookie_banner(self):
        """Dismiss cookie consent banner by accepting all cookies."""
        accept_all_selectors = [
            "button:has-text('Tout accepter')",
            "button:has-text('Accepter tout')",
            "button:has-text('Accept all')",
            "button:has-text('Autoriser tous')",
            "button:has-text('J'accepte')",
            "button:has-text('Accepter et fermer')",
            "[id*='accept-all']",
            "[class*='accept-all']",
            "[data-testid*='accept-all']",
            "button:has-text('Accepter')",
            "button:has-text('Accept')",
            "button:has-text('OK')",
        ]
        for selector in accept_all_selectors:
            try:
                btn = self._page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    self._page.wait_for_timeout(500)
                    logger.info(f"Accepted all cookies via: {selector}")
                    return
            except Exception:
                continue

    def _login(self):
        """Perform email/password login."""
        logger.info("Logging in to Inqom...")
        self._page.goto(INQOM_LOGIN_URL, wait_until="networkidle", timeout=30000)

        # Dismiss cookie banner if present
        self._dismiss_cookie_banner()

        # Wait for the login form to be ready
        self._page.wait_for_selector("input[type='email'], input[name='email'], input[type='text']", timeout=15000)

        # Fill email
        email_input = self._page.locator("input[type='email'], input[name='email'], input[type='text']").first
        email_input.fill(self.email)

        # Look for password field (might appear after email submission)
        password_input = self._page.locator("input[type='password']").first
        if password_input.is_visible():
            password_input.fill(self.password)
        else:
            # Some flows show password after email "next" step
            self._page.locator("button[type='submit'], button:has-text('Suivant'), button:has-text('Next')").first.click()
            self._page.wait_for_selector("input[type='password']", timeout=10000)
            self._page.locator("input[type='password']").first.fill(self.password)

        # Submit
        self._page.locator("button[type='submit'], button:has-text('Connexion'), button:has-text('Se connecter'), button:has-text('Log in')").first.click()

        # Wait for navigation to complete (redirect away from login)
        self._page.wait_for_url(lambda url: "/login" not in url, timeout=30000)
        # Wait for the SPA to fully stabilize after login
        self._page.wait_for_load_state("networkidle", timeout=15000)
        self._page.wait_for_timeout(5000)
        logger.info(f"Login successful, landed on: {self._page.url}")

        # Save session state
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(self.state_file))

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

    def navigate_to_upload(self, doc_type: str = "SupplierBill"):
        """Navigate to the document upload section for the given type."""
        page = self._page
        begin_date, end_date = self._fiscal_year_dates()

        # Force full-page navigation using the absolute URL
        pieces_url = (
            f"https://home.inqom.com/clients/{self.client_id}/gestion/accounting-documents"
            f"?begin_date={begin_date}&end_date={end_date}"
        )
        logger.info(f"Forcing navigation to: {pieces_url}")
        page.evaluate(f"window.location.assign('{pieces_url}')")

        # Wait for navigation
        try:
            page.wait_for_url("**/accounting-documents**", timeout=20000)
        except Exception:
            # If wait_for_url fails, check manually
            page.wait_for_timeout(5000)
            if "accounting-documents" not in page.url:
                raise InqomUploadError(
                    f"Navigation failed. Still on: {page.url}"
                )

        page.wait_for_load_state("networkidle", timeout=15000)
        logger.info(f"After navigating to Pièces: {page.url}")

    def upload_document(self, file_path: Path, doc_type: str = "SupplierBill") -> dict:
        """
        Upload a single document to Inqom.

        Args:
            file_path: Path to the PDF file to upload.
            doc_type: Document type (SupplierBill, ClientBill, ExpenseReport, Other).

        Returns:
            Dict with upload result info.
        """
        if not file_path.exists():
            raise InqomUploadError(f"File not found: {file_path}")

        page = self._page

        # Each upload zone is a div[role="presentation"] containing a label and a hidden input[type="file"]
        # Find the correct zone by matching the label text
        type_labels = {
            "SupplierBill": "Factures d'achat",
            "ClientBill": "Factures de vente",
            "ExpenseReport": "Notes de frais",
            "Other": "Autres",
        }
        label = type_labels.get(doc_type, type_labels["SupplierBill"])

        # Locate the drop zone div that contains the label, then find its file input
        drop_zone = page.locator(f"div[role='presentation']:has(span:has-text('{label}'))").first
        try:
            file_input = drop_zone.locator("input[type='file']").first
            file_input.set_input_files(str(file_path))
            logger.info(f"Uploaded '{file_path.name}' to '{label}' zone")
        except Exception as e:
            raise InqomUploadError(
                f"Could not upload to '{label}' zone: {e}. Current URL: {page.url}"
            )

        # Wait for upload to process
        page.wait_for_timeout(3000)

        # Confirm/submit if needed
        self._try_confirm_upload()

        return {
            "file": file_path.name,
            "status": "uploaded",
        }

    def _try_set_doc_type(self, doc_type: str):
        """Try to set document type in the UI if a selector is available."""
        page = self._page
        type_map = {
            "SupplierBill": ["Facture fournisseur", "Achat", "Supplier"],
            "ClientBill": ["Facture client", "Vente", "Client"],
            "ExpenseReport": ["Note de frais", "Expense"],
            "Other": ["Autre", "Other"],
        }
        keywords = type_map.get(doc_type, [])

        for keyword in keywords:
            try:
                selector = page.locator(f"option:has-text('{keyword}'), [data-value*='{keyword}'], label:has-text('{keyword}')")
                if selector.count() > 0:
                    selector.first.click()
                    return
            except Exception:
                continue

    def _try_confirm_upload(self):
        """Try to click a confirm/validate button after upload."""
        page = self._page
        confirm_selectors = [
            "button:has-text('Valider')",
            "button:has-text('Confirmer')",
            "button:has-text('Envoyer')",
            "button:has-text('Submit')",
            "button[type='submit']",
        ]
        for selector in confirm_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(2000)
                    return
            except Exception:
                continue

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

        yield {"type": "status", "message": "Navigating to Inqom upload section…"}

        try:
            self.navigate_to_upload(doc_type)
        except InqomUploadError as e:
            yield {"type": "error", "error": str(e)}
            return

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
    Interactive exploration helper — launches visible browser for debugging.
    Navigates to Pièces and prints page structure.
    """
    with InqomUploader(email, password, headless=False) as uploader:
        page = uploader._page
        print(f"\n✅ Logged in. Current URL: {page.url}")

        # Try to navigate to Pièces
        print("\n⏳ Navigating to Pièces...")
        try:
            uploader.navigate_to_upload("SupplierBill")
            print(f"✅ Navigated to: {page.url}")
        except InqomUploadError as e:
            print(f"❌ Navigation failed: {e}")

        # Dump buttons on the page (to find upload buttons)
        print("\n=== Buttons on page ===")
        buttons = page.locator("button").all()
        for btn in buttons:
            try:
                text = (btn.text_content() or "").strip()[:80]
                cls = (btn.get_attribute("class") or "")[:60]
                if text:
                    print(f"  <button class='{cls}'> {text}")
            except Exception:
                pass

        print(f"\nCurrent URL: {page.url}")
        input("\nPress Enter to close browser...")
