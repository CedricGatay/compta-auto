"""Mail management routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from ..config import Settings
from ..mail_to_pdf import mail_to_pdf
from ..normalize import email_domain
from ..pipeline import AccountingPipeline, RunSummary
from ..repositories import Repository
from .deps import get_repo, get_settings

router = APIRouter(tags=["mails"])


def _mail_rule_match_value(mail: dict, match_type: str) -> str:
    """Determine the match value for a rule based on the mail and match type."""
    if match_type == "sender":
        return str(mail.get("sender") or "")
    if match_type == "domain":
        return email_domain(str(mail.get("sender") or ""))
    if match_type == "vendor":
        return str(mail.get("detected_vendor") or mail.get("sender") or "")
    raise HTTPException(status_code=400, detail="Unsupported rule match type")


def _process_mail_now(settings: Settings, repo: Repository, mail: dict) -> None:
    """Process a mail immediately (download attachments and extract)."""
    pipeline = AccountingPipeline(settings, repo)
    for message in pipeline.spark.read_thread(str(mail["spark_message_id"]), download_attachments=True):
        if message.spark_message_id == str(mail["spark_message_id"]):
            pipeline.extract_message_artifacts(int(mail["id"]), message, RunSummary())
            break


@router.post("/mails/{mail_id}/rule")
def add_rule_from_mail(
    mail_id: int,
    rule_type: str = Form(...),
    match_type: str = Form(...),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    mail = repo.get_mail(mail_id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")
    match_value = _mail_rule_match_value(mail, match_type)
    vendor = mail.get("detected_vendor")
    repo.add_rule(rule_type, match_type, match_value, vendor)
    # Apply rule to all matching mails currently in triage or pending states
    actionable_statuses = ["mail_triage_needed", "mail_auto_selected", "mail_ignored"]
    matching_mails = repo.find_mails_matching_rule(match_type, match_value, actionable_statuses)
    for matched in matching_mails:
        matched_id = int(matched["id"])
        if rule_type == "always_process":
            repo.update_mail_status(matched_id, "mail_auto_selected")
            _process_mail_now(settings, repo, matched)
        elif rule_type == "ignore":
            repo.update_mail_status(matched_id, "mail_ignored")
    return RedirectResponse("/", status_code=303)


@router.post("/mails/{mail_id}/status")
def update_mail_status(
    mail_id: int,
    status: str = Form(...),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    repo.update_mail_status(mail_id, status)
    if status == "mail_auto_selected":
        mail = repo.get_mail(mail_id)
        if mail:
            _process_mail_now(settings, repo, mail)
    return RedirectResponse("/", status_code=303)


@router.get("/mails/{mail_id}/pdf-preview")
def mail_pdf_preview(
    mail_id: int, repo: Repository = Depends(get_repo),
) -> FileResponse:
    """Generate a temporary PDF preview of the mail."""
    mail = repo.get_mail(mail_id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")
    # Use NamedTemporaryFile with delete=False to avoid leaking unnamed temp files
    tmp = Path(tempfile.mktemp(suffix=".pdf"))
    mail_to_pdf(
        subject=mail["subject"] or "(no subject)",
        sender=mail["sender"] or "",
        recipients=mail.get("recipients", "") or "",
        sent_at=mail.get("sent_at"),
        body=mail.get("body", "") or "",
        output_path=tmp,
    )
    return FileResponse(
        tmp, media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
        background=None,  # TODO: clean up temp file after response
    )


@router.post("/mails/{mail_id}/to-pdf")
def mail_to_pdf_route(
    mail_id: int,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    import mimetypes

    from ..extraction import MetadataExtractor, extract_fetcher_metadata
    from ..files import sha256_file
    from ..links import provider_from_sender_or_url
    from ..normalize import normalize_vendor
    from ..renamer import rename_document
    from ..services.categorize import auto_categorize_document

    mail = repo.get_mail(mail_id)
    if not mail:
        raise HTTPException(status_code=404, detail="Mail not found")

    subject_slug = "".join(
        c if c.isalnum() or c in " -_" else "" for c in (mail["subject"] or "mail")
    ).strip()[:60]
    date_prefix = (mail["sent_at"] or "")[:10].replace("-", "") or "nodate"
    filename = f"{date_prefix}_{subject_slug}.pdf"

    output_path = settings.raw_dir / filename
    mail_to_pdf(
        subject=mail["subject"] or "(no subject)",
        sender=mail["sender"] or "",
        recipients=mail.get("recipients", "") or "",
        sent_at=mail.get("sent_at"),
        body=mail.get("body", "") or "",
        output_path=output_path,
    )

    # Register as document
    content_hash = sha256_file(output_path)
    mime = mimetypes.guess_type(output_path.name)[0]
    doc_id, created = repo.add_document(
        source_type="mail_pdf",
        source_id=str(mail_id),
        original_filename=filename,
        raw_path=str(output_path),
        content_hash=content_hash,
        mime_type=mime,
        status="attachment_extracted",
    )

    # Extract metadata using mail context (sender/subject help vendor detection)
    extractor = MetadataExtractor(
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        llm_command=settings.llm_extractor_command,
        use_apple_llm=settings.use_apple_llm,
    )
    detected_vendor = normalize_vendor(provider_from_sender_or_url(mail["sender"] or ""))
    if detected_vendor:
        metadata = extract_fetcher_metadata(output_path, detected_vendor, extractor)
    else:
        metadata = extractor.extract(
            output_path, mail_subject=mail["subject"] or "", sender=mail["sender"] or ""
        )

    # Rename and update document status
    result = rename_document(
        output_path, metadata, settings.renamed_dir, settings.min_rename_confidence,
    )
    if result:
        final_filename, final_path = result
        repo.update_document_metadata(
            doc_id, metadata.vendor, metadata.date,
            metadata.confidence, metadata.method, "rename_needed",
        )
        repo.mark_document_renamed(doc_id, final_filename, str(final_path))
    else:
        repo.update_document_metadata(
            doc_id, metadata.vendor, metadata.date,
            metadata.confidence, metadata.method, "rename_review_needed",
        )
    document = repo.get_document(doc_id)
    if document and not document.get("accounting_type"):
        repo.update_document_accounting_type(
            doc_id, auto_categorize_document({"detected_vendor": metadata.vendor})
        )

    repo.update_mail_status(mail_id, "mail_auto_selected")
    return RedirectResponse("/", status_code=303)


@router.get("/mail-attachments/{attachment_id}/raw")
def raw_mail_attachment(
    attachment_id: int, repo: Repository = Depends(get_repo),
) -> FileResponse:
    from .documents import _document_file_response

    attachment = repo.get_mail_attachment(attachment_id)
    if not attachment or not attachment.get("path"):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return _document_file_response(attachment["path"], attachment["filename"])


@router.get("/mail-attachments/{attachment_id}/preview/{filename:path}")
def preview_mail_attachment(
    attachment_id: int, filename: str, repo: Repository = Depends(get_repo),
) -> FileResponse:
    from .documents import _preview_file_response

    attachment = repo.get_mail_attachment(attachment_id)
    if not attachment or not attachment.get("path"):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return _preview_file_response(attachment["path"], filename or attachment["filename"])


@router.get("/api/mails")
def api_mails(repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_mails()
