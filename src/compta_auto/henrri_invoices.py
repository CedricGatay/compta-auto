"""Henrri invoice retrieval service via sandbox API."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator


HENRRI_SANDBOX_BASE = "https://api-sandbox.henrri.io/v1"
_ALLOWED_DOWNLOAD_HOSTS_SUFFIX = ".henrri.io"
_MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB
_REQUEST_TIMEOUT = 30  # seconds
TOKEN_TTL_SECONDS = 600


@dataclass
class HenrriToken:
    access_token: str
    refresh_token: str
    expires_at: float


class HenrriClient:
    """Client for the Henrri sandbox API."""

    def __init__(self, client_id: str, client_secret: str, base_url: str = HENRRI_SANDBOX_BASE):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self._token: HenrriToken | None = None

    def _authenticate(self) -> HenrriToken:
        url = f"{self.base_url}/users/authenticate"
        payload = json.dumps({
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
        }).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        return HenrriToken(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + data.get("expires_in", TOKEN_TTL_SECONDS) - 30,
        )

    def _get_token(self) -> str:
        if self._token is None or time.time() >= self._token.expires_at:
            self._token = self._authenticate()
        return self._token.access_token

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            if filtered:
                url += "?" + urllib.parse.urlencode(filtered, doseq=True)
        token = self._get_token()
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    def list_documents(
        self,
        *,
        page: int = 1,
        limit: int = 50,
        document_types: list[str] | None = None,
        finalized: bool | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> dict[str, Any]:
        """List documents (invoices, quotes, etc.) with pagination."""
        params: dict[str, Any] = {
            "page": page,
            "limit": limit,
        }
        if document_types:
            params["documentTypes"] = document_types
        if finalized is not None:
            params["finalized"] = str(finalized).lower()
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        if sort_by:
            params["sortBy"] = sort_by
        if sort_order:
            params["sortOrder"] = sort_order
        return self._request("GET", "/documents", params)

    def list_invoices(
        self,
        *,
        page: int = 1,
        limit: int = 50,
        finalized: bool | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        """List only Invoice-type documents."""
        return self.list_documents(
            page=page,
            limit=limit,
            document_types=["Invoice"],
            finalized=finalized,
            from_date=from_date,
            to_date=to_date,
            sort_by="date",
            sort_order="descending",
        )

    def get_document(self, document_id: int) -> dict[str, Any]:
        """Get a single document by ID."""
        return self._request("GET", f"/documents/{document_id}")

    def get_pdf_url(self, document_id: int) -> dict[str, Any]:
        """Generate PDF and get a temporary download URL (valid 10 min)."""
        url = f"{self.base_url}/documents/{document_id}/pdf/url"
        token = self._get_token()
        req = urllib.request.Request(
            url,
            data=b"",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Length": "0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    def download_pdf(self, document_id: int, output_path: Path) -> Path:
        """Download document PDF to a local file. Returns the output path."""
        pdf_info = self.get_pdf_url(document_id)
        download_url = pdf_info["downloadUrl"]

        # Validate URL to prevent SSRF
        parsed = urllib.parse.urlparse(download_url)
        if parsed.scheme != "https" or not (
            parsed.hostname and (
                parsed.hostname == "henrri.io"
                or parsed.hostname.endswith(_ALLOWED_DOWNLOAD_HOSTS_SUFFIX)
            )
        ):
            raise ValueError(
                f"Refusing to download from untrusted URL: {download_url}"
            )

        token = self._get_token()
        req = urllib.request.Request(
            download_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/octet-stream",
            },
            method="GET",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            # Stream to file with size cap to avoid memory exhaustion
            with open(output_path, "wb") as f:
                bytes_written = 0
                while chunk := resp.read(8192):
                    bytes_written += len(chunk)
                    if bytes_written > _MAX_PDF_SIZE:
                        f.close()
                        output_path.unlink(missing_ok=True)
                        raise ValueError(
                            f"PDF for document {document_id} exceeds {_MAX_PDF_SIZE // (1024*1024)}MB limit"
                        )
                    f.write(chunk)
        return output_path


def list_henrri_invoices(
    client_id: str,
    client_secret: str,
    *,
    base_url: str = HENRRI_SANDBOX_BASE,
    limit: int = 50,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict[str, Any]]:
    """Convenience function: fetch all invoices and return simplified records."""
    client = HenrriClient(client_id, client_secret, base_url=base_url)
    result = client.list_invoices(limit=limit, from_date=from_date, to_date=to_date)

    invoices = []
    for doc in result.get("elements", []):
        customer = doc.get("customer") or {}
        invoices.append({
            "id": doc.get("id"),
            "number": doc.get("identity"),
            "type": doc.get("type"),
            "title": doc.get("title"),
            "date": doc.get("date"),
            "customer_name": customer.get("name", "N/A"),
            "customer_id": doc.get("customerId"),
            "price_ht": doc.get("priceBeforeTax"),
            "tax": doc.get("taxAmount"),
            "price_ttc": doc.get("priceAfterTax"),
            "finalized": doc.get("finalized"),
        })
    return invoices


def fetch_henrri_invoices_stream(
    client_id: str,
    client_secret: str,
    output_dir: Path,
    *,
    base_url: str = HENRRI_SANDBOX_BASE,
) -> Generator[dict, None, None]:
    """Fetch all finalized Henrri invoices as PDFs.

    Yields progress events compatible with run_provider_fetch.
    """
    env_label = "sandbox" if "sandbox" in base_url else "production"
    yield {"type": "status", "message": f"Connecting to Henrri API ({env_label})…"}

    try:
        client = HenrriClient(client_id, client_secret, base_url=base_url)
        # Fetch all finalized invoices (paginate)
        all_docs: list[dict[str, Any]] = []
        page = 1
        while True:
            result = client.list_documents(
                page=page,
                limit=50,
                document_types=["Invoice"],
                finalized=True,
                sort_by="date",
                sort_order="descending",
            )
            elements = result.get("elements", [])
            all_docs.extend(elements)
            meta = result.get("meta", {})
            if not meta.get("hasNext", False):
                break
            page += 1
    except urllib.error.HTTPError as e:
        yield {"type": "error", "error": f"Henrri API error: {e.code} {e.reason}"}
        return
    except Exception as e:
        yield {"type": "error", "error": f"Henrri connection error: {e}"}
        return

    if not all_docs:
        yield {"type": "done", "result": {
            "total": 0, "downloaded": 0, "skipped": 0, "errors": [],
            "message": "No finalized invoices found on Henrri.",
        }}
        return

    yield {"type": "status", "message": f"Found {len(all_docs)} invoice(s), downloading PDFs…"}
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(all_docs)
    downloaded = 0
    skipped = 0
    errors: list[str] = []

    for i, doc in enumerate(all_docs, 1):
        doc_id = doc["id"]
        identity = doc.get("identity") or f"doc-{doc_id}"
        date_str = (doc.get("date") or "")[:10].replace("-", "_")
        customer = (doc.get("customer") or {}).get("name", "henrri")
        safe_customer = customer.replace(" ", "_").replace("/", "-")[:20]
        safe_identity = identity.replace("/", "-").replace(" ", "_")
        filename = f"henrri_{date_str}_{safe_customer}_{safe_identity}.pdf"
        output_path = output_dir / filename

        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "message": f"Processing invoice {i}/{total} ({identity})…",
        }

        if output_path.exists():
            skipped += 1
            continue

        try:
            client.download_pdf(doc_id, output_path)
            downloaded += 1
        except Exception as e:
            errors.append(f"{identity}: {e}")

    yield {"type": "done", "result": {
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }}
