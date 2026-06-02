from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .db import row_to_dict, rows_to_dicts
from .links import find_invoice_links
from .normalize import (
    email_domain,
    normalize_email,
    normalize_url,
    normalize_vendor,
    safe_filename_stem,
)


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs DEFAULT VALUES")
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, summary: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = CURRENT_TIMESTAMP, status = ?, summary = ? WHERE id = ?",
            (status, json.dumps(summary, sort_keys=True), run_id),
        )

    def list_runs(self) -> list[dict[str, Any]]:
        return rows_to_dicts(self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 20"))

    def add_rule(
        self, rule_type: str, match_type: str, match_value: str, vendor: str | None = None
    ) -> int:
        normalized = normalize_vendor(match_value) if match_type == "vendor" else match_value.lower()
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO vendor_rules(rule_type, match_type, match_value, vendor)
            VALUES (?, ?, ?, ?)
            """,
            (rule_type, match_type, normalized, normalize_vendor(vendor) if vendor else None),
        )
        return int(cur.lastrowid)

    def delete_rule(self, rule_id: int) -> None:
        self.conn.execute("DELETE FROM vendor_rules WHERE id = ?", (rule_id,))

    def list_rules(self) -> list[dict[str, Any]]:
        return rows_to_dicts(
            self.conn.execute("SELECT * FROM vendor_rules ORDER BY rule_type, match_type, match_value")
        )

    def classify_by_rules(self, sender: str, detected_vendor: str | None) -> tuple[str | None, str | None]:
        sender_norm = normalize_email(sender)
        domain = email_domain(sender)
        vendor_norm = normalize_vendor(detected_vendor)
        candidates = [
            ("sender", sender_norm),
            ("domain", domain),
            ("vendor", vendor_norm),
        ]
        for match_type, match_value in candidates:
            if not match_value:
                continue
            row = self.conn.execute(
                """
                SELECT rule_type, vendor FROM vendor_rules
                WHERE match_type = ? AND match_value = ?
                ORDER BY id DESC LIMIT 1
                """,
                (match_type, match_value),
            ).fetchone()
            if row:
                return str(row["rule_type"]), row["vendor"]
        return None, None

    def get_mail_by_spark_id(self, spark_message_id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute(
                "SELECT * FROM mails WHERE spark_message_id = ?", (spark_message_id,)
            ).fetchone()
        )

    def get_mail(self, mail_id: int) -> dict[str, Any] | None:
        return row_to_dict(self.conn.execute("SELECT * FROM mails WHERE id = ?", (mail_id,)).fetchone())

    def upsert_mail(
        self,
        spark_message_id: str,
        sender: str,
        recipients: list[str],
        subject: str,
        sent_at: str | None,
        body: str,
        status: str,
        detected_vendor: str | None,
        extraction_reason: str,
    ) -> tuple[int, bool]:
        existing = self.get_mail_by_spark_id(spark_message_id)
        if existing:
            return int(existing["id"]), False
        cur = self.conn.execute(
            """
            INSERT INTO mails(
                spark_message_id, sender, recipients, subject, sent_at, body,
                status, detected_vendor, extraction_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spark_message_id,
                normalize_email(sender),
                json.dumps([normalize_email(r) for r in recipients]),
                subject,
                sent_at,
                body,
                status,
                normalize_vendor(detected_vendor),
                extraction_reason,
            ),
        )
        return int(cur.lastrowid), True

    def update_mail_status(self, mail_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE mails SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, mail_id),
        )

    def find_mails_matching_rule(
        self, match_type: str, match_value: str, statuses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Find all mails that match a rule criteria."""
        if match_type == "sender":
            condition = "LOWER(sender) = ?"
            param = match_value.lower()
        elif match_type == "domain":
            condition = "LOWER(sender) LIKE ?"
            param = f"%@{match_value.lower()}"
        elif match_type == "vendor":
            condition = "LOWER(detected_vendor) = ?"
            param = match_value.lower()
        else:
            return []

        query = f"SELECT * FROM mails WHERE {condition}"
        params: list[Any] = [param]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        return rows_to_dicts(self.conn.execute(query, params))

    def refresh_mail_metadata(
        self,
        mail_id: int,
        sender: str,
        recipients: list[str],
        subject: str,
        sent_at: str | None,
        body: str,
        detected_vendor: str | None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE mails
            SET sender = COALESCE(NULLIF(sender, ''), ?),
                recipients = CASE WHEN recipients IN ('', '[]') THEN ? ELSE recipients END,
                subject = COALESCE(NULLIF(subject, ''), ?),
                sent_at = COALESCE(sent_at, ?),
                body = COALESCE(NULLIF(body, ''), ?),
                detected_vendor = COALESCE(NULLIF(detected_vendor, ''), ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalize_email(sender),
                json.dumps([normalize_email(r) for r in recipients]),
                subject,
                sent_at,
                body,
                normalize_vendor(detected_vendor),
                mail_id,
            ),
        )

    def list_mails(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return [
                self.enrich_mail_with_attachments(row)
                for row in rows_to_dicts(
                    self.conn.execute("SELECT * FROM mails WHERE status = ? ORDER BY id DESC", (status,))
                )
            ]
        return [
            self.enrich_mail_with_attachments(row)
            for row in rows_to_dicts(self.conn.execute("SELECT * FROM mails ORDER BY id DESC LIMIT 200"))
        ]

    def enrich_mail_with_attachments(self, row: dict[str, Any]) -> dict[str, Any]:
        attachments = [
            enrich_mail_attachment(attachment)
            for attachment in rows_to_dicts(
                self.conn.execute(
                    "SELECT * FROM mail_attachments WHERE mail_id = ? ORDER BY filename",
                    (row["id"],),
                )
            )
        ]
        enriched = enrich_mail(row, attachments)
        enriched["attachments"] = attachments
        return enriched

    def upsert_mail_attachment(
        self, mail_id: int, filename: str, path: str | None, mime_type: str | None
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO mail_attachments(mail_id, filename, path, mime_type)
            VALUES (?, ?, ?, ?)
            """,
            (mail_id, filename, path, mime_type),
        )

    def list_mail_attachments(self, mail_id: int) -> list[dict[str, Any]]:
        return [
            enrich_mail_attachment(row)
            for row in rows_to_dicts(
                self.conn.execute(
                    "SELECT * FROM mail_attachments WHERE mail_id = ? ORDER BY filename",
                    (mail_id,),
                )
            )
        ]

    def get_mail_attachment(self, attachment_id: int) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute(
                "SELECT * FROM mail_attachments WHERE id = ?", (attachment_id,)
            ).fetchone()
        )

    def get_document_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute(
                """
                SELECT * FROM documents
                WHERE content_hash = ? AND canonical_document_id IS NULL
                """,
                (content_hash,),
            ).fetchone()
        )

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        )

    def count_documents_for_source(self, source_type: str, source_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM documents WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        ).fetchone()
        return int(row["count"]) if row else 0

    def add_document(
        self,
        source_type: str,
        source_id: str | None,
        original_filename: str,
        raw_path: str,
        content_hash: str,
        mime_type: str | None,
        status: str,
    ) -> tuple[int, bool]:
        existing = self.get_document_by_hash(content_hash)
        if existing:
            self.add_duplicate_source(
                int(existing["id"]), source_type, source_id, original_filename, content_hash
            )
            return int(existing["id"]), False
        cur = self.conn.execute(
            """
            INSERT INTO documents(
                source_type, source_id, original_filename, raw_path, content_hash, mime_type, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source_type, source_id, original_filename, raw_path, content_hash, mime_type, status),
        )
        return int(cur.lastrowid), True

    def add_duplicate_source(
        self,
        canonical_document_id: int,
        source_type: str,
        source_id: str | None,
        original_filename: str | None,
        content_hash: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO duplicate_sources(
                canonical_document_id, source_type, source_id, original_filename, content_hash
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (canonical_document_id, source_type, source_id, original_filename, content_hash),
        )

    def update_document_metadata(
        self,
        document_id: int,
        vendor: str | None,
        date: str | None,
        confidence: float,
        method: str,
        status: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE documents
            SET detected_vendor = ?, detected_date = ?, confidence = ?, extraction_method = ?,
                status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalize_vendor(vendor), date, confidence, method, status, document_id),
        )

    def mark_document_renamed(self, document_id: int, final_filename: str, final_path: str) -> None:
        self.conn.execute(
            """
            UPDATE documents
            SET status = 'renamed', final_filename = ?, final_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (final_filename, final_path, document_id),
        )

    def update_document_status(self, document_id: int, status: str) -> None:
        self.conn.execute(
            """
            UPDATE documents
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, document_id),
        )

    def bulk_update_document_status_by_sender(
        self, match_type: str, match_value: str, target_status: str
    ) -> None:
        """Move all documents from a matching sender/domain to the target status."""
        if match_type == "domain":
            self.conn.execute(
                """
                UPDATE documents SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE source_type = 'mail_attachment'
                AND CAST(source_id AS INTEGER) IN (
                    SELECT id FROM mails WHERE sender LIKE ?
                )
                AND status IN ('rename_review_needed', 'doc_included', 'review_ignored')
                """,
                (target_status, f"%@{match_value.lower()}"),
            )
        else:
            self.conn.execute(
                """
                UPDATE documents SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE source_type = 'mail_attachment'
                AND CAST(source_id AS INTEGER) IN (
                    SELECT id FROM mails WHERE LOWER(sender) = LOWER(?)
                )
                AND status IN ('rename_review_needed', 'doc_included', 'review_ignored')
                """,
                (target_status, match_value),
            )

    def list_documents(self, status: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT
                documents.*,
                mails.sender AS mail_sender,
                mails.recipients AS mail_recipients,
                mails.subject AS mail_subject
            FROM documents
            LEFT JOIN mails
                ON documents.source_type = 'mail_attachment'
                AND CAST(documents.source_id AS INTEGER) = mails.id
        """
        if status:
            return [
                enrich_document(row)
                for row in rows_to_dicts(
                    self.conn.execute(f"{query} WHERE documents.status = ? ORDER BY documents.id DESC", (status,))
                )
            ]
        return [
            enrich_document(row)
            for row in rows_to_dicts(
                self.conn.execute(f"{query} ORDER BY documents.id DESC LIMIT 200")
            )
        ]

    def add_provider_task(
        self,
        provider: str,
        url: str,
        source_mail_id: int | None,
        status: str,
        notes: str = "",
    ) -> tuple[int, bool]:
        key = f"{normalize_vendor(provider) or 'unknown'}:{normalize_url(url)}"
        existing = self.conn.execute(
            "SELECT id FROM provider_tasks WHERE normalized_key = ?", (key,)
        ).fetchone()
        if existing:
            return int(existing["id"]), False
        cur = self.conn.execute(
            """
            INSERT INTO provider_tasks(provider, url, normalized_key, source_mail_id, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalize_vendor(provider) or provider, url, key, source_mail_id, status, notes),
        )
        return int(cur.lastrowid), True

    def list_provider_tasks(self) -> list[dict[str, Any]]:
        return rows_to_dicts(self.conn.execute("SELECT * FROM provider_tasks ORDER BY id DESC"))

    def get_app_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def set_app_state(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )

    def reset_all(self) -> None:
        """Delete all data except vendor_rules. Keeps whitelist/blacklist intact."""
        self.conn.execute("DELETE FROM duplicate_sources")
        self.conn.execute("DELETE FROM documents")
        self.conn.execute("DELETE FROM mail_attachments")
        self.conn.execute("DELETE FROM provider_tasks")
        self.conn.execute("DELETE FROM mails")
        self.conn.execute("DELETE FROM runs")


def enrich_mail(row: dict[str, Any], attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    row = row.copy()
    recipients = parse_json_list(row.get("recipients"))
    row["recipients_list"] = recipients
    row["recipients_display"] = ", ".join(recipients)
    row["download_links"] = find_invoice_links(str(row.get("body") or ""))
    row["preview_items"] = mail_preview_items(attachments or [], row["download_links"])
    return row


def enrich_mail_attachment(row: dict[str, Any]) -> dict[str, Any]:
    row = row.copy()
    row["preview_kind"] = preview_kind(row.get("path") or row.get("filename") or "")
    row["preview_label"] = preview_label(row["preview_kind"])
    row["open_url"] = f"/mail-attachments/{row['id']}/raw" if row.get("path") else ""
    row["preview_url"] = (
        f"/mail-attachments/{row['id']}/preview/{quote(str(row.get('filename') or 'attachment'), safe='')}"
        if row.get("path")
        else ""
    )
    row["modal_preview_kind"] = row["preview_kind"]
    return row


def mail_preview_items(
    attachments: list[dict[str, Any]], download_links: list[str]
) -> list[dict[str, Any]]:
    if attachments:
        return attachments
    return [
        {
            "type": "link",
            "url": url,
            "label": "LINK",
            "display_name": preview_link_label(url),
        }
        for url in download_links
    ]


def preview_link_label(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").split("?", 1)[0][:48]


def enrich_document(row: dict[str, Any]) -> dict[str, Any]:
    row = row.copy()
    recipients = parse_json_list(row.get("mail_recipients"))
    row["mail_recipients_list"] = recipients
    row["mail_recipients_display"] = ", ".join(recipients)
    row["source_from_display"] = row.get("mail_sender") or ""
    row["source_to_display"] = row["mail_recipients_display"]
    row["supposed_filename"] = supposed_filename(row)
    row["preview_kind"] = preview_kind(row.get("raw_path") or row.get("original_filename") or "")
    row["preview_label"] = preview_label(row["preview_kind"])
    row["raw_open_url"] = f"/documents/{row['id']}/raw"
    row["raw_preview_url"] = (
        f"/documents/{row['id']}/preview/{quote(str(row.get('original_filename') or 'document'), safe='')}"
    )
    row["modal_preview_kind"] = row["preview_kind"]
    row["final_preview_url"] = f"/documents/{row['id']}/final" if row.get("final_path") else None
    # Month key for grouping (YYYY-MM or "Unknown")
    detected_date = row.get("detected_date") or ""
    row["month_key"] = detected_date[:7] if len(detected_date) >= 7 else "Unknown"
    return row


def parse_json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return [str(value)]
    if isinstance(loaded, list):
        return [str(item) for item in loaded if item]
    return [str(loaded)]


def supposed_filename(row: dict[str, Any]) -> str:
    final_filename = row.get("final_filename")
    if final_filename:
        return str(final_filename)
    vendor = row.get("detected_vendor")
    detected_date = row.get("detected_date")
    if vendor and detected_date:
        suffix = Path(str(row.get("original_filename") or row.get("raw_path") or "")).suffix.lower()
        return f"{safe_filename_stem(str(detected_date), str(vendor))}{suffix}"
    return ""


def preview_kind(path_value: str) -> str:
    suffix = Path(path_value).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    return "file"


def preview_label(kind: str) -> str:
    if kind == "image":
        return "IMG"
    if kind == "pdf":
        return "PDF"
    return "FILE"
