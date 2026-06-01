from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_attachment(raw_dir: Path, filename: str, content: bytes | None, source_path: Path | None) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(raw_dir / Path(filename).name)
    if content is not None:
        target.write_bytes(content)
    elif source_path is not None:
        shutil.copy2(source_path, target)
    else:
        raise ValueError(f"Attachment {filename} has no content or source path")
    return target


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1

