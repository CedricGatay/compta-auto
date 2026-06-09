"""Credential management routes."""

from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request

from ..repositories import Repository
from ..services import (
    CREDENTIAL_KEYS,
    delete_credential,
    get_all_credentials,
    save_credential,
)
from .deps import get_fernet, get_repo

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


@router.get("")
def api_get_credentials(
    repo: Repository = Depends(get_repo),
    fernet: Fernet = Depends(get_fernet),
):
    """Return saved credentials (values masked for display)."""
    return get_all_credentials(repo, fernet=fernet)


@router.post("")
async def api_save_credentials(
    request: Request,
    repo: Repository = Depends(get_repo),
    fernet: Fernet = Depends(get_fernet),
):
    """Save one or more credentials."""
    body = await request.json()
    saved = []
    for key in CREDENTIAL_KEYS:
        if key in body and body[key]:
            save_credential(repo, key, body[key], fernet=fernet)
            saved.append(key)
    return {"saved": saved}


@router.delete("/{key}")
def api_delete_credential(key: str, repo: Repository = Depends(get_repo)):
    """Delete a saved credential."""
    if key not in CREDENTIAL_KEYS:
        raise HTTPException(status_code=400, detail="Invalid credential key")
    delete_credential(repo, key)
    return {"deleted": key}
