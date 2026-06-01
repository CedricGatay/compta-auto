from __future__ import annotations

import shutil
from pathlib import Path

from .files import unique_path
from .models import ExtractedMetadata
from .normalize import safe_filename_stem


def rename_document(
    source: Path,
    metadata: ExtractedMetadata,
    output_dir: Path,
    min_confidence: float,
) -> tuple[str, Path] | None:
    if not metadata.vendor or not metadata.date or metadata.confidence < min_confidence:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_dir / f"{safe_filename_stem(metadata.date, metadata.vendor)}{source.suffix.lower()}")
    shutil.copy2(source, target)
    return target.name, target


def rename_document_as(source: Path, vendor: str, date_value: str, output_dir: Path) -> tuple[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_dir / f"{safe_filename_stem(date_value, vendor)}{source.suffix.lower()}")
    shutil.copy2(source, target)
    return target.name, target
