from compta_auto.extraction import find_date, heuristic_extract


def test_find_date_accepts_iso_and_french_formats() -> None:
    assert find_date("invoice 2026-05-29") == "2026-05-29"
    assert find_date("facture du 29/05/2026") == "2026-05-29"


def test_heuristic_extract_uses_sender_vendor(tmp_path) -> None:
    path = tmp_path / "invoice_2026-05-29.pdf"
    path.write_bytes(b"")

    metadata = heuristic_extract(path, "", "Your invoice", "billing@openai.com")

    assert metadata.date == "2026-05-29"
    assert metadata.vendor == "openai"
    assert metadata.confidence >= 0.8

