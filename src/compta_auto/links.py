from __future__ import annotations

import re
from urllib.parse import urlsplit

from .normalize import email_domain, normalize_vendor

# Map domain segments or vendor slugs to canonical fetcher vendor names
VENDOR_ALIASES: dict[str, str] = {
    "freetelecom": "freebox",
    "free": "free_mobile",
    "engie": "engie",
    "sosh": "sosh",
    "orange": "orange",
    "spotify": "spotify",
    "openai": "openai",
    "ovh": "ovh",
    "ovhcloud": "ovh",
    "free-mobile": "free_mobile",
}


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

# URLs matching these patterns are NOT invoice downloads
INVOICE_LINK_EXCLUDES = (
    "support.apple.com",
    "toggle-renewal",
    "unsubscribe",
    "manage-subscription",
    "account/settings",
    "preferences",
    "help.apple.com",
    "mailto:",
)


def find_invoice_links(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s<>)\"']+", text)
    found: list[str] = []
    for url in urls:
        cleaned = url.rstrip(".,;]")
        haystack = cleaned.lower()
        if any(excl in haystack for excl in INVOICE_LINK_EXCLUDES):
            continue
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
            resolved = VENDOR_ALIASES.get(vendor) or normalize_vendor(vendor) or vendor
            return resolved
    domain = email_domain(sender)
    # Check full domain and parent domains for known aliases
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        candidate = parts[i]
        if candidate in VENDOR_ALIASES:
            return VENDOR_ALIASES[candidate]
    # Skip generic subdomains (email, noreply, billing, etc.) and use brand domain
    vendor = parts[0]
    if vendor in _GENERIC_SUBDOMAINS and len(parts) >= 3:
        vendor = parts[-2]
    resolved = VENDOR_ALIASES.get(vendor) or normalize_vendor(vendor) or vendor
    return resolved


_GENERIC_SUBDOMAINS = frozenset({
    "email", "mail", "noreply", "no-reply", "billing", "support", "info",
    "newsletter", "notifications", "accounts", "contact", "service",
    "messages", "alert", "alerts", "news", "updates",
})

