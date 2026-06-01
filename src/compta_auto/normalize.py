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
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or None


def safe_filename_stem(date_value: str, vendor: str) -> str:
    normalized_vendor = normalize_vendor(vendor) or "unknown_vendor"
    return f"{date_value.replace('-', '_')}_{normalized_vendor}"


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = re.sub(r"/+$", "", parts.path)
    ignored_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ignored_params]
    query = urlencode(sorted(params))
    return urlunsplit((scheme, host, path, query, ""))

