"""Scanning routes (mail scan & folder scan)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import Settings
from ..db import Database
from ..models import DOCUMENT_EXTENSIONS
from ..pipeline import AccountingPipeline, RunSummary
from ..repositories import Repository
from .deps import get_settings, get_db

router = APIRouter(tags=["scan"])


@router.post("/scan")
def scan(
    months: int = Form(1),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> StreamingResponse:
    """Scan mail with SSE progress updates."""

    def event_stream():
        conn = db.connect()
        try:
            repo = Repository(conn)
            pipeline = AccountingPipeline(settings, repo)
            summary = RunSummary()
            run_id = repo.create_run()
            yield f"data: {json.dumps({'type': 'status', 'message': 'Searching emails…'})}\n\n"
            try:
                message_ids = pipeline.spark.search_candidate_ids(months)
                total = len(message_ids)
                yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"
                for i, message_id in enumerate(message_ids):
                    for message in pipeline.spark.read_thread(message_id, download_attachments=True):
                        summary.scanned_messages += 1
                        pipeline.process_message(message, summary)
                    yield f"data: {json.dumps({'type': 'progress', 'current': i + 1, 'total': total, 'new': summary.new_mails, 'triage': summary.triage_mails})}\n\n"
                repo.finish_run(run_id, "finished", summary.as_dict())
                conn.commit()
                yield f"data: {json.dumps({'type': 'complete', 'result': summary.as_dict()})}\n\n"
            except Exception as exc:
                summary.failures.append(str(exc))
                repo.finish_run(run_id, "failed", summary.as_dict())
                conn.commit()
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        finally:
            conn.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/scan-folder")
def scan_folder(
    folder: str = Form(...),
    timespan: str = Form("30"),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> StreamingResponse:
    """Scan folder with SSE progress updates."""
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")
    # Reject system paths to prevent scanning sensitive directories
    _BLOCKED_PREFIXES = ("/etc", "/var", "/usr", "/bin", "/sbin", "/System", "/Library")
    if any(str(folder_path).startswith(p) for p in _BLOCKED_PREFIXES):
        raise HTTPException(status_code=403, detail="Scanning system directories is not allowed")

    # Compute max_age_days before entering the generator
    if timespan == "since_last":
        conn_pre = db.connect()
        repo_pre = Repository(conn_pre)
        last_date_str = repo_pre.get_app_state("last_scan_folder_date")
        conn_pre.close()
        if last_date_str:
            last_dt = datetime.fromisoformat(last_date_str)
            delta = datetime.now(timezone.utc) - last_dt
            max_age_days = max(1, delta.days + 1)
        else:
            max_age_days = 30
    else:
        max_age_days = int(timespan)

    def event_stream():
        conn = db.connect()
        try:
            repo = Repository(conn)
            pipeline = AccountingPipeline(settings, repo)
            summary = RunSummary()
            run_id = repo.create_run()
            yield f"data: {json.dumps({'type': 'status', 'message': 'Scanning folder…'})}\n\n"
            try:
                cutoff = time.time() - (max_age_days * 86400)
                files = [
                    f for f in sorted(folder_path.iterdir())
                    if f.is_file() and f.suffix.lower() in DOCUMENT_EXTENSIONS
                    and f.stat().st_mtime >= cutoff
                ]
                total = len(files)
                yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"
                for i, file_path in enumerate(files):
                    summary.scanned_messages += 1
                    pipeline._process_local_file(file_path, summary)
                    if (i + 1) % 3 == 0 or i == total - 1:
                        yield f"data: {json.dumps({'type': 'progress', 'current': i + 1, 'total': total, 'renamed': summary.renamed, 'review': summary.rename_review_needed})}\n\n"
                repo.finish_run(run_id, "finished", summary.as_dict())
                repo.set_app_state("last_scan_folder", str(folder_path))
                repo.set_app_state("last_scan_folder_date", datetime.now(timezone.utc).isoformat())
                conn.commit()
                yield f"data: {json.dumps({'type': 'complete', 'result': summary.as_dict()})}\n\n"
            except Exception as exc:
                summary.failures.append(str(exc))
                repo.finish_run(run_id, "failed", summary.as_dict())
                conn.commit()
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        finally:
            conn.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/api/pick-folder")
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
