"""Credential encryption at rest using Fernet symmetric encryption.

The encryption key is derived from a stable machine-local secret stored
alongside the database. If the key file doesn't exist, one is generated
automatically on first use.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


_KEY_FILENAME = ".compta_key"


def _key_path(db_path: Path) -> Path:
    """Key file lives next to the database."""
    return db_path.parent / _KEY_FILENAME


def _load_or_create_key(db_path: Path) -> bytes:
    """Load existing key or generate a new one."""
    kp = _key_path(db_path)
    if kp.exists():
        return kp.read_bytes().strip()
    # Generate a new key and restrict permissions
    key = Fernet.generate_key()
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_bytes(key)
    try:
        os.chmod(kp, 0o600)
    except OSError:
        pass  # Windows or restricted FS
    return key


def get_fernet(db_path: Path) -> Fernet:
    """Return a Fernet instance using the app's encryption key."""
    key = _load_or_create_key(db_path)
    return Fernet(key)


def encrypt_value(fernet: Fernet, plaintext: str) -> str:
    """Encrypt a string, returning a base64-encoded ciphertext."""
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(fernet: Fernet, ciphertext: str) -> str | None:
    """Decrypt a ciphertext string. Returns None if decryption fails (corrupted/wrong key)."""
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
