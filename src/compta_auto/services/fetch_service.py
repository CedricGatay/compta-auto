"""Generic SSE fetch + pipeline processing orchestrator.

Eliminates duplication across all provider fetch endpoints by providing
a single function that handles the common pattern:
  1. Stream events from a provider fetcher
  2. Yield progress/status events as SSE
  3. Run pipeline scan on downloaded files
  4. Yield final complete/error event
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from datetime import datetime

from ..config import Settings
from ..pipeline import AccountingPipeline
from ..providers.base import AuthError
from ..repositories import Repository
from .categorize import auto_categorize_document

logger = logging.getLogger(__name__)

__all__ = ["auto_categorize_document", "run_provider_fetch"]


def _set_accounting_type_on_recent(repo: Repository, vendor: str, accounting_type: str) -> None:
    """Set accounting_type on documents for this vendor that don't have one yet."""
    repo.conn.execute(
        """
        UPDATE documents
        SET accounting_type = ?, updated_at = CURRENT_TIMESTAMP
        WHERE detected_vendor = ? AND accounting_type IS NULL
        """,
        (accounting_type, vendor),
    )


def run_provider_fetch(
    fetch_stream: Generator[dict, None, None],
    settings: Settings,
    repo: Repository,
    vendor: str,
    *,
    accounting_type: str = "purchase",
    auth_error_types: tuple[type[Exception], ...] = (AuthError,),
) -> Generator[str, None, None]:
    """Generic SSE event stream for provider fetching.

    Args:
        fetch_stream: Generator yielding events from a provider fetcher.
        settings: Application settings.
        repo: Repository instance (caller manages connection lifecycle).
        vendor: Vendor name for pipeline processing and state tracking.
        accounting_type: Default accounting type for fetched documents ('purchase' or 'sale').
        auth_error_types: Exception types to treat as auth failures.

    Yields:
        SSE-formatted strings (data: {...}\n\n).
    """
    try:
        result = {"total": 0, "downloaded": 0, "skipped": 0, "errors": []}
        for event in fetch_stream:
            if event["type"] in ("progress", "status"):
                yield f"data: {json.dumps(event)}\n\n"
            elif event["type"] == "done":
                result = event["result"]
            elif event["type"] == "error":
                yield f"data: {json.dumps(event)}\n\n"
                return
        # Process through pipeline
        if result.get("downloaded", 0) > 0:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing documents…'})}\n\n"
            pipeline = AccountingPipeline(settings, repo)
            scan_summary = pipeline.run_folder_scan(
                settings.raw_dir, max_age_days=730, known_vendor=vendor,
            )
            result["processed"] = scan_summary.renamed + scan_summary.rename_review_needed
            # Set accounting type on newly processed documents
            if accounting_type:
                _set_accounting_type_on_recent(repo, vendor, accounting_type)
        repo.set_app_state(f"last_fetch_{vendor}", datetime.now().isoformat(timespec="minutes"))
        yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
    except tuple(auth_error_types) as exc:
        yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
    except Exception:
        logger.exception("Provider fetch failed for %s", vendor)
        yield f"data: {json.dumps({'type': 'error', 'error': 'An unexpected error occurred. Check server logs.'})}\n\n"
