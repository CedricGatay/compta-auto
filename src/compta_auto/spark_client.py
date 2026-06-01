from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .models import Attachment, MailMessage


class SparkClient:
    def search_candidate_ids(self, months: int = 1) -> list[str]:
        filter_value = f"newer_than:{months}m"
        result = subprocess.run(
            ["spark", "emails", "--filter", filter_value, "--page-size", "100"],
            check=True,
            capture_output=True,
            text=True,
        )
        return parse_email_ids(result.stdout)

    def read_thread(self, message_id: str, download_attachments: bool = True) -> list[MailMessage]:
        cmd = ["spark", "thread"]
        if download_attachments:
            cmd.append("--download-attachments")
        cmd.append(message_id)
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return parse_thread_output(result.stdout)


def parse_email_ids(output: str) -> list[str]:
    ids: list[str] = []
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\s+", line)
        if match:
            ids.append(match.group(1))
    return ids


def parse_thread_output(output: str) -> list[MailMessage]:
    messages: list[MailMessage] = []
    chunks = re.split(r"\n(?=Message\s+\d+\b)", output)
    for chunk in chunks:
        message = parse_message_chunk(chunk)
        if message:
            messages.append(message)
    return messages


def parse_message_chunk(chunk: str) -> MailMessage | None:
    id_match = re.search(r"(?:Message|ID):\s*(\d+)", chunk, re.IGNORECASE)
    if not id_match:
        first_line = chunk.strip().splitlines()[0] if chunk.strip() else ""
        id_match = re.match(r"(?:#+\s*)?Message\s+(\d+)", first_line, re.IGNORECASE)
    if not id_match:
        return None

    sender = find_header(chunk, "From") or find_header(chunk, "Sender") or ""
    recipients = split_recipients(
        find_header(chunk, "To")
        or find_header(chunk, "Recipients")
        or find_header(chunk, "Delivered-To")
        or ""
    )
    subject = find_header(chunk, "Subject") or ""
    sent_at = find_header(chunk, "Date")
    body = extract_body(chunk)
    attachments = parse_attachments(chunk)
    return MailMessage(
        spark_message_id=id_match.group(1),
        sender=extract_email(sender),
        recipients=[extract_email(r) for r in recipients if r.strip()],
        subject=subject.strip(),
        sent_at=sent_at.strip() if sent_at else None,
        body=body,
        attachments=attachments,
    )


def find_header(text: str, name: str) -> str | None:
    match = re.search(
        rf"^\s*(?:[-*]\s*)?(?:\*\*{re.escape(name)}:\*\*|(?:\*\*)?{re.escape(name)}(?:\*\*)?\s*:)\s*(.+)$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def split_recipients(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]


def extract_email(value: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
    return match.group(0).lower() if match else value.strip().lower()


def extract_body(chunk: str) -> str:
    marker = re.search(r"^Body:\s*$", chunk, re.MULTILINE | re.IGNORECASE)
    if marker:
        return chunk[marker.end() :].strip()
    parts = re.split(r"^Attachments?:", chunk, flags=re.MULTILINE | re.IGNORECASE)
    return parts[0].strip()


def parse_attachments(chunk: str) -> list[Attachment]:
    attachments: list[Attachment] = []
    current_filename: str | None = None
    for line in chunk.splitlines():
        filename_match = re.search(
            r"^\s*-\s+(.+\.(?:pdf|png|jpg|jpeg|webp|tif|tiff))\s*(?:\(|downloaded\b|$)",
            line,
            re.IGNORECASE,
        )
        if filename_match and "downloaded" not in line.lower():
            current_filename = filename_match.group(1).strip()
            continue

        path_match = re.search(
            r"^\s*Path:\s*(.+\.(?:pdf|png|jpg|jpeg|webp|tif|tiff))\s*$",
            line,
            re.IGNORECASE,
        )
        if path_match:
            path = Path(path_match.group(1).strip())
            filename = current_filename or path.name
            attachments.append(Attachment(filename=filename, path=path))
            current_filename = None
            continue

        if "attachment" not in line.lower() and "downloaded" not in line.lower():
            continue
        inline_path_match = re.search(r"(/.+\.(?:pdf|png|jpg|jpeg|webp|tif|tiff))", line, re.IGNORECASE)
        inline_filename_match = re.search(
            r"([\w .@()+-]+\.(?:pdf|png|jpg|jpeg|webp|tif|tiff))", line, re.IGNORECASE
        )
        path = Path(inline_path_match.group(1).strip()) if inline_path_match else None
        filename = (
            inline_filename_match.group(1).strip(" -*")
            if inline_filename_match
            else (path.name if path else "")
        )
        if filename:
            attachments.append(Attachment(filename=filename, path=path))
    return attachments
