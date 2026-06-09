from pathlib import Path

from compta_auto.config import Settings
from compta_auto.db import Database
from compta_auto.models import Attachment, MailMessage
from compta_auto.pipeline import AccountingPipeline, RunSummary
from compta_auto.renamer import rename_document_as
from compta_auto.repositories import Repository


class FakeSpark:
    def __init__(self, messages: list[MailMessage]):
        self.messages = messages

    def search_candidate_ids(self, months: int = 1) -> list[str]:
        return [message.spark_message_id for message in self.messages]

    def read_thread(self, message_id: str, download_attachments: bool = True) -> list[MailMessage]:
        return [message for message in self.messages if message.spark_message_id == message_id]


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "db.sqlite3",
        raw_dir=tmp_path / "raw",
        renamed_dir=tmp_path / "renamed",
        accounting_domain="ACCOUNTING_DOMAIN_PLACEHOLDER",
    )


def make_repo(settings: Settings) -> Repository:
    db = Database(settings.db_path)
    db.init()
    conn = db.connect()
    return Repository(conn)


def test_accounting_domain_recipient_is_auto_processed_and_renamed(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    source = tmp_path / "openai_invoice_2026-05-29.pdf"
    source.write_text("invoice from OpenAI\nDate: 2026-05-29")
    message = MailMessage(
        spark_message_id="100",
        sender="billing@openai.com",
        recipients=["accounting@ACCOUNTING_DOMAIN_PLACEHOLDER"],
        subject="Invoice 2026-05-29",
        sent_at="2026-05-29",
        attachments=[Attachment(filename=source.name, path=source)],
    )
    repo = make_repo(settings)

    try:
        summary = AccountingPipeline(settings, repo, spark=FakeSpark([message])).run_mail_scan()
        repo.conn.commit()

        docs = repo.list_documents()
        assert summary.new_mails == 1
        assert summary.renamed == 1
        assert docs[0]["status"] == "renamed"
        assert docs[0]["final_filename"] == "2026_05_29_openai.pdf"
    finally:
        repo.conn.close()


def test_non_accounting_domain_candidate_goes_to_triage(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    attachment = tmp_path / "spotify_invoice.pdf"
    attachment.write_text("invoice")
    message = MailMessage(
        spark_message_id="101",
        sender="billing@spotify.com",
        recipients=["me@example.com"],
        subject="Your invoice",
        sent_at=None,
        attachments=[Attachment(filename=attachment.name, path=attachment)],
    )
    repo = make_repo(settings)

    try:
        summary = RunSummary()
        AccountingPipeline(settings, repo, spark=FakeSpark([message])).process_message(message, summary)
        repo.conn.commit()

        mails = repo.list_mails()
        assert summary.triage_mails == 1
        assert mails[0]["status"] == "mail_triage_needed"
        assert mails[0]["attachments"][0]["filename"] == "spotify_invoice.pdf"
        assert mails[0]["attachments"][0]["preview_label"] == "PDF"
    finally:
        repo.conn.close()


def test_mail_without_attachment_displays_download_link(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    message = MailMessage(
        spark_message_id="101-link",
        sender="billing@provider.com",
        recipients=["me@example.com"],
        subject="Your invoice is ready",
        sent_at=None,
        body="Your invoice is ready: https://provider.example.com/invoices/12345/download",
    )
    repo = make_repo(settings)

    try:
        summary = RunSummary()
        AccountingPipeline(settings, repo, spark=FakeSpark([message])).process_message(message, summary)
        repo.conn.commit()

        mail = repo.list_mails()[0]
        assert mail["status"] == "mail_triage_needed"
        assert mail["preview_items"][0]["type"] == "link"
        assert mail["preview_items"][0]["url"] == "https://provider.example.com/invoices/12345/download"
        assert mail["preview_items"][0]["display_name"].startswith("provider.example.com/invoices/12345")
    finally:
        repo.conn.close()


def test_saved_sender_rule_auto_processes_future_mail(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    # Mail WITH an invoice link should be auto-selected
    message = MailMessage(
        spark_message_id="102",
        sender="billing@spotify.com",
        recipients=["me@example.com"],
        subject="Your invoice",
        sent_at=None,
        body="Download your invoice: https://spotify.com/invoices/123/download",
    )
    repo = make_repo(settings)

    try:
        repo.add_rule("always_process", "sender", "billing@spotify.com", "Spotify")
        summary = RunSummary()
        AccountingPipeline(settings, repo, spark=FakeSpark([message])).process_message(message, summary)
        repo.conn.commit()

        mails = repo.list_mails()
        assert mails[0]["status"] == "mail_auto_selected"
        assert mails[0]["detected_vendor"] == "spotify"
    finally:
        repo.conn.close()


def test_always_process_rule_without_attachment_goes_to_provider_hint(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    # Mail WITHOUT attachments from known provider → provider hint (badge on fetch)
    message = MailMessage(
        spark_message_id="103",
        sender="billing@spotify.com",
        recipients=["me@example.com"],
        subject="Your invoice",
        sent_at=None,
    )
    repo = make_repo(settings)

    try:
        repo.add_rule("always_process", "sender", "billing@spotify.com", "Spotify")
        summary = RunSummary()
        AccountingPipeline(settings, repo, spark=FakeSpark([message])).process_message(message, summary)
        repo.conn.commit()

        mails = repo.list_mails()
        assert mails[0]["status"] == "mail_provider_hint"
        assert mails[0]["detected_vendor"] == "spotify"
    finally:
        repo.conn.close()


def test_rule_can_be_deleted(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repo = make_repo(settings)

    try:
        rule_id = repo.add_rule("ignore", "domain", "example.com")
        repo.conn.commit()
        assert len(repo.list_rules()) == 1

        repo.delete_rule(rule_id)
        repo.conn.commit()
        assert repo.list_rules() == []
    finally:
        repo.conn.close()


def test_auto_selected_mail_can_be_moved_back_to_triage(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repo = make_repo(settings)

    try:
        mail_id, _ = repo.upsert_mail(
            spark_message_id="auto-selected",
            sender="billing@example.com",
            recipients=["accounting@ACCOUNTING_DOMAIN_PLACEHOLDER"],
            subject="Invoice",
            sent_at=None,
            body="",
            status="mail_auto_selected",
            detected_vendor="example",
            extraction_reason="test",
        )

        repo.update_mail_status(mail_id, "mail_triage_needed")
        repo.conn.commit()

        assert repo.get_mail(mail_id)["status"] == "mail_triage_needed"
    finally:
        repo.conn.close()


def test_duplicate_message_and_attachment_are_not_reprocessed(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    source = tmp_path / "openai_invoice_2026-05-29.pdf"
    source.write_text("invoice from OpenAI\nDate: 2026-05-29")
    message = MailMessage(
        spark_message_id="103",
        sender="billing@openai.com",
        recipients=["accounting@ACCOUNTING_DOMAIN_PLACEHOLDER"],
        subject="Invoice 2026-05-29",
        sent_at="2026-05-29",
        attachments=[Attachment(filename=source.name, path=source)],
    )
    repo = make_repo(settings)

    try:
        pipeline = AccountingPipeline(settings, repo, spark=FakeSpark([message]))
        first = pipeline.run_mail_scan()
        second = pipeline.run_mail_scan()
        repo.conn.commit()

        assert first.renamed == 1
        assert second.renamed == 0
        assert second.duplicates_skipped == 1
        assert len(repo.list_documents()) == 1
    finally:
        repo.conn.close()


def test_existing_blank_mail_metadata_is_refreshed_on_rerun(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    message = MailMessage(
        spark_message_id="103-refresh",
        sender="billing@openai.com",
        recipients=["accounting@ACCOUNTING_DOMAIN_PLACEHOLDER"],
        subject="Invoice 2026-05-29",
        sent_at="2026-05-29",
    )
    repo = make_repo(settings)

    try:
        repo.upsert_mail(
            spark_message_id="103-refresh",
            sender="",
            recipients=[],
            subject="",
            sent_at=None,
            body="",
            status="mail_auto_selected",
            detected_vendor=None,
            extraction_reason="old_parser",
        )
        AccountingPipeline(settings, repo, spark=FakeSpark([message])).run_mail_scan()
        repo.conn.commit()

        mail = repo.list_mails()[0]
        assert mail["sender"] == "billing@openai.com"
        assert mail["recipients_display"] == "accounting@accounting_domain_placeholder"
        assert mail["subject"] == "Invoice 2026-05-29"
        assert mail["detected_vendor"] == "openai"
    finally:
        repo.conn.close()


def test_provider_task_is_deduplicated(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repo = make_repo(settings)

    try:
        first = repo.add_provider_task("OpenAI", "https://example.com/invoice?utm_source=x&id=1", None, "provider_manual_link")
        second = repo.add_provider_task("openai", "https://example.com/invoice?id=1", None, "provider_manual_link")
        repo.conn.commit()

        assert first[1] is True
        assert second[1] is False
        assert len(repo.list_provider_tasks()) == 1
    finally:
        repo.conn.close()


def test_document_rows_include_source_and_supposed_filename(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repo = make_repo(settings)

    try:
        mail_id, _ = repo.upsert_mail(
            spark_message_id="104",
            sender="billing@openai.com",
            recipients=["accounting@ACCOUNTING_DOMAIN_PLACEHOLDER"],
            subject="Invoice",
            sent_at=None,
            body="",
            status="mail_auto_selected",
            detected_vendor="openai",
            extraction_reason="test",
        )
        doc_id, _ = repo.add_document(
            source_type="mail_attachment",
            source_id=str(mail_id),
            original_filename="invoice.pdf",
            raw_path=str(tmp_path / "invoice.pdf"),
            content_hash="hash",
            mime_type="application/pdf",
            status="rename_review_needed",
        )
        repo.update_document_metadata(doc_id, "OpenAI", "2026-05-29", 0.7, "test", "rename_review_needed")
        repo.conn.commit()

        document = repo.list_documents()[0]
        assert document["source_from_display"] == "billing@openai.com"
        assert document["source_to_display"] == "accounting@accounting_domain_placeholder"
        assert document["supposed_filename"] == "2026_05_29_openai.pdf"
        assert document["preview_kind"] == "pdf"
        assert document["raw_preview_url"].endswith(".pdf")
        assert document["modal_preview_kind"] == "pdf"
    finally:
        repo.conn.close()


def test_manual_document_rename_updates_metadata_and_final_file(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    raw = tmp_path / "invoice.pdf"
    raw.write_text("invoice")
    repo = make_repo(settings)

    try:
        doc_id, _ = repo.add_document(
            source_type="mail_attachment",
            source_id="1",
            original_filename="invoice.pdf",
            raw_path=str(raw),
            content_hash="manual-hash",
            mime_type="application/pdf",
            status="rename_review_needed",
        )

        final_filename, final_path = rename_document_as(raw, "OpenAI", "2026-05-29", settings.renamed_dir)
        repo.update_document_metadata(doc_id, "OpenAI", "2026-05-29", 1.0, "manual", "rename_needed")
        repo.mark_document_renamed(doc_id, final_filename, str(final_path))
        repo.conn.commit()

        document = repo.list_documents()[0]
        assert document["status"] == "renamed"
        assert document["detected_vendor"] == "openai"
        assert document["detected_date"] == "2026-05-29"
        assert document["final_filename"] == "2026_05_29_openai.pdf"
        assert Path(document["final_path"]).exists()
    finally:
        repo.conn.close()


def test_document_can_be_ignored_from_review(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    raw = tmp_path / "invoice.pdf"
    raw.write_text("invoice")
    repo = make_repo(settings)

    try:
        doc_id, _ = repo.add_document(
            source_type="mail_attachment",
            source_id="1",
            original_filename="invoice.pdf",
            raw_path=str(raw),
            content_hash="ignored-hash",
            mime_type="application/pdf",
            status="rename_review_needed",
        )

        repo.update_document_status(doc_id, "review_ignored")
        repo.conn.commit()

        document = repo.list_documents()[0]
        assert document["status"] == "review_ignored"
        assert document["final_filename"] is None
        assert document["final_path"] is None
    finally:
        repo.conn.close()
