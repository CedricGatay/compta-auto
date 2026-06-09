from __future__ import annotations

SALE_VENDOR_MARKERS = (
    "SALE_MARKER_1",
    "SALE_MARKER_2",
    "SALE_MARKER_3",
    "SALE_MARKER_4",
)


def auto_categorize_document(doc: dict) -> str:
    """Infer accounting_type from extracted vendor/recipient hints."""
    searchable_text = " ".join(
        str(doc.get(key) or "")
        for key in ("detected_vendor", "vendor", "recipient", "detected_recipient")
    ).casefold()
    if any(marker in searchable_text for marker in SALE_VENDOR_MARKERS):
        return "sale"
    return "purchase"
