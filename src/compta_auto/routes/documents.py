"""Document management routes."""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

from ..config import Settings
from ..extraction import MetadataExtractor, async_extract_fetcher_metadata, detect_fetcher_vendor
from ..files import unique_path
from ..normalize import email_domain
from ..renamer import rename_document, rename_document_as
from ..repositories import Repository
from .deps import get_repo, get_settings

router = APIRouter(tags=["documents"])
EXPORT_READY_STATUSES = ("doc_included", "uploaded_to_inqom")


def list_export_ready_documents(repo: Repository) -> list[dict]:
    """Return documents ready for local export."""
    documents: list[dict] = []
    for status in EXPORT_READY_STATUSES:
        documents.extend(repo.list_documents(status=status))
    return documents


def _document_file_response(path_value: str, filename: str | None) -> FileResponse:
    """Serve a document file inline."""
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found")
    display_name = filename or path.name
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline"})


def _preview_file_response(path_value: str, filename: str | None) -> FileResponse:
    """Serve a document file for preview."""
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found")
    display_name = filename or path.name
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.post("/documents/{document_id}/rename")
def rename_document_route(
    document_id: int,
    vendor: str = Form(...),
    date: str = Form(...),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    source = Path(document["raw_path"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source document file not found")
    final_filename, final_path = rename_document_as(source, vendor, date, settings.renamed_dir)
    repo.update_document_metadata(document_id, vendor, date, 1.0, "manual", "rename_needed")
    repo.mark_document_renamed(document_id, final_filename, str(final_path))
    return RedirectResponse("/", status_code=303)


@router.post("/documents/{document_id}/keep")
def keep_document_route(
    document_id: int,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Keep the document with its current original filename (copy to renamed dir)."""
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    source = Path(document["raw_path"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source file not found")
    settings.renamed_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(settings.renamed_dir / source.name)
    shutil.copy2(source, target)
    repo.update_document_metadata(
        document_id, document.get("detected_vendor"), document.get("detected_date"),
        1.0, "manual", "rename_needed",
    )
    repo.mark_document_renamed(document_id, target.name, str(target))
    return RedirectResponse("/", status_code=303)


@router.post("/documents/{document_id}/ignore")
def ignore_document_route(
    document_id: int,
    repo: Repository = Depends(get_repo),
) -> RedirectResponse:
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    repo.update_document_status(document_id, "review_ignored")
    return RedirectResponse("/", status_code=303)


@router.post("/documents/{document_id}/status")
def update_document_status_route(
    document_id: int,
    status: str = Form(...),
    repo: Repository = Depends(get_repo),
) -> RedirectResponse:
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    repo.update_document_status(document_id, status)
    return RedirectResponse("/", status_code=303)


@router.post("/documents/{document_id}/accounting-type")
def update_document_accounting_type_route(
    document_id: int,
    accounting_type: str = Form(...),
    repo: Repository = Depends(get_repo),
) -> JSONResponse:
    """Set accounting type: 'purchase' or 'sale'."""
    if accounting_type not in ("purchase", "sale", ""):
        raise HTTPException(status_code=400, detail="accounting_type must be 'purchase', 'sale', or empty")
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    repo.update_document_accounting_type(document_id, accounting_type or None)
    return JSONResponse({"ok": True, "id": document_id, "accounting_type": accounting_type})


@router.post("/documents/bulk-accounting-type")
async def bulk_update_accounting_type(
    request: Request,
    repo: Repository = Depends(get_repo),
) -> JSONResponse:
    """Bulk set accounting type for multiple documents."""
    body = await request.json()
    doc_ids: list[int] = body.get("ids", [])
    accounting_type: str = body.get("accounting_type", "")
    if not doc_ids or accounting_type not in ("purchase", "sale"):
        raise HTTPException(status_code=400, detail="ids and accounting_type (purchase/sale) required")
    for doc_id in doc_ids:
        repo.update_document_accounting_type(doc_id, accounting_type)
    return JSONResponse({"ok": True, "count": len(doc_ids)})


@router.post("/documents/bulk-status")
async def bulk_update_document_status(
    request: Request,
    repo: Repository = Depends(get_repo),
) -> JSONResponse:
    """Bulk update status for multiple documents."""
    body = await request.json()
    doc_ids: list[int] = body.get("ids", [])
    status: str = body.get("status", "")
    if not doc_ids or not status:
        raise HTTPException(status_code=400, detail="ids and status required")
    for doc_id in doc_ids:
        repo.update_document_status(doc_id, status)
    return JSONResponse({"ok": True, "count": len(doc_ids)})


@router.post("/documents/bulk-accept-suggested")
async def bulk_accept_suggested(
    request: Request,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Bulk accept suggested names for multiple documents."""
    body = await request.json()
    doc_ids: list[int] = body.get("ids", [])
    if not doc_ids:
        raise HTTPException(status_code=400, detail="ids required")
    accepted = 0
    for doc_id in doc_ids:
        document = repo.get_document(doc_id)
        if not document:
            continue
        final_fn = document.get("final_filename") or ""
        m = re.match(r"(\d{4})_(\d{2})_(\d{2})_(.+)\.\w+$", final_fn)
        if m:
            d = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            v = m.group(4)
        elif document.get("detected_vendor") and document.get("detected_date"):
            v = document["detected_vendor"]
            d = document["detected_date"]
        else:
            continue
        source = Path(document["raw_path"])
        if not source.exists():
            continue
        final_filename, final_path = rename_document_as(source, v, d, settings.renamed_dir)
        repo.update_document_metadata(doc_id, v, d, 1.0, "manual", "rename_needed")
        repo.mark_document_renamed(doc_id, final_filename, str(final_path))
        accepted += 1
    return JSONResponse({"ok": True, "count": accepted})


@router.post("/documents/re-rename")
async def re_rename_documents(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Re-run rename logic on all non-manually-renamed documents, streaming progress."""

    async def event_stream():
        extractor = MetadataExtractor()
        docs = repo.list_documents("renamed") + repo.list_documents("rename_review_needed")
        processable = [
            d for d in docs
            if d.get("extraction_method") != "manual" and Path(d["raw_path"]).exists()
        ]
        total = len(processable)
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"
        updated = 0
        for i, doc in enumerate(processable):
            raw_path = Path(doc["raw_path"])
            known_vendor = detect_fetcher_vendor(doc.get("original_filename", raw_path.name))
            if known_vendor:
                metadata = await async_extract_fetcher_metadata(raw_path, known_vendor, extractor)
            else:
                metadata = await extractor.async_extract(raw_path)
            result = rename_document(
                raw_path, metadata, settings.renamed_dir, settings.min_rename_confidence,
            )
            if result:
                old_final = doc.get("final_path")
                if old_final:
                    old_path = Path(old_final)
                    if old_path.exists():
                        old_path.unlink()
                final_filename, final_path = result
                repo.update_document_metadata(
                    doc["id"], metadata.vendor, metadata.date,
                    metadata.confidence, metadata.method, "rename_needed",
                )
                repo.mark_document_renamed(doc["id"], final_filename, str(final_path))
                updated += 1
            yield f"data: {json.dumps({'type': 'progress', 'current': i + 1, 'total': total, 'filename': raw_path.name})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'updated': updated})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/documents/bulk-delete")
async def bulk_delete_documents(
    request: Request,
    repo: Repository = Depends(get_repo),
) -> JSONResponse:
    """Permanently dismiss documents (they won't come back on re-scan)."""
    body = await request.json()
    doc_ids: list[int] = body.get("ids", [])
    if not doc_ids:
        raise HTTPException(status_code=400, detail="ids required")
    for doc_id in doc_ids:
        repo.delete_document(doc_id)
    return JSONResponse({"ok": True, "count": len(doc_ids)})


@router.post("/documents/bulk-rule")
def bulk_document_rule(
    document_id: int = Form(...),
    rule_type: str = Form(...),
    match_type: str = Form(...),
    repo: Repository = Depends(get_repo),
) -> RedirectResponse:
    """Whitelist/blacklist moves all docs from same sender/domain."""
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    sender = document.get("mail_sender") or ""
    if not sender:
        return RedirectResponse("/", status_code=303)

    if match_type == "domain":
        match_value = email_domain(sender)
    else:
        match_value = sender

    vendor = document.get("detected_vendor")
    try:
        repo.add_rule(rule_type, match_type, match_value, vendor)
    except Exception:
        pass  # Rule may already exist

    # Bulk move all documents from matching sender/domain
    target_status = "doc_included" if rule_type == "always_process" else "review_ignored"
    repo.bulk_update_document_status_by_sender(match_type, match_value, target_status)

    # Also apply to matching mails
    actionable_statuses = ["mail_triage_needed", "mail_auto_selected", "mail_ignored"]
    matching_mails = repo.find_mails_matching_rule(match_type, match_value, actionable_statuses)
    for matched in matching_mails:
        matched_id = int(matched["id"])
        if rule_type == "always_process":
            repo.update_mail_status(matched_id, "mail_auto_selected")
        elif rule_type == "ignore":
            repo.update_mail_status(matched_id, "mail_ignored")

    return RedirectResponse("/", status_code=303)


@router.get("/api/documents")
def api_documents(repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_documents()


@router.get("/documents/{document_id}/raw")
def raw_document(document_id: int, repo: Repository = Depends(get_repo)) -> FileResponse:
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_file_response(document["raw_path"], document["original_filename"])


@router.get("/documents/{document_id}/preview/{filename:path}")
def preview_document(
    document_id: int, filename: str, repo: Repository = Depends(get_repo),
) -> FileResponse:
    document = repo.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return _preview_file_response(document["raw_path"], filename or document["original_filename"])


@router.get("/documents/{document_id}/final")
def final_document(document_id: int, repo: Repository = Depends(get_repo)) -> FileResponse:
    document = repo.get_document(document_id)
    if not document or not document.get("final_path"):
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_file_response(document["final_path"], document["final_filename"])


@router.get("/api/export-preview")
def api_export_preview(repo: Repository = Depends(get_repo)):
    """Return documents ready for export, grouped by YYYY/MM."""
    docs = list_export_ready_documents(repo)
    tree: dict[str, list] = {}
    for doc in docs:
        date_str = doc.get("detected_date") or ""
        if len(date_str) >= 7:
            folder = f"{date_str[:4]}/{date_str[5:7]}"
        else:
            folder = "unknown"
        tree.setdefault(folder, []).append(doc)
    return {"tree": tree, "total": len(docs)}


@router.post("/api/export")
def api_export(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
):
    """Move all export-ready documents to output_dir/YYYY/MM/filename."""
    output_base = settings.output_dir
    custom_output = repo.get_app_state("output_dir")
    if custom_output:
        output_base = Path(custom_output)

    docs = list_export_ready_documents(repo)
    moved = 0
    errors = []
    for doc in docs:
        date_str = doc.get("detected_date") or ""
        if len(date_str) >= 7:
            folder = f"{date_str[:4]}/{date_str[5:7]}"
        else:
            folder = "unknown"

        source_path = Path(doc.get("final_path") or doc["raw_path"])
        if not source_path.exists():
            errors.append(f"Missing: {source_path.name}")
            continue

        filename = doc.get("final_filename") or source_path.name
        dest_dir = output_base / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / filename

        if dest_file.exists():
            errors.append(f"Already exists: {folder}/{filename}")
            continue

        try:
            shutil.copy2(source_path, dest_file)
            repo.update_document_status(doc["id"], "exported")
            moved += 1
        except Exception as exc:
            errors.append(f"{filename}: {exc}")

    return {"moved": moved, "errors": errors, "output_dir": str(output_base)}


@router.post("/api/settings/output-dir")
async def api_set_output_dir(request: Request, repo: Repository = Depends(get_repo)):
    """Set the output directory for export."""
    body = await request.json()
    path = body.get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Path is required")
    # Validate path is within user home directory
    resolved = str(Path(path).expanduser().resolve())
    home = str(Path.home().resolve())
    if not (resolved == home or resolved.startswith(home + "/")):
        raise HTTPException(status_code=403, detail="Output directory must be within your home directory")
    repo.set_app_state("output_dir", resolved)
    return {"path": resolved}


@router.get("/api/settings/output-dir")
def api_get_output_dir(repo: Repository = Depends(get_repo), settings: Settings = Depends(get_settings)):
    """Get the configured output directory."""
    custom = repo.get_app_state("output_dir")
    return {"path": custom or str(settings.output_dir)}
