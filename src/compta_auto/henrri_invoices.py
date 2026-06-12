"""Henrri invoice retrieval service via sandbox API."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


HENRRI_SANDBOX_BASE = "https://api-sandbox.henrri.io/v1"
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
        with urllib.request.urlopen(req) as resp:
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
        with urllib.request.urlopen(req) as resp:
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


def list_henrri_invoices(
    client_id: str,
    client_secret: str,
    *,
    limit: int = 50,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict[str, Any]]:
    """Convenience function: fetch all invoices and return simplified records."""
    client = HenrriClient(client_id, client_secret)
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
