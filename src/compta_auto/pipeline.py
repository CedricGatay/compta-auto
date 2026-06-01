from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .extraction import MetadataExtractor
from .files import sha256_file, write_attachment
from .links import find_invoice_links, provider_from_sender_or_url
from .models import (
    ACCOUNTING_TERMS,
    DOCUMENT_EXTENSIONS,
    INVOICE_MODERATE_TERMS,
    INVOICE_SENDER_PATTERNS,
    INVOICE_STRONG_TERMS,
    MailMessage,
)
from .normalize import email_domain, normalize_vendor
from .renamer import rename_document
from .repositories import Repository
from .spark_client import SparkClient


@dataclass
class RunSummary:
    scanned_messages: int = 0
    new_mails: int = 0
    triage_mails: int = 0
    ignored_mails: int = 0
    attachments_extracted: int = 0
    duplicates_skipped: int = 0
    provider_tasks: int = 0
    renamed: int = 0
    rename_review_needed: int = 0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


class AccountingPipeline:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        spark: SparkClient | None = None,
        extractor: MetadataExtractor | None = None,
    ):
        self.settings = settings
        self.repo = repo
        self.spark = spark or SparkClient()
        self.extractor = extractor or MetadataExtractor(
            llm_command=settings.llm_extractor_command,
            openai_api_key=settings.openai_api_key,
            openai_model=settings.openai_model,
            use_apple_llm=settings.use_apple_llm,
        )

    def run_mail_scan(self, months: int = 1) -> RunSummary:
        summary = RunSummary()
        run_id = self.repo.create_run()
        try:
            message_ids = self.spark.search_candidate_ids(months)
            for message_id in message_ids:
                for message in self.spark.read_thread(message_id, download_attachments=True):
                    summary.scanned_messages += 1
                    self.process_message(message, summary)
            self.repo.finish_run(run_id, "finished", summary.as_dict())
        except Exception as exc:
            summary.failures.append(str(exc))
            self.repo.finish_run(run_id, "failed", summary.as_dict())
            raise
        return summary

    def run_folder_scan(self, folder: Path, max_age_days: int = 30) -> RunSummary:
        """Scan a local folder for receipts/invoices and process them."""
        import time

        summary = RunSummary()
        run_id = self.repo.create_run()
        cutoff = time.time() - (max_age_days * 86400)
        try:
            for file_path in sorted(folder.iterdir()):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in DOCUMENT_EXTENSIONS:
                    continue
                # Filter by modification time
                if file_path.stat().st_mtime < cutoff:
                    continue
                summary.scanned_messages += 1
                self._process_local_file(file_path, summary)
            self.repo.finish_run(run_id, "finished", summary.as_dict())
        except Exception as exc:
            summary.failures.append(str(exc))
            self.repo.finish_run(run_id, "failed", summary.as_dict())
            raise
        return summary

    def _process_local_file(self, file_path: Path, summary: RunSummary) -> None:
        """Import a single local file as a document."""
        content_hash = sha256_file(file_path)

        mime = mimetypes.guess_type(file_path.name)[0]
        doc_id, created = self.repo.upsert_document(
            source_type="local_folder",
            source_id=str(file_path.parent),
            original_filename=file_path.name,
            raw_path=str(file_path),
            content_hash=content_hash,
            mime_type=mime,
        )
        if not created:
            summary.duplicates_skipped += 1
            return
        summary.attachments_extracted += 1
        # Extract metadata and rename
        metadata = self.extractor.extract(file_path)
        result = rename_document(
            file_path,
            metadata,
            self.settings.renamed_dir,
            self.settings.min_rename_confidence,
        )
        if result:
            final_filename, final_path = result
            self.repo.update_document_metadata(
                doc_id, metadata.vendor, metadata.date,
                metadata.confidence, metadata.method, "rename_needed",
            )
            self.repo.mark_document_renamed(doc_id, final_filename, str(final_path))
            summary.renamed += 1
        else:
            self.repo.update_document_metadata(
                doc_id, metadata.vendor, metadata.date,
                metadata.confidence, metadata.method, "rename_review_needed",
            )
            summary.rename_review_needed += 1

    def process_message(self, message: MailMessage, summary: RunSummary) -> None:
        existing = self.repo.get_mail_by_spark_id(message.spark_message_id)
        if existing:
            _, _, detected_vendor = self.classify_message(message)
            mail_id = int(existing["id"])
            self.repo.refresh_mail_metadata(
                mail_id,
                message.sender,
                message.recipients,
                message.subject,
                message.sent_at,
                message.body,
                detected_vendor,
            )
            self.record_attachment_previews(mail_id, message)
            if (
                existing["status"] == "mail_auto_selected"
                and message.attachments
                and self.repo.count_documents_for_source("mail_attachment", str(mail_id)) == 0
            ):
                self.extract_message_artifacts(mail_id, message, summary)
            summary.duplicates_skipped += 1
            return
        status, reason, detected_vendor = self.classify_message(message)
        mail_id, created = self.repo.upsert_mail(
            spark_message_id=message.spark_message_id,
            sender=message.sender,
            recipients=message.recipients,
            subject=message.subject,
            sent_at=message.sent_at,
            body=message.body,
            status=status,
            detected_vendor=detected_vendor,
            extraction_reason=reason,
        )
        if created:
            summary.new_mails += 1
        if status == "mail_triage_needed":
            self.record_attachment_previews(mail_id, message)
            summary.triage_mails += 1
            return
        if status == "mail_ignored":
            self.record_attachment_previews(mail_id, message)
            summary.ignored_mails += 1
            return
        self.record_attachment_previews(mail_id, message)
        self.extract_message_artifacts(mail_id, message, summary)

    def classify_message(self, message: MailMessage) -> tuple[str, str, str | None]:
        detected_vendor = provider_from_sender_or_url(message.sender)
        rule, rule_vendor = self.repo.classify_by_rules(message.sender, detected_vendor)
        if rule == "ignore":
            return "mail_ignored", "ignored_by_rule", rule_vendor or detected_vendor
        if rule == "always_process":
            return "mail_auto_selected", "always_process_rule", rule_vendor or detected_vendor
        if any(r.lower().endswith(self.settings.accounting_recipient_suffix) for r in message.recipients):
            return "mail_auto_selected", "accounting_recipient", detected_vendor
        if is_likely_accounting(message):
            return "mail_triage_needed", "candidate_terms_or_attachments", detected_vendor
        return "mail_ignored", "not_accounting_candidate", detected_vendor

    def extract_message_artifacts(self, mail_id: int, message: MailMessage, summary: RunSummary) -> None:
        self.record_attachment_previews(mail_id, message)
        for attachment in message.attachments:
            if Path(attachment.filename).suffix.lower() not in DOCUMENT_EXTENSIONS:
                continue
            try:
                raw_path = write_attachment(
                    self.settings.raw_dir, attachment.filename, attachment.content, attachment.path
                )
                content_hash = sha256_file(raw_path)
                doc_id, created = self.repo.add_document(
                    source_type="mail_attachment",
                    source_id=str(mail_id),
                    original_filename=attachment.filename,
                    raw_path=str(raw_path),
                    content_hash=content_hash,
                    mime_type=attachment.mime_type or mimetypes.guess_type(attachment.filename)[0],
                    status="attachment_extracted",
                )
                if not created:
                    summary.duplicates_skipped += 1
                    continue
                summary.attachments_extracted += 1
                self.extract_and_rename(doc_id, raw_path, message, summary)
            except Exception as exc:
                summary.failures.append(f"{attachment.filename}: {exc}")

        for url in find_invoice_links(message.body):
            provider = provider_from_sender_or_url(message.sender, url)
            _, created = self.repo.add_provider_task(
                provider=provider,
                url=url,
                source_mail_id=mail_id,
                status="provider_download_needed",
            )
            if created:
                summary.provider_tasks += 1
            else:
                summary.duplicates_skipped += 1

    def record_attachment_previews(self, mail_id: int, message: MailMessage) -> None:
        for attachment in message.attachments:
            self.repo.upsert_mail_attachment(
                mail_id,
                attachment.filename,
                str(attachment.path) if attachment.path else None,
                attachment.mime_type or mimetypes.guess_type(attachment.filename)[0],
            )

    def extract_and_rename(
        self, document_id: int, raw_path: Path, message: MailMessage, summary: RunSummary
    ) -> None:
        metadata = self.extractor.extract(raw_path, mail_subject=message.subject, sender=message.sender)
        result = rename_document(
            raw_path,
            metadata,
            self.settings.renamed_dir,
            self.settings.min_rename_confidence,
        )
        if result:
            final_filename, final_path = result
            self.repo.update_document_metadata(
                document_id,
                metadata.vendor,
                metadata.date,
                metadata.confidence,
                metadata.method,
                "rename_needed",
            )
            self.repo.mark_document_renamed(document_id, final_filename, str(final_path))
            summary.renamed += 1
        else:
            self.repo.update_document_metadata(
                document_id,
                metadata.vendor,
                metadata.date,
                metadata.confidence,
                metadata.method,
                "rename_review_needed",
            )
            summary.rename_review_needed += 1


def is_likely_accounting(message: MailMessage) -> bool:
    """Score-based heuristic to detect invoice/billing mails.

    Weighs signals from sender address, subject line, body, and attachments.
    Requires a minimum combined score to avoid false positives from mails
    that merely mention 'payment' in passing.
    """
    score = 0.0
    sender_lower = message.sender.lower()
    subject_lower = message.subject.lower()
    body_lower = message.body[:3000].lower()

    # Sender analysis: billing-related sender addresses are strong signals
    sender_local = sender_lower.split("@")[0] if "@" in sender_lower else sender_lower
    if any(pattern in sender_local for pattern in INVOICE_SENDER_PATTERNS):
        score += 0.4

    # Subject analysis: strongest signal since subject summarizes intent
    for term in INVOICE_STRONG_TERMS:
        if term in subject_lower:
            score += 0.6
            break
    else:
        for term in INVOICE_MODERATE_TERMS:
            if term in subject_lower:
                score += 0.3
                break

    # Body analysis: look for invoice-specific patterns
    for term in INVOICE_STRONG_TERMS:
        if term in body_lower:
            score += 0.3
            break
    else:
        for term in INVOICE_MODERATE_TERMS:
            if term in body_lower:
                score += 0.15
                break

    # Attachment filenames: invoice-named PDFs are a strong signal
    attachment_names = " ".join(a.filename.lower() for a in message.attachments)
    if attachment_names:
        for term in INVOICE_STRONG_TERMS:
            if term in attachment_names:
                score += 0.5
                break
        else:
            # PDF/image attachment is a weak supporting signal (not sufficient alone)
            if any(Path(a.filename).suffix.lower() in DOCUMENT_EXTENSIONS for a in message.attachments):
                score += 0.1

    # Threshold: require meaningful evidence (e.g. strong subject alone = 0.6,
    # invoice-named attachment = 0.5, billing sender + moderate body = 0.55)
    return score >= 0.5
