"""OTP code reader that polls the Spark mailbox for incoming OTP emails."""

from __future__ import annotations

import logging
import re
import subprocess
import time
from datetime import datetime, time as datetime_time, timezone

logger = logging.getLogger(__name__)

# Known OTP sender patterns
FREE_MOBILE_OTP_SENDERS = ["free-mobile.fr", "free.fr"]
ENGIE_OTP_SENDERS = ["okta.com", "engie.fr", "engie.com"]


class OtpReadError(Exception):
    """Raised when OTP cannot be read from mailbox."""


def recent_mail_ids() -> set[str]:
    """Snapshot recent Spark message IDs before requesting a provider OTP."""
    try:
        result = subprocess.run(
            ["spark", "emails", "--filter", "newer_than:1d", "--page-size", "100"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Unable to snapshot Spark message IDs: %s", exc)
        return set()
    if result.returncode != 0:
        logger.warning("Spark message ID snapshot failed: %s", result.stderr.strip())
        return set()
    ids = {
        match.group(1)
        for line in result.stdout.splitlines()
        if (match := re.match(r"\s*(\d+)\s+", line))
    }
    logger.info("Snapshotted %s recent Spark message IDs before OTP request", len(ids))
    return ids


def latest_mail_summary() -> str | None:
    """Return Spark's newest mail row, for a visible OTP polling status."""
    logger.info("Spark mailbox status query started")
    try:
        result = subprocess.run(
            ["spark", "emails", "--filter", "newer_than:1d", "--page-size", "1"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Unable to retrieve Spark mailbox status: %s", exc)
        return None
    if result.returncode != 0:
        logger.warning("spark emails failed while retrieving mailbox status: %s", result.stderr)
        return None
    for line in result.stdout.splitlines():
        if re.match(r"\s*\d+\s+", line):
            summary = re.sub(r"\s+", " ", line).strip()[:240]
            logger.info("Spark mailbox status query completed: latest mail found")
            return summary
    logger.info("Spark mailbox status query completed: no mail rows found")
    return None


class OtpMailReader:
    """Reads OTP codes from the Spark mailbox by polling for recent emails."""

    def __init__(
        self,
        timeout: int = 90,
        poll_interval: int = 5,
        initial_delay: int = 0,
    ):
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.initial_delay = initial_delay

    def wait_for_otp(
        self,
        sender_keywords: list[str],
        subject_keywords: list[str],
        started_at: datetime | None = None,
        code_length: int = 6,
        include_read: bool = False,
        excluded_message_ids: set[str] | None = None,
    ) -> str:
        """
        Poll the mailbox for an OTP email and extract the code.

        Args:
            sender_keywords: domains/addresses to filter by (e.g. ["free.fr"])
            subject_keywords: keywords expected in subject (e.g. ["code", "vérification"])
            started_at: only consider emails after this timestamp
            code_length: expected OTP code length (default 6)

        Returns:
            The extracted OTP code string.

        Raises:
            OtpReadError: if no OTP found within timeout.
        """
        if started_at is None:
            started_at = datetime.now(timezone.utc)
        elif started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        logger.info(
            "Starting Spark OTP polling: timeout=%ss, include_read=%s, senders=%s",
            self.timeout,
            include_read,
            sender_keywords,
        )
        deadline = time.time() + self.timeout
        attempt = 0
        if self.initial_delay > 0:
            time.sleep(min(self.initial_delay, self.timeout))

        while time.time() < deadline:
            attempt += 1
            logger.info("Spark OTP poll attempt %s started", attempt)

            try:
                code = self._try_find_otp(
                    sender_keywords,
                    subject_keywords,
                    started_at,
                    code_length,
                    include_read,
                    excluded_message_ids,
                )
                if code:
                    logger.info("Spark OTP code found on attempt %s", attempt)
                    return code
            except Exception as exc:
                logger.warning("Spark OTP poll attempt %s failed: %s", attempt, exc)

            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(self.poll_interval, remaining))

        raise OtpReadError(
            f"No OTP email found within {self.timeout}s. "
            f"Checked for senders matching {sender_keywords}."
        )

    def _try_find_otp(
        self,
        sender_keywords: list[str],
        subject_keywords: list[str],
        started_at: datetime,
        code_length: int,
        include_read: bool = False,
        excluded_message_ids: set[str] | None = None,
    ) -> str | None:
        """Single attempt to find an OTP code in recent emails."""
        # A forced refresh must also consider a message that another client
        # (or a prior Spark query) has already marked as read.
        filter_parts = ["newer_than:1d"]
        if not include_read:
            filter_parts.insert(0, "is:unread")
        filter_str = " ".join(filter_parts)
        logger.info("Running Spark OTP mail query with filter %r", filter_str)

        result = subprocess.run(
            ["spark", "emails", "--filter", filter_str, "--page-size", "20"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Spark OTP mail query failed: %s", result.stderr.strip())
            return None

        # Parse email IDs and find candidates
        candidate_ids = self._filter_candidates(
            result.stdout, sender_keywords, subject_keywords, started_at
        )
        if excluded_message_ids:
            candidate_ids = [candidate for candidate in candidate_ids if candidate not in excluded_message_ids]
        logger.info("Spark OTP mail query completed: %s candidate(s)", len(candidate_ids))

        if not candidate_ids:
            return None

        # Read each candidate thread and extract OTP
        for email_id in candidate_ids:
            logger.info("Reading Spark OTP candidate thread %s", email_id)
            code = self._extract_otp_from_thread(email_id, code_length, sender_keywords)
            if code:
                logger.info("OTP extracted from Spark thread %s", email_id)
                return code
            logger.info("No OTP extracted from Spark thread %s", email_id)

        return None

    def _filter_candidates(
        self,
        emails_output: str,
        sender_keywords: list[str],
        subject_keywords: list[str],
        started_at: datetime,
    ) -> list[str]:
        """Filter email list output to find OTP email candidates."""
        fresh_candidates: list[tuple[datetime, str]] = []
        lines = emails_output.strip().splitlines()
        # Spark's list view only reports timestamps to the minute. Compare at
        # that same precision so a code delivered later in the request minute
        # is not rejected as older merely because it lacks seconds.
        started_at_minute = started_at.replace(second=0, microsecond=0)

        for line in lines:
            # spark emails output format: "  ID  From  Subject  Date"
            line_lower = line.lower()

            # Spark truncates long sender addresses in its list output (for
            # example, noreply@authentifi…). A matching OTP subject is enough
            # to inspect the thread; the complete sender is validated there.
            sender_match = any(kw.lower() in line_lower for kw in sender_keywords)
            subject_match = (
                not subject_keywords
                or any(kw.lower() in line_lower for kw in subject_keywords)
            )
            if not sender_match and not subject_match:
                continue

            # Extract the ID from the line
            id_match = re.match(r"\s*(\d+)\s+", line)
            if id_match:
                email_id = id_match.group(1)
                received_at = _parse_spark_line_datetime(line)
                if received_at and received_at >= started_at_minute:
                    fresh_candidates.append((received_at, email_id))

        # Spark normally lists newest first, but enforce it here. The ID is a
        # tie-breaker for codes received within the same displayed minute.
        fresh_candidates.sort(key=lambda candidate: (candidate[0], int(candidate[1])), reverse=True)
        return [email_id for _, email_id in fresh_candidates]

    def _extract_otp_from_thread(
        self, email_id: str, code_length: int, sender_keywords: list[str]
    ) -> str | None:
        """Read an email thread, validate its sender, and extract its OTP code."""
        result = subprocess.run(
            ["spark", "thread", email_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Spark thread %s could not be read: %s", email_id, result.stderr.strip())
            return None

        sender_match = re.search(r"^\s*From:\s*(.+)$", result.stdout, re.MULTILINE | re.IGNORECASE)
        sender = sender_match.group(1).lower() if sender_match else ""
        if not any(keyword.lower() in sender for keyword in sender_keywords):
            logger.info("Spark thread %s rejected: sender did not match provider", email_id)
            return None

        return extract_otp_code(result.stdout, code_length)


def extract_otp_code(text: str, code_length: int = 6) -> str | None:
    """
    Extract an OTP code from email text.

    Looks for a standalone N-digit number that appears to be a verification code.
    Uses contextual clues (keywords near the code) to disambiguate.
    """
    # Spark includes six-digit thread IDs in its metadata. Search only the
    # message body so an ``ID: 271062`` line can never become an OTP.
    flags_header = re.search(r"^\s*Flags:.*$", text, re.MULTILINE | re.IGNORECASE)
    if flags_header:
        text = text[flags_header.end() :]
    else:
        body_marker = re.search(r"^Body:\s*$", text, re.MULTILINE | re.IGNORECASE)
        if body_marker:
            text = text[body_marker.end() :]

    # Look for code near OTP-related keywords
    otp_keywords = [
        r"code",
        r"vérification",
        r"verification",
        r"sécurité",
        r"security",
        r"confirmer",
        r"confirm",
        r"one.time",
        r"otp",
        r"authentification",
        r"valider",
    ]
    keyword_pattern = "|".join(otp_keywords)

    # Strategy 1: code appears on its own line or clearly isolated
    standalone_pattern = rf"(?:^|\s)(\d{{{code_length}}})(?:\s|$|\.)"
    standalone_matches = re.findall(standalone_pattern, text, re.MULTILINE)

    # Strategy 2: code near a keyword (within ~100 chars)
    for match in re.finditer(keyword_pattern, text, re.IGNORECASE):
        context_start = max(0, match.start() - 50)
        context_end = min(len(text), match.end() + 100)
        context = text[context_start:context_end]

        code_match = re.search(rf"\b(\d{{{code_length}}})\b", context)
        if code_match:
            return code_match.group(1)

    # Fallback: if we only found one standalone match, use it
    if len(standalone_matches) == 1:
        return standalone_matches[0]

    return None


def _parse_spark_line_datetime(line: str) -> datetime | None:
    """Best-effort parse of a timestamp from a Spark email list row."""
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?))?\b", line)
    if not match:
        return None

    date_part, time_part = match.groups()
    if not time_part:
        return None

    try:
        parsed_date = datetime.fromisoformat(date_part).date()
        parsed_time = datetime_time.fromisoformat(time_part)
    except ValueError:
        return None
    local_tz = datetime.now().astimezone().tzinfo
    return datetime.combine(parsed_date, parsed_time, tzinfo=local_tz)


def read_free_mobile_otp(
    timeout: int = 180,
    started_at: datetime | None = None,
    *,
    include_read: bool = False,
    excluded_message_ids: set[str] | None = None,
) -> str:
    """Read OTP code from Free Mobile verification email."""
    reader = OtpMailReader(timeout=timeout, initial_delay=0 if include_read else 3)
    return reader.wait_for_otp(
        sender_keywords=FREE_MOBILE_OTP_SENDERS,
        subject_keywords=["code", "vérification", "verification", "connexion"],
        started_at=started_at,
        include_read=include_read,
        excluded_message_ids=excluded_message_ids,
    )


def read_engie_otp(
    timeout: int = 180,
    started_at: datetime | None = None,
    *,
    include_read: bool = False,
    excluded_message_ids: set[str] | None = None,
) -> str:
    """Read OTP code from Engie/Okta verification email."""
    reader = OtpMailReader(timeout=timeout, initial_delay=0 if include_read else 3)
    return reader.wait_for_otp(
        sender_keywords=ENGIE_OTP_SENDERS,
        subject_keywords=["code", "vérification", "verification", "sécurité"],
        started_at=started_at,
        include_read=include_read,
        excluded_message_ids=excluded_message_ids,
    )
