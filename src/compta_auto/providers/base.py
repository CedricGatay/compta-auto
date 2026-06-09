"""Shared utilities for invoice provider fetchers."""

from __future__ import annotations

import http.cookiejar
import json
import urllib.request
from typing import Generator


class AuthError(Exception):
    """Raised when authentication fails for a provider."""


def build_opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    """Create a urllib opener with cookie support and redirect handling."""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPRedirectHandler(),
    )
    return opener, cj


def serialize_cookies(cj: http.cookiejar.CookieJar) -> str:
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


def restore_cookies(cj: http.cookiejar.CookieJar, serialized: str) -> None:
    """Restore cookies from serialized JSON into a cookie jar."""
    cookies = json.loads(serialized)
    for c in cookies:
        cookie = http.cookiejar.Cookie(
            version=0,
            name=c["name"],
            value=c["value"],
            port=None,
            port_specified=False,
            domain=c["domain"],
            domain_specified=bool(c["domain"]),
            domain_initial_dot=c["domain"].startswith("."),
            path=c["path"],
            path_specified=bool(c["path"]),
            secure=False,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
        )
        cj.set_cookie(cookie)


# Type alias for the SSE event stream generators used by all fetchers
FetchEvent = dict[str, object]
FetchStream = Generator[FetchEvent, None, None]
