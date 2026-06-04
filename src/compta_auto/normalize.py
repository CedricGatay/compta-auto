from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_email(value: str) -> str:
    return value.strip().lower()


def email_domain(value: str) -> str:
    value = normalize_email(value)
    if "@" not in value:
        return value
    return value.rsplit("@", 1)[1]


def normalize_vendor(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("&", " and ")
    # Remove common legal entity suffixes
    legal_suffixes = (
        r"\bs\.?a\.?s\.?\b", r"\bs\.?a\.?\b", r"\bs\.?a\.?r\.?l\.?\b",
        r"\be\.?u\.?r\.?l\.?\b", r"\bs\.?c\.?i\.?\b", r"\bs\.?n\.?c\.?\b",
        r"\bgmbh\b", r"\bltd\.?\b", r"\binc\.?\b", r"\bcorp\.?\b",
        r"\bllc\b", r"\bplc\b", r"\bn\.?v\.?\b", r"\bb\.?v\.?\b",
        r"\bse\b", r"\bgroup\b", r"\bgroupe\b",
    )
    for suffix in legal_suffixes:
        cleaned = re.sub(suffix, "", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    # Truncate to first meaningful segment (max 30 chars)
    if len(cleaned) > 30:
        cleaned = cleaned[:30].rstrip("_")
    return cleaned or None


def safe_filename_stem(date_value: str, vendor: str) -> str:
    normalized_vendor = normalize_vendor(vendor) or "unknown_vendor"
    safe_date = date_value.replace("-", "_").replace("/", "_")
    return f"{safe_date}_{normalized_vendor}"


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = re.sub(r"/+$", "", parts.path)
    ignored_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ignored_params]
    query = urlencode(sorted(params))
    return urlunsplit((scheme, host, path, query, ""))

