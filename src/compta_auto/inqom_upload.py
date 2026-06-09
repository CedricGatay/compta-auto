from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Generator, Literal

from .config import Settings
from .inqom_uploader import InqomUploader
from .repositories import Repository

INQOM_READY_STATUSES = ("doc_included", "renamed")
INQOM_DOC_TYPES = {
    "purchase": "SupplierBill",
    "sale": "ClientBill",
}
InqomUploadSelection = Literal["purchase", "sale", "all"]


def get_document_upload_path(document: dict[str, Any]) -> Path | None:
    """Return the best available file path for upload."""
    final_path = document.get("final_path")
    if final_path:
        candidate = Path(final_path)
        if candidate.exists():
            return candidate

    raw_path = document.get("raw_path")
    if raw_path:
        candidate = Path(raw_path)
        if candidate.exists():
            return candidate

    return None


def list_inqom_upload_candidates(
    repo: Repository,
    accounting_type: InqomUploadSelection = "all",
) -> list[dict[str, Any]]:
    """List documents eligible for Inqom upload."""
    documents: list[dict[str, Any]] = []
    for status in INQOM_READY_STATUSES:
        for document in repo.list_documents(status=status):
            document_type = document.get("accounting_type")
            if document_type not in INQOM_DOC_TYPES:
                continue
            if accounting_type != "all" and document_type != accounting_type:
                continue

            upload_path = get_document_upload_path(document)
            if upload_path is None:
                continue

            documents.append({**document, "upload_path": str(upload_path)})

    return sorted(documents, key=lambda document: (str(document["accounting_type"]), int(document["id"])))


def group_inqom_upload_candidates(
    documents: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        grouped[str(document["accounting_type"])].append(document)
    return {key: grouped.get(key, []) for key in INQOM_DOC_TYPES}


def stream_inqom_upload(
    repo: Repository,
    settings: Settings,
    documents: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    headless: bool = True,
) -> Generator[dict[str, Any], None, None]:
    """Yield upload progress events for Inqom-ready documents."""
    grouped_documents = group_inqom_upload_candidates(documents)
    total = len(documents)
    uploaded_ids: list[int] = []
    errors: list[str] = []

    yield {
        "type": "start",
        "total": total,
        "groups": {group: len(group_docs) for group, group_docs in grouped_documents.items()},
        "dry_run": dry_run,
    }

    if total == 0:
        yield {"type": "done", "result": {"total": 0, "uploaded": 0, "errors": [], "dry_run": dry_run}}
        return

    if dry_run:
        for group_name, group_docs in grouped_documents.items():
            for document in group_docs:
                yield {
                    "type": "candidate",
                    "document_id": document["id"],
                    "accounting_type": group_name,
                    "doc_type": INQOM_DOC_TYPES[group_name],
                    "filename": document.get("final_filename") or Path(document["upload_path"]).name,
                    "path": document["upload_path"],
                    "status": document["status"],
                }
        yield {"type": "done", "result": {"total": total, "uploaded": 0, "errors": [], "dry_run": True}}
        return

    if not settings.inqom_email or not settings.inqom_password or not settings.inqom_client_id:
        yield {
            "type": "error",
            "error": "Missing Inqom configuration. Set COMPTA_INQOM_EMAIL, COMPTA_INQOM_PASSWORD, and COMPTA_INQOM_CLIENT_ID.",
        }
        yield {"type": "done", "result": {"total": total, "uploaded": 0, "errors": ["missing_config"]}}
        return

    try:
        with InqomUploader(
            settings.inqom_email,
            settings.inqom_password,
            client_id=settings.inqom_client_id,
            headless=headless,
        ) as uploader:
            for group_name, group_docs in grouped_documents.items():
                if not group_docs:
                    continue

                doc_type = INQOM_DOC_TYPES[group_name]
                yield {
                    "type": "group_start",
                    "accounting_type": group_name,
                    "doc_type": doc_type,
                    "count": len(group_docs),
                }
                documents_by_path = {
                    str(Path(document["upload_path"]).resolve()): document for document in group_docs
                }
                file_paths = [Path(document["upload_path"]) for document in group_docs]
                for event in uploader.upload_documents_stream(file_paths, doc_type=doc_type):
                    enriched_event = {**event, "accounting_type": group_name, "doc_type": doc_type}
                    if event.get("type") == "uploaded":
                        document = documents_by_path.get(str(Path(event["file_path"]).resolve()))
                        if document is not None:
                            repo.update_document_status(int(document["id"]), "uploaded_to_inqom")
                            uploaded_ids.append(int(document["id"]))
                            enriched_event["document_id"] = document["id"]
                            enriched_event["status"] = "uploaded_to_inqom"
                    elif event.get("type") == "error":
                        errors.append(str(event["error"]))
                    elif event.get("type") == "done":
                        enriched_event = {
                            **enriched_event,
                            "type": "group_done",
                            "result": {
                                **event["result"],
                                "accounting_type": group_name,
                                "doc_type": doc_type,
                            },
                        }
                        errors.extend(event["result"]["errors"])
                    yield enriched_event
    except Exception as exc:
        errors.append(str(exc))
        yield {"type": "error", "error": str(exc)}

    yield {
        "type": "done",
        "result": {
            "total": total,
            "uploaded": len(uploaded_ids),
            "uploaded_ids": uploaded_ids,
            "errors": errors,
            "dry_run": False,
        },
    }
