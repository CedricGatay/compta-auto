from __future__ import annotations

import re
from urllib.parse import urlsplit

from .normalize import email_domain, normalize_vendor


INVOICE_LINK_TERMS = (
    "invoice",
    "facture",
    "receipt",
    "billing",
    "payment",
    "paiement",
    "download",
    "telecharger",
    "télécharger",
)


def find_invoice_links(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>)\"']+", text)
    found: list[str] = []
    for url in urls:
        cleaned = url.rstrip(".,;]")
        haystack = cleaned.lower()
        if any(term in haystack for term in INVOICE_LINK_TERMS):
            found.append(cleaned)
    return list(dict.fromkeys(found))


def provider_from_sender_or_url(sender: str, url: str | None = None) -> str:
    if url:
        host = urlsplit(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        vendor = host.split(".")[0]
        if vendor:
            return normalize_vendor(vendor) or vendor
    domain = email_domain(sender)
    vendor = domain.split(".")[0]
    return normalize_vendor(vendor) or vendor

