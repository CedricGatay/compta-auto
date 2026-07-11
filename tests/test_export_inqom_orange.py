from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from compta_auto.config import Settings
from compta_auto.db import SCHEMA
from compta_auto.inqom_upload import list_inqom_upload_candidates
from compta_auto.orange_invoices import _fetch_bills, _fetch_json, _get_contract_id
from compta_auto.providers.base import AuthError
from compta_auto.repositories import Repository
from compta_auto.routes.documents import api_export, api_export_preview


def make_repo() -> Repository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return Repository(conn)


def add_export_document(
    repo: Repository,
    raw_path: Path,
    *,
    status: str,
    content_hash: str,
    accounting_type: str = "purchase",
) -> int:
    doc_id, _ = repo.add_document(
        source_type="local_folder",
        source_id=str(raw_path),
        original_filename=raw_path.name,
        raw_path=str(raw_path),
        content_hash=content_hash,
        mime_type="application/pdf",
        status=status,
    )
    repo.update_document_metadata(doc_id, "OpenAI", "2026-06-09", 1.0, "test", status)
    repo.update_document_accounting_type(doc_id, accounting_type)
    return doc_id


def test_export_includes_uploaded_to_inqom_documents(tmp_path: Path) -> None:
    repo = make_repo()
    settings = Settings(
        db_path=tmp_path / "db.sqlite3",
        raw_dir=tmp_path / "raw",
        renamed_dir=tmp_path / "renamed",
        output_dir=tmp_path / "output",
        use_apple_llm=False,
    )
    included = tmp_path / "included.pdf"
    uploaded = tmp_path / "uploaded.pdf"
    included.write_bytes(b"%PDF included")
    uploaded.write_bytes(b"%PDF uploaded")
    included_id = add_export_document(repo, included, status="doc_included", content_hash="h1")
    uploaded_id = add_export_document(
        repo, uploaded, status="uploaded_to_inqom", content_hash="h2"
    )

    preview = api_export_preview(repo)
    result = api_export(repo, settings)

    assert preview["total"] == 2
    assert result["moved"] == 2
    assert repo.get_document(included_id)["status"] == "exported"
    assert repo.get_document(uploaded_id)["status"] == "exported"
    assert (settings.output_dir / "2026" / "06" / included.name).exists()
    assert (settings.output_dir / "2026" / "06" / uploaded.name).exists()


def test_inqom_candidates_exclude_already_uploaded_documents(tmp_path: Path) -> None:
    repo = make_repo()
    included = tmp_path / "included.pdf"
    uploaded = tmp_path / "uploaded.pdf"
    included.write_bytes(b"%PDF included")
    uploaded.write_bytes(b"%PDF uploaded")
    included_id = add_export_document(repo, included, status="doc_included", content_hash="h1")
    add_export_document(repo, uploaded, status="uploaded_to_inqom", content_hash="h2")

    candidates = list_inqom_upload_candidates(repo)

    assert [candidate["id"] for candidate in candidates] == [included_id]


class FakePage:
    def __init__(self, result: dict):
        self.result = result

    def evaluate(self, *_args):
        return self.result


def test_orange_fetch_json_reports_non_json_response() -> None:
    page = FakePage(
        {
            "ok": False,
            "status": 200,
            "contentType": "text/html",
            "parseError": "Unexpected token '<'",
            "text": "<html>login</html>",
        }
    )

    with pytest.raises(AuthError, match="Orange bills API returned an unexpected response"):
        _fetch_json(page, "/bills", {}, "Orange bills API")


def test_orange_contract_and_bills_validate_shapes() -> None:
    contract_page = FakePage(
        {"ok": True, "status": 200, "contentType": "application/json", "data": {"contracts": {}}}
    )
    bills_page = FakePage(
        {
            "ok": True,
            "status": 200,
            "contentType": "application/json",
            "data": {"billsHistory": {"billList": {}}},
        }
    )

    with pytest.raises(AuthError, match="contracts shape"):
        _get_contract_id(contract_page)
    with pytest.raises(AuthError, match="billList shape"):
        _fetch_bills(bills_page, "contract-1")
