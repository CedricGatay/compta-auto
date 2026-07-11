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

        deadline = time.time() + self.timeout
        attempt = 0
        if self.initial_delay > 0:
            time.sleep(min(self.initial_delay, self.timeout))

        while time.time() < deadline:
            attempt += 1
            logger.debug(f"OTP poll attempt {attempt}...")

            try:
                code = self._try_find_otp(
                    sender_keywords, subject_keywords, started_at, code_length
                )
                if code:
                    logger.info(f"OTP code found on attempt {attempt}")
                    return code
            except Exception as e:
                logger.warning(f"OTP poll error: {e}")

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
    ) -> str | None:
        """Single attempt to find an OTP code in recent emails."""
        # Search for recent unread emails
        filter_parts = ["is:unread", "newer_than:1d"]
        filter_str = " ".join(filter_parts)

        result = subprocess.run(
            ["spark", "emails", "--filter", filter_str, "--page-size", "20"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"spark emails failed: {result.stderr}")
            return None

        # Parse email IDs and find candidates
        candidate_ids = self._filter_candidates(
            result.stdout, sender_keywords, subject_keywords, started_at
        )

        if not candidate_ids:
            return None

        # Read each candidate thread and extract OTP
        for email_id in candidate_ids:
            code = self._extract_otp_from_thread(email_id, code_length)
            if code:
                return code

        return None

    def _filter_candidates(
        self,
        emails_output: str,
        sender_keywords: list[str],
        subject_keywords: list[str],
        started_at: datetime,
    ) -> list[str]:
        """Filter email list output to find OTP email candidates."""
        fresh_candidates = []
        unknown_time_candidates = []
        lines = emails_output.strip().splitlines()

        for line in lines:
            # spark emails output format: "  ID  From  Subject  Date"
            line_lower = line.lower()

            # Check if any sender keyword matches
            sender_match = any(kw.lower() in line_lower for kw in sender_keywords)
            if not sender_match:
                continue

            # Check if any subject keyword matches (optional - OTP emails
            # might not always have obvious subject keywords)
            subject_match = (
                not subject_keywords
                or any(kw.lower() in line_lower for kw in subject_keywords)
            )
            if not subject_match:
                continue

            # Extract the ID from the line
            id_match = re.match(r"\s*(\d+)\s+", line)
            if id_match:
                email_id = id_match.group(1)
                received_at = _parse_spark_line_datetime(line)
                if received_at is None:
                    unknown_time_candidates.append(email_id)
                elif received_at >= started_at:
                    fresh_candidates.append(email_id)

        if fresh_candidates:
            return fresh_candidates

        return unknown_time_candidates

    def _extract_otp_from_thread(self, email_id: str, code_length: int) -> str | None:
        """Read an email thread and extract OTP code from the body."""
        result = subprocess.run(
            ["spark", "thread", email_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None

        return extract_otp_code(result.stdout, code_length)


def extract_otp_code(text: str, code_length: int = 6) -> str | None:
    """
    Extract an OTP code from email text.

    Looks for a standalone N-digit number that appears to be a verification code.
    Uses contextual clues (keywords near the code) to disambiguate.
    """
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


def read_free_mobile_otp(timeout: int = 180, started_at: datetime | None = None) -> str:
    """Read OTP code from Free Mobile verification email."""
    reader = OtpMailReader(timeout=timeout, initial_delay=3)
    return reader.wait_for_otp(
        sender_keywords=FREE_MOBILE_OTP_SENDERS,
        subject_keywords=["code", "vérification", "verification", "connexion"],
        started_at=started_at,
    )


def read_engie_otp(timeout: int = 180, started_at: datetime | None = None) -> str:
    """Read OTP code from Engie/Okta verification email."""
    reader = OtpMailReader(timeout=timeout, initial_delay=3)
    return reader.wait_for_otp(
        sender_keywords=ENGIE_OTP_SENDERS,
        subject_keywords=["code", "vérification", "verification", "sécurité"],
        started_at=started_at,
    )
