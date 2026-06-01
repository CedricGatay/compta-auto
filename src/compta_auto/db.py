from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    summary TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vendor_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL CHECK(rule_type IN ('always_process', 'ignore')),
    match_type TEXT NOT NULL CHECK(match_type IN ('sender', 'domain', 'vendor')),
    match_value TEXT NOT NULL,
    vendor TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(rule_type, match_type, match_value)
);

CREATE TABLE IF NOT EXISTS mails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spark_message_id TEXT NOT NULL UNIQUE,
    sender TEXT NOT NULL,
    recipients TEXT NOT NULL,
    subject TEXT NOT NULL,
    sent_at TEXT,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    detected_vendor TEXT,
    extraction_reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id TEXT,
    original_filename TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mime_type TEXT,
    status TEXT NOT NULL,
    detected_vendor TEXT,
    detected_date TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    final_filename TEXT,
    final_path TEXT,
    extraction_method TEXT,
    canonical_document_id INTEGER REFERENCES documents(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_content_hash
ON documents(content_hash)
WHERE canonical_document_id IS NULL;

CREATE TABLE IF NOT EXISTS duplicate_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_document_id INTEGER NOT NULL REFERENCES documents(id),
    source_type TEXT NOT NULL,
    source_id TEXT,
    original_filename TEXT,
    content_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(canonical_document_id, source_type, source_id, original_filename)
);

CREATE TABLE IF NOT EXISTS provider_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    url TEXT NOT NULL,
    normalized_key TEXT NOT NULL UNIQUE,
    source_mail_id INTEGER REFERENCES mails(id),
    status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mail_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mail_id INTEGER NOT NULL REFERENCES mails(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    path TEXT,
    mime_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(mail_id, filename, path)
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
