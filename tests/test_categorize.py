from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from compta_auto.config import Settings
from compta_auto.db import SCHEMA
from compta_auto.pipeline import AccountingPipeline
from compta_auto.repositories import Repository
from compta_auto.services.fetch_service import auto_categorize_document

TEST_SALE_MARKERS = "testsale,othersale"


@pytest.fixture(autouse=True)
def _set_test_sale_markers(monkeypatch):
    """Override sale markers for tests to avoid depending on .env."""
    monkeypatch.setenv("COMPTA_SALE_VENDOR_MARKERS", TEST_SALE_MARKERS)


@pytest.mark.parametrize(
    ("detected_vendor", "expected"),
    [
        ("testsale corp", "sale"),
        ("TESTSALE Inc", "sale"),
        ("othersale", "sale"),
        ("OtherSale Ltd", "sale"),
        ("openai", "purchase"),
        (None, "purchase"),
    ],
)
def test_auto_categorize_document(detected_vendor: str | None, expected: str) -> None:
    assert auto_categorize_document({"detected_vendor": detected_vendor}) == expected


def test_categorize_uncategorized_documents_updates_existing_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    repo = Repository(conn)

    sale_doc_id, _ = repo.add_document(
        source_type="local_folder",
        source_id="raw",
        original_filename="sale.pdf",
        raw_path="data/raw/sale.pdf",
        content_hash="hash-sale",
        mime_type="application/pdf",
        status="attachment_extracted",
    )
    repo.update_document_metadata(
        sale_doc_id, "testsale corp", "2026-06-09", 0.95, "test", "rename_needed"
    )

    purchase_doc_id, _ = repo.add_document(
        source_type="local_folder",
        source_id="raw",
        original_filename="purchase.pdf",
        raw_path="data/raw/purchase.pdf",
        content_hash="hash-purchase",
        mime_type="application/pdf",
        status="attachment_extracted",
    )
    repo.update_document_metadata(
        purchase_doc_id, "openai", "2026-06-09", 0.95, "test", "rename_needed"
    )

    settings = Settings(
        db_path=Path("data/test.sqlite3"),
        raw_dir=Path("data/raw"),
        renamed_dir=Path("data/renamed"),
        output_dir=Path("data/output"),
        use_apple_llm=False,
        sale_vendor_markers=TEST_SALE_MARKERS,
    )
    pipeline = AccountingPipeline(settings, repo, spark=object(), extractor=object())

    assert pipeline.categorize_uncategorized_documents() == 2
    assert repo.get_document(sale_doc_id)["accounting_type"] == "sale"
    assert repo.get_document(purchase_doc_id)["accounting_type"] == "purchase"
