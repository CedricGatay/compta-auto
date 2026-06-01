from pathlib import Path

from compta_auto.app import document_file_response, preview_file_response


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
