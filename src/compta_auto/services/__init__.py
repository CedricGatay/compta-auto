"""Credential management service."""

from __future__ import annotations

from cryptography.fernet import Fernet

from ..repositories import Repository
from .crypto import decrypt_value, encrypt_value, get_fernet as get_fernet

CREDENTIAL_KEYS = (
    "spotify_sp_dc",
    "chatgpt_bearer",
    "free_username",
    "free_password",
    "freebox_username",
    "freebox_password",
    "engie_email",
    "engie_password",
    "orange_username",
    "orange_password",
    "sosh_username",
    "sosh_password",
    "ovh_app_key",
    "ovh_app_secret",
    "ovh_consumer_key",
)


def get_credential(
    repo: Repository, key: str, form_value: str | None = None, *, fernet: Fernet | None = None
) -> str | None:
    """Return form value if provided, otherwise fall back to saved credential."""
    if form_value and form_value.strip():
        return form_value.strip()
    raw = repo.get_app_state(f"cred_{key}")
    if not raw:
        return None
    if fernet:
        decrypted = decrypt_value(fernet, raw)
        if decrypted:
            return decrypted
        # Fallback: value may be stored unencrypted (pre-migration)
        return raw
    return raw


def save_credential(repo: Repository, key: str, value: str, *, fernet: Fernet | None = None) -> None:
    """Save a credential value (encrypted if fernet provided)."""
    stored = encrypt_value(fernet, value) if fernet else value
    repo.set_app_state(f"cred_{key}", stored)


def get_all_credentials(repo: Repository, *, fernet: Fernet | None = None) -> dict[str, dict]:
    """Return all credentials (masked for display)."""
    creds = {}
    for key in CREDENTIAL_KEYS:
        raw = repo.get_app_state(f"cred_{key}")
        if raw:
            # Decrypt for hint generation
            val = decrypt_value(fernet, raw) if fernet else raw
            if not val:
                val = raw  # fallback for pre-migration data
            creds[key] = {
                "saved": True,
                "hint": val[:4] + "…" + val[-4:] if len(val) > 10 else "••••",
            }
        else:
            creds[key] = {"saved": False, "hint": ""}
    return creds


def delete_credential(repo: Repository, key: str) -> None:
    """Delete a saved credential from the database."""
    repo.delete_app_state(f"cred_{key}")

