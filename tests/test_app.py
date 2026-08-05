from pathlib import Path

from fastapi.testclient import TestClient

from compta_auto.app import create_app
from compta_auto.config import Settings
from compta_auto.routes.documents import _document_file_response as document_file_response, _preview_file_response as preview_file_response


def test_document_preview_is_served_inline(tmp_path: Path) -> None:
    raw = tmp_path / "invoice.pdf"
    raw.write_bytes(b"%PDF-1.4\n")

    response = document_file_response(str(raw), "invoice.pdf")

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"] == "inline"


def test_preview_response_has_no_content_disposition(tmp_path: Path) -> None:
    raw = tmp_path / "invoice.pdf"
    raw.write_bytes(b"%PDF-1.4\n")

    response = preview_file_response(str(raw), "invoice.pdf")

    assert response.media_type == "application/pdf"
    assert "content-disposition" not in response.headers


def test_henrri_environment_client_id_keeps_secret_field_visible(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "compta.sqlite3",
        raw_dir=tmp_path / "raw",
        renamed_dir=tmp_path / "renamed",
        output_dir=tmp_path / "output",
        henrri_client_id="configured-in-environment",
        henrri_client_secret="",
    )

    response = TestClient(create_app(settings)).get("/")

    assert response.status_code == 200
    assert "Client ID from environment" in response.text
    assert 'id="henrri-client-id"' not in response.text
    assert 'id="henrri-client-secret"' in response.text
