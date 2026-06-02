from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings, get_settings
from .db import Database
from .mail_to_pdf import mail_to_pdf
from .pipeline import AccountingPipeline, RunSummary
from .normalize import email_domain
from .renamer import rename_document_as
from .repositories import Repository


templates = Jinja2Templates(directory=str(Path(__file__).parent / "web" / "templates"))


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    db = Database(app_settings.db_path)
    db.init()

    app = FastAPI(title="Compta Auto")
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def get_repo() -> Repository:
        conn = db.connect()
        try:
            yield Repository(conn)
            conn.commit()
        finally:
            conn.close()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, repo: Repository = Depends(get_repo)) -> HTMLResponse:
        last_scan_folder = repo.get_app_state("last_scan_folder") or app_settings.scan_folder or ""
        last_scan_folder_date = repo.get_app_state("last_scan_folder_date") or ""
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "runs": repo.list_runs(),
                "mails": repo.list_mails(),
                "documents": repo.list_documents(),
                "provider_tasks": repo.list_provider_tasks(),
                "rules": repo.list_rules(),
                "settings": app_settings,
                "last_scan_folder": last_scan_folder,
                "last_scan_folder_date": last_scan_folder_date,
            },
        )

    @app.post("/scan")
    def scan(months: int = Form(1), repo: Repository = Depends(get_repo)) -> RedirectResponse:
        pipeline = AccountingPipeline(app_settings, repo)
        pipeline.run_mail_scan(months=months)
        return RedirectResponse("/", status_code=303)

    @app.post("/scan-folder")
    def scan_folder(
        folder: str = Form(...),
        timespan: str = Form("30"),
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        from datetime import datetime, timezone

        folder_path = Path(folder).expanduser().resolve()
        if not folder_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")

        # Compute max_age_days
        if timespan == "since_last":
            last_date_str = repo.get_app_state("last_scan_folder_date")
            if last_date_str:
                last_dt = datetime.fromisoformat(last_date_str)
                delta = datetime.now(timezone.utc) - last_dt
                max_age_days = max(1, delta.days + 1)
            else:
                max_age_days = 30
        else:
            max_age_days = int(timespan)

        pipeline = AccountingPipeline(app_settings, repo)
        pipeline.run_folder_scan(folder_path, max_age_days=max_age_days)
        # Persist folder path and scan timestamp
        repo.set_app_state("last_scan_folder", str(folder_path))
        repo.set_app_state("last_scan_folder_date", datetime.now(timezone.utc).isoformat())
        return RedirectResponse("/", status_code=303)

    @app.get("/api/pick-folder")
    def pick_folder() -> JSONResponse:
        """Open a native macOS folder picker dialog and return the selected path."""
        import subprocess

        script = (
            'tell application "System Events"\n'
            '  activate\n'
            '  set theFolder to choose folder with prompt "Select receipts folder"\n'
            '  return POSIX path of theFolder\n'
            'end tell'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                return JSONResponse({"path": result.stdout.strip().rstrip("/")})
            return JSONResponse({"path": None, "error": "Cancelled"}, status_code=200)
        except Exception as exc:
            return JSONResponse({"path": None, "error": str(exc)}, status_code=500)

    @app.post("/reset")
    def reset(repo: Repository = Depends(get_repo)) -> RedirectResponse:
        """Reset all data except rules, delete renamed files, and allow reprocessing."""
        import shutil

        repo.reset_all()
        # Remove renamed files on disk
        if app_settings.renamed_dir.exists():
            shutil.rmtree(app_settings.renamed_dir)
            app_settings.renamed_dir.mkdir(parents=True, exist_ok=True)
        # Remove raw downloads too so they get re-fetched
        if app_settings.raw_dir.exists():
            shutil.rmtree(app_settings.raw_dir)
            app_settings.raw_dir.mkdir(parents=True, exist_ok=True)
        return RedirectResponse("/", status_code=303)

    # --- Credentials management ---

    CREDENTIAL_KEYS = ("spotify_sp_dc", "chatgpt_bearer", "free_username", "free_password")

    @app.get("/api/credentials")
    def api_get_credentials(repo: Repository = Depends(get_repo)):
        """Return saved credentials (values masked for display)."""
        creds = {}
        for key in CREDENTIAL_KEYS:
            val = repo.get_app_state(f"cred_{key}")
            if val:
                creds[key] = {"saved": True, "hint": val[:4] + "…" + val[-4:] if len(val) > 10 else "••••"}
            else:
                creds[key] = {"saved": False, "hint": ""}
        return creds

    @app.post("/api/credentials")
    async def api_save_credentials(
        request: Request,
        repo: Repository = Depends(get_repo),
    ):
        """Save one or more credentials."""
        body = await request.json()
        saved = []
        for key in CREDENTIAL_KEYS:
            if key in body and body[key]:
                repo.set_app_state(f"cred_{key}", body[key])
                saved.append(key)
        return {"saved": saved}

    @app.delete("/api/credentials/{key}")
    def api_delete_credential(key: str, repo: Repository = Depends(get_repo)):
        """Clear a saved credential."""
        if key not in CREDENTIAL_KEYS:
            raise HTTPException(status_code=400, detail="Invalid credential key")
        repo.set_app_state(f"cred_{key}", "")
        return {"deleted": key}

    def _get_cred(repo: Repository, key: str, form_value: str | None = None) -> str | None:
        """Return form value if provided, otherwise fall back to saved credential."""
        if form_value and form_value.strip():
            return form_value.strip()
        return repo.get_app_state(f"cred_{key}") or None

    @app.post("/api/fetch-spotify")
    def api_fetch_spotify(
        sp_dc: str = Form(""),
        repo: Repository = Depends(get_repo),
    ) -> StreamingResponse:
        """Fetch Spotify invoices with SSE progress updates."""
        from .spotify import fetch_spotify_invoices_stream

        effective_sp_dc = _get_cred(repo, "spotify_sp_dc", sp_dc)
        if not effective_sp_dc:
            raise HTTPException(status_code=400, detail="No sp_dc cookie provided or saved.")
        # Save for next time
        repo.set_app_state("cred_spotify_sp_dc", effective_sp_dc)

        def event_stream():
            try:
                result = {"total": 0, "downloaded": 0, "skipped": 0, "errors": []}
                for event in fetch_spotify_invoices_stream(effective_sp_dc, app_settings.raw_dir):
                    if event["type"] == "progress":
                        yield f"data: {json.dumps(event)}\n\n"
                    elif event["type"] == "done":
                        result = event["result"]
                # Process through pipeline
                yield f"data: {json.dumps({'type': 'status', 'message': 'Processing documents…'})}\n\n"
                pipeline = AccountingPipeline(app_settings, repo)
                scan_summary = pipeline.run_folder_scan(app_settings.raw_dir, max_age_days=730)
                result["processed"] = scan_summary.renamed + scan_summary.rename_review_needed
                yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
            except SystemExit:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Authentication failed. Your sp_dc cookie is invalid or expired.'})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/fetch-chatgpt")
    def api_fetch_chatgpt(
        bearer_token: str = Form(""),
        repo: Repository = Depends(get_repo),
    ) -> StreamingResponse:
        """Fetch ChatGPT subscription invoices with SSE progress updates."""
        from .openai_invoices import fetch_chatgpt_invoices_stream, AuthError

        effective_token = _get_cred(repo, "chatgpt_bearer", bearer_token)
        if not effective_token:
            raise HTTPException(status_code=400, detail="No Bearer token provided or saved.")
        repo.set_app_state("cred_chatgpt_bearer", effective_token)

        def event_stream():
            try:
                result = {"total": 0, "downloaded": 0, "skipped": 0, "errors": []}
                for event in fetch_chatgpt_invoices_stream(effective_token, app_settings.raw_dir):
                    if event["type"] == "progress":
                        yield f"data: {json.dumps(event)}\n\n"
                    elif event["type"] == "done":
                        result = event["result"]
                # Process through pipeline
                yield f"data: {json.dumps({'type': 'status', 'message': 'Processing documents…'})}\n\n"
                pipeline = AccountingPipeline(app_settings, repo)
                scan_summary = pipeline.run_folder_scan(app_settings.raw_dir, max_age_days=730)
                result["processed"] = scan_summary.renamed + scan_summary.rename_review_needed
                yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
            except AuthError as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/free-mobile-login")
    def api_free_mobile_login(
        username: str = Form(""),
        password: str = Form(""),
        repo: Repository = Depends(get_repo),
    ):
        """Step 1: Login to Free Mobile (triggers OTP via email)."""
        from .free_invoices import login, AuthError

        effective_user = _get_cred(repo, "free_username", username)
        effective_pass = _get_cred(repo, "free_password", password)
        if not effective_user or not effective_pass:
            return JSONResponse(status_code=400, content={"error": "No credentials provided or saved."})

        try:
            session_cookies, csrf_token, otp_id = login(effective_user, effective_pass)
            # Save on success
            repo.set_app_state("cred_free_username", effective_user)
            repo.set_app_state("cred_free_password", effective_pass)
            return {"status": "otp_required", "session_cookies": session_cookies, "csrf_token": csrf_token, "otp_id": otp_id}
        except AuthError as exc:
            return JSONResponse(status_code=401, content={"error": str(exc)})
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.post("/api/free-mobile-otp")
    def api_free_mobile_otp(
        session_cookies: str = Form(...),
        csrf_token: str = Form(...),
        otp_code: str = Form(...),
        otp_id: str = Form(""),
        repo: Repository = Depends(get_repo),
    ) -> StreamingResponse:
        """Step 2: Validate OTP and download Free Mobile invoices."""
        from .free_invoices import fetch_free_invoices_stream, AuthError

        otp_id_int = int(otp_id) if otp_id else None

        def event_stream():
            try:
                result = {"total": 0, "downloaded": 0, "skipped": 0, "errors": []}
                for event in fetch_free_invoices_stream(session_cookies, csrf_token, otp_code, otp_id_int, app_settings.raw_dir):
                    if event["type"] in ("progress", "status"):
                        yield f"data: {json.dumps(event)}\n\n"
                    elif event["type"] == "done":
                        result = event["result"]
                    elif event["type"] == "error":
                        yield f"data: {json.dumps(event)}\n\n"
                        return
                # Process through pipeline
                if result.get("downloaded", 0) > 0:
                    yield f"data: {json.dumps({'type': 'status', 'message': 'Processing documents…'})}\n\n"
                    pipeline = AccountingPipeline(app_settings, repo)
                    scan_summary = pipeline.run_folder_scan(app_settings.raw_dir, max_age_days=730)
                    result["processed"] = scan_summary.renamed + scan_summary.rename_review_needed
                yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
            except AuthError as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/rules")
    def add_rule(
        rule_type: str = Form(...),
        match_type: str = Form(...),
        match_value: str = Form(...),
        vendor: str = Form(""),
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        repo.add_rule(rule_type, match_type, match_value, vendor or None)
        return RedirectResponse("/", status_code=303)

    @app.post("/rules/{rule_id}/delete")
    def delete_rule(rule_id: int, repo: Repository = Depends(get_repo)) -> RedirectResponse:
        repo.delete_rule(rule_id)
        return RedirectResponse("/", status_code=303)

    @app.post("/mails/{mail_id}/rule")
    def add_rule_from_mail(
        mail_id: int,
        rule_type: str = Form(...),
        match_type: str = Form(...),
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        mail = repo.get_mail(mail_id)
        if not mail:
            raise HTTPException(status_code=404, detail="Mail not found")
        match_value = mail_rule_match_value(mail, match_type)
        vendor = mail.get("detected_vendor")
        repo.add_rule(rule_type, match_type, match_value, vendor)
        # Apply rule to all matching mails currently in triage or pending states
        actionable_statuses = ["mail_triage_needed", "mail_auto_selected", "mail_ignored"]
        matching_mails = repo.find_mails_matching_rule(match_type, match_value, actionable_statuses)
        for matched in matching_mails:
            matched_id = int(matched["id"])
            if rule_type == "always_process":
                repo.update_mail_status(matched_id, "mail_auto_selected")
                process_mail_now(app_settings, repo, matched)
            elif rule_type == "ignore":
                repo.update_mail_status(matched_id, "mail_ignored")
        return RedirectResponse("/", status_code=303)

    @app.post("/mails/{mail_id}/status")
    def update_mail_status(
        mail_id: int, status: str = Form(...), repo: Repository = Depends(get_repo)
    ) -> RedirectResponse:
        repo.update_mail_status(mail_id, status)
        if status == "mail_auto_selected":
            mail = repo.get_mail(mail_id)
            if mail:
                process_mail_now(app_settings, repo, mail)
        return RedirectResponse("/", status_code=303)

    @app.get("/mails/{mail_id}/pdf-preview")
    def mail_pdf_preview(
        mail_id: int, repo: Repository = Depends(get_repo)
    ) -> FileResponse:
        """Generate a temporary PDF preview of the mail (not saved to pipeline)."""
        import tempfile
        mail = repo.get_mail(mail_id)
        if not mail:
            raise HTTPException(status_code=404, detail="Mail not found")
        tmp = Path(tempfile.mktemp(suffix=".pdf"))
        mail_to_pdf(
            subject=mail["subject"] or "(no subject)",
            sender=mail["sender"] or "",
            recipients=mail.get("recipients", "") or "",
            sent_at=mail.get("sent_at"),
            body=mail.get("body", "") or "",
            output_path=tmp,
        )
        return FileResponse(tmp, media_type="application/pdf", filename="preview.pdf")

    @app.post("/mails/{mail_id}/to-pdf")
    def mail_to_pdf_route(
        mail_id: int, repo: Repository = Depends(get_repo)
    ) -> RedirectResponse:
        mail = repo.get_mail(mail_id)
        if not mail:
            raise HTTPException(status_code=404, detail="Mail not found")

        # Generate a sanitized filename
        subject_slug = "".join(
            c if c.isalnum() or c in " -_" else "" for c in (mail["subject"] or "mail")
        ).strip()[:60]
        date_prefix = (mail["sent_at"] or "")[:10].replace("-", "") or "nodate"
        filename = f"{date_prefix}_{subject_slug}.pdf"

        output_path = app_settings.raw_dir / filename
        mail_to_pdf(
            subject=mail["subject"] or "(no subject)",
            sender=mail["sender"] or "",
            recipients=mail.get("recipients", "") or "",
            sent_at=mail.get("sent_at"),
            body=mail.get("body", "") or "",
            output_path=output_path,
        )

        # Run through the document pipeline (handles hashing, dedup, metadata, rename)
        pipeline = AccountingPipeline(app_settings, repo)
        pipeline._process_local_file(output_path, RunSummary())

        # Mark mail as processed
        repo.update_mail_status(mail_id, "mail_auto_selected")
        return RedirectResponse("/", status_code=303)

    @app.post("/providers")
    def add_provider(
        provider: str = Form(...),
        url: str = Form(...),
        notes: str = Form(""),
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        repo.add_provider_task(provider, url, None, "provider_manual_link", notes)
        return RedirectResponse("/", status_code=303)

    @app.post("/documents/{document_id}/rename")
    def rename_document_route(
        document_id: int,
        vendor: str = Form(...),
        date: str = Form(...),
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        document = repo.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        source = Path(document["raw_path"])
        if not source.exists():
            raise HTTPException(status_code=404, detail="Source document file not found")
        final_filename, final_path = rename_document_as(source, vendor, date, app_settings.renamed_dir)
        repo.update_document_metadata(document_id, vendor, date, 1.0, "manual", "rename_needed")
        repo.mark_document_renamed(document_id, final_filename, str(final_path))
        return RedirectResponse("/", status_code=303)

    @app.post("/documents/{document_id}/ignore")
    def ignore_document_route(
        document_id: int,
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        document = repo.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        repo.update_document_status(document_id, "review_ignored")
        return RedirectResponse("/", status_code=303)

    @app.post("/documents/{document_id}/status")
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

    @app.post("/documents/bulk-status")
    def bulk_update_document_status(
        request: Request,
        repo: Repository = Depends(get_repo),
    ) -> RedirectResponse:
        """Bulk update status for multiple documents (by IDs or month filter)."""
        import asyncio
        body = asyncio.get_event_loop().run_until_complete(request.json())
        doc_ids: list[int] = body.get("ids", [])
        status: str = body.get("status", "")
        if not doc_ids or not status:
            raise HTTPException(status_code=400, detail="ids and status required")
        for doc_id in doc_ids:
            repo.update_document_status(doc_id, status)
        return JSONResponse({"ok": True, "count": len(doc_ids)})

    @app.post("/documents/bulk-delete")
    def bulk_delete_documents(
        request: Request,
        repo: Repository = Depends(get_repo),
    ) -> JSONResponse:
        """Permanently delete documents (they won't come back on re-scan)."""
        import asyncio
        body = asyncio.get_event_loop().run_until_complete(request.json())
        doc_ids: list[int] = body.get("ids", [])
        if not doc_ids:
            raise HTTPException(status_code=400, detail="ids required")
        for doc_id in doc_ids:
            repo.delete_document(doc_id)
        return JSONResponse({"ok": True, "count": len(doc_ids)})

    @app.post("/documents/bulk-rule")
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

        # Add the vendor rule (shared with mail rules)
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

    @app.get("/api/runs")
    def api_runs(repo: Repository = Depends(get_repo)) -> list[dict]:
        return repo.list_runs()

    @app.get("/api/mails")
    def api_mails(repo: Repository = Depends(get_repo)) -> list[dict]:
        return repo.list_mails()

    @app.get("/api/documents")
    def api_documents(repo: Repository = Depends(get_repo)) -> list[dict]:
        return repo.list_documents()

    @app.get("/api/provider-tasks")
    def api_provider_tasks(repo: Repository = Depends(get_repo)) -> list[dict]:
        return repo.list_provider_tasks()

    @app.get("/documents/{document_id}/raw")
    def raw_document(document_id: int, repo: Repository = Depends(get_repo)) -> FileResponse:
        document = repo.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return document_file_response(document["raw_path"], document["original_filename"])

    @app.get("/documents/{document_id}/preview/{filename:path}")
    def preview_document(
        document_id: int, filename: str, repo: Repository = Depends(get_repo)
    ) -> FileResponse:
        document = repo.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return preview_file_response(document["raw_path"], filename or document["original_filename"])

    @app.get("/documents/{document_id}/final")
    def final_document(document_id: int, repo: Repository = Depends(get_repo)) -> FileResponse:
        document = repo.get_document(document_id)
        if not document or not document.get("final_path"):
            raise HTTPException(status_code=404, detail="Document not found")
        return document_file_response(document["final_path"], document["final_filename"])

    @app.get("/mail-attachments/{attachment_id}/raw")
    def raw_mail_attachment(
        attachment_id: int, repo: Repository = Depends(get_repo)
    ) -> FileResponse:
        attachment = repo.get_mail_attachment(attachment_id)
        if not attachment or not attachment.get("path"):
            raise HTTPException(status_code=404, detail="Attachment not found")
        return document_file_response(attachment["path"], attachment["filename"])

    @app.get("/mail-attachments/{attachment_id}/preview/{filename:path}")
    def preview_mail_attachment(
        attachment_id: int, filename: str, repo: Repository = Depends(get_repo)
    ) -> FileResponse:
        attachment = repo.get_mail_attachment(attachment_id)
        if not attachment or not attachment.get("path"):
            raise HTTPException(status_code=404, detail="Attachment not found")
        return preview_file_response(attachment["path"], filename or attachment["filename"])

    @app.get("/api/export-preview")
    def api_export_preview(repo: Repository = Depends(get_repo)):
        """Return documents ready for export, grouped by YYYY/MM."""
        docs = repo.list_documents(status="doc_included")
        # Build tree grouped by date
        tree: dict[str, list] = {}
        for doc in docs:
            date_str = doc.get("detected_date") or ""
            if len(date_str) >= 7:
                folder = f"{date_str[:4]}/{date_str[5:7]}"
            else:
                folder = "unknown"
            tree.setdefault(folder, []).append(doc)
        return {"tree": tree, "total": len(docs)}

    @app.post("/api/export")
    def api_export(repo: Repository = Depends(get_repo)):
        """Move all included documents to output_dir/YYYY/MM/filename."""
        import shutil

        output_base = app_settings.output_dir
        # Allow override via app_state
        custom_output = repo.get_app_state("output_dir")
        if custom_output:
            output_base = Path(custom_output)

        docs = repo.list_documents(status="doc_included")
        moved = 0
        errors = []
        for doc in docs:
            date_str = doc.get("detected_date") or ""
            if len(date_str) >= 7:
                folder = f"{date_str[:4]}/{date_str[5:7]}"
            else:
                folder = "unknown"

            # Use final_path (renamed) if available, else raw_path
            source_path = Path(doc.get("final_path") or doc["raw_path"])
            if not source_path.exists():
                errors.append(f"Missing: {source_path.name}")
                continue

            filename = doc.get("final_filename") or source_path.name
            dest_dir = output_base / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / filename

            # Avoid overwriting
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

    @app.post("/api/settings/output-dir")
    async def api_set_output_dir(request: Request, repo: Repository = Depends(get_repo)):
        """Set the output directory for export."""
        body = await request.json()
        path = body.get("path", "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="Path is required")
        repo.set_app_state("output_dir", path)
        return {"path": path}

    @app.get("/api/settings/output-dir")
    def api_get_output_dir(repo: Repository = Depends(get_repo)):
        """Get the configured output directory."""
        custom = repo.get_app_state("output_dir")
        return {"path": custom or str(app_settings.output_dir)}

    return app


app = create_app()


def document_file_response(path_value: str, filename: str | None) -> FileResponse:
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found")
    display_name = filename or path.name
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": "inline"},
    )


def preview_file_response(path_value: str, filename: str | None) -> FileResponse:
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Document file not found")
    display_name = filename or path.name
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


def mail_rule_match_value(mail: dict, match_type: str) -> str:
    if match_type == "sender":
        return str(mail.get("sender") or "")
    if match_type == "domain":
        return email_domain(str(mail.get("sender") or ""))
    if match_type == "vendor":
        return str(mail.get("detected_vendor") or mail.get("sender") or "")
    raise HTTPException(status_code=400, detail="Unsupported rule match type")


def process_mail_now(settings: Settings, repo: Repository, mail: dict) -> None:
    pipeline = AccountingPipeline(settings, repo)
    for message in pipeline.spark.read_thread(str(mail["spark_message_id"]), download_attachments=True):
        if message.spark_message_id == str(mail["spark_message_id"]):
            pipeline.extract_message_artifacts(int(mail["id"]), message, RunSummary())
            break
