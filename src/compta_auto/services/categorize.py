from __future__ import annotations

from ..config import get_settings


def _get_sale_markers() -> tuple[str, ...]:
    """Load sale vendor markers from settings."""
    raw = get_settings().sale_vendor_markers
    if not raw:
        return ()
    return tuple(m.strip().casefold() for m in raw.split(",") if m.strip())


def auto_categorize_document(doc: dict) -> str:
    """Infer accounting_type from extracted vendor/recipient hints."""
    markers = _get_sale_markers()
    if not markers:
        return "purchase"
    searchable_text = " ".join(
        str(doc.get(key) or "")
        for key in ("detected_vendor", "vendor", "recipient", "detected_recipient")
    ).casefold()
    if any(marker in searchable_text for marker in markers):
        return "sale"
    return "purchase"
