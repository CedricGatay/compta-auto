"""Vendor rules routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse, RedirectResponse

from ..repositories import Repository
from .deps import get_repo

router = APIRouter(tags=["rules"])


@router.post("/rules")
def add_rule(
    rule_type: str = Form(...),
    match_type: str = Form(...),
    match_value: str = Form(...),
    vendor: str = Form(""),
    repo: Repository = Depends(get_repo),
) -> RedirectResponse:
    repo.add_rule(rule_type, match_type, match_value, vendor or None)
    return RedirectResponse("/", status_code=303)


@router.post("/rules/{rule_id}/delete")
def delete_rule(rule_id: int, repo: Repository = Depends(get_repo)) -> RedirectResponse:
    repo.delete_rule(rule_id)
    return RedirectResponse("/", status_code=303)


@router.post("/providers")
def add_provider(
    provider: str = Form(...),
    url: str = Form(...),
    notes: str = Form(""),
    repo: Repository = Depends(get_repo),
) -> RedirectResponse:
    repo.add_provider_task(provider, url, None, "provider_manual_link", notes)
    return RedirectResponse("/", status_code=303)


@router.post("/api/dismiss-provider-suggestion")
def dismiss_provider_suggestion(
    vendor: str = Form(...),
    repo: Repository = Depends(get_repo),
) -> JSONResponse:
    repo.dismiss_provider_suggestion(vendor)
    return JSONResponse({"ok": True})


@router.get("/api/runs")
def api_runs(repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_runs()


@router.get("/api/provider-tasks")
def api_provider_tasks(repo: Repository = Depends(get_repo)) -> list[dict]:
    return repo.list_provider_tasks()
