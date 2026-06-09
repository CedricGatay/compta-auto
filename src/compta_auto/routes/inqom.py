from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..config import Settings
from ..inqom_upload import list_inqom_upload_candidates, stream_inqom_upload
from ..repositories import Repository
from .deps import get_repo, get_settings

router = APIRouter(tags=["inqom"])


@router.post("/api/inqom-upload")
def api_inqom_upload(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Upload ready documents to Inqom and stream progress as SSE."""
    documents = list_inqom_upload_candidates(repo)

    def event_stream():
        for event in stream_inqom_upload(repo, settings, documents):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
