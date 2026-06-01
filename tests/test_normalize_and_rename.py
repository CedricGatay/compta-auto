from pathlib import Path

from compta_auto.models import ExtractedMetadata
from compta_auto.normalize import normalize_url, normalize_vendor, safe_filename_stem
from compta_auto.renamer import rename_document


def test_normalize_vendor_for_filename() -> None:
    assert normalize_vendor("OpenAI, LLC") == "openai_llc"
    assert normalize_vendor("Spotify & Co") == "spotify_and_co"
    assert safe_filename_stem("2026-05-29", "OpenAI, LLC") == "2026_05_29_openai_llc"


def test_normalize_url_removes_tracking_params() -> None:
    assert (
        normalize_url("HTTPS://Example.com/invoices/?utm_source=x&invoice=123")
        == "https://example.com/invoices?invoice=123"
    )


def test_rename_document_adds_collision_suffix(tmp_path: Path) -> None:
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"fake pdf")
    output = tmp_path / "out"
    metadata = ExtractedMetadata("OpenAI", "2026-05-29", 0.95, "test")

    first = rename_document(source, metadata, output, 0.82)
    second = rename_document(source, metadata, output, 0.82)

    assert first is not None
    assert second is not None
    assert first[0] == "2026_05_29_openai.pdf"
    assert second[0] == "2026_05_29_openai_001.pdf"


def test_rename_document_requires_confidence(tmp_path: Path) -> None:
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"fake pdf")
    metadata = ExtractedMetadata("OpenAI", "2026-05-29", 0.5, "test")

    assert rename_document(source, metadata, tmp_path / "out", 0.82) is None

