"""Tests for the OTP mail reader module."""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from compta_auto.otp_reader import (
    extract_otp_code,
    OtpMailReader,
    OtpReadError,
    read_free_mobile_otp,
    read_engie_otp,
    latest_mail_summary,
    recent_mail_ids,
)


class TestExtractOtpCode:
    """Tests for OTP code extraction from email text."""

    def test_code_near_keyword(self):
        text = "Votre code de vérification est : 847291"
        assert extract_otp_code(text) == "847291"

    def test_code_on_own_line(self):
        text = "Bonjour,\n\nVoici votre code :\n\n123456\n\nCordialement"
        assert extract_otp_code(text) == "123456"

    def test_code_after_security_keyword(self):
        text = "Your security code is 982143. It expires in 10 minutes."
        assert extract_otp_code(text) == "982143"

    def test_code_with_otp_keyword(self):
        text = "OTP: 554433"
        assert extract_otp_code(text) == "554433"

    def test_no_code_returns_none(self):
        text = "Hello, this is a regular email with no codes."
        assert extract_otp_code(text) is None

    def test_ignores_non_6_digit_numbers_by_default(self):
        text = "Your order #12345 has been shipped. Track at 9876543210."
        assert extract_otp_code(text) is None

    def test_custom_code_length(self):
        text = "Your verification code: 1234"
        assert extract_otp_code(text, code_length=4) == "1234"

    def test_french_verification_email(self):
        text = """
        Bonjour,

        Pour confirmer votre connexion, veuillez saisir le code de vérification suivant :

        Code : 749312

        Ce code est valable pendant 10 minutes.
        """
        assert extract_otp_code(text) == "749312"

    def test_engie_style_email(self):
        text = """
        Votre code de sécurité Engie Pro

        Pour valider votre authentification, veuillez entrer le code suivant :
        583920

        Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.
        """
        assert extract_otp_code(text) == "583920"

    def test_standalone_code_only_one_match(self):
        text = "Your account number is not relevant.\n\n\n654321\n\n"
        # Only one 6-digit standalone number, should match
        assert extract_otp_code(text) == "654321"

    def test_multiple_standalone_codes_returns_none(self):
        # Ambiguous: multiple 6-digit numbers without keyword context
        text = "Numbers: 123456 and 654321 are listed."
        assert extract_otp_code(text) is None

    def test_ignores_six_digit_spark_thread_id_in_metadata(self):
        text = """Thread: Votre code de sécurité

  ID: 271062
  Subject: Votre code de sécurité
  Flags: unread

  Voici le code de sécurité :
  494414
"""

        assert extract_otp_code(text) == "494414"


class TestOtpMailReader:
    """Tests for OtpMailReader with mocked spark CLI."""

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_finds_otp_on_first_poll(self, mock_run):
        # Mock spark emails output
        emails_output = "  42001  noreply@free.fr  Code de vérification  2026-06-08 12:05"
        # Mock spark thread output
        thread_output = (
            "Message 42001\nFrom: noreply@free.fr\nSubject: Code de vérification\n\n"
            "Body:\nVotre code est 839201."
        )

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=emails_output, stderr=""),
            MagicMock(returncode=0, stdout=thread_output, stderr=""),
        ]

        reader = OtpMailReader(timeout=10, poll_interval=1)
        code = reader.wait_for_otp(
            sender_keywords=["free.fr"],
            subject_keywords=["code", "vérification"],
            started_at=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc),
        )
        assert code == "839201"

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_timeout_raises_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        reader = OtpMailReader(timeout=2, poll_interval=1)
        with pytest.raises(OtpReadError, match="No OTP email found"):
            reader.wait_for_otp(
                sender_keywords=["free.fr"],
                subject_keywords=["code"],
            )

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_spark_failure_retries(self, mock_run):
        # First call fails, second succeeds
        emails_output = "  100  noreply@okta.com  Votre code de sécurité  2026-06-08 12:05"
        thread_output = "Message 100\nFrom: noreply@okta.com\n\nBody:\nCode de sécurité: 192837"

        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="error"),
            MagicMock(returncode=0, stdout=emails_output, stderr=""),
            MagicMock(returncode=0, stdout=thread_output, stderr=""),
        ]

        reader = OtpMailReader(timeout=10, poll_interval=1)
        code = reader.wait_for_otp(
            sender_keywords=["okta.com"],
            subject_keywords=["code", "sécurité"],
            started_at=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc),
        )
        assert code == "192837"

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_filter_by_sender(self, mock_run):
        # Email from wrong sender should be filtered out
        emails_output = (
            "  200  amazon@notifications.com  Your order  2026-06-08 12:05\n"
            "  201  noreply@free.fr  Code connexion  2026-06-08 12:05"
        )
        thread_output = (
            "Message 201\nFrom: noreply@free.fr\n\nBody:\n"
            "Votre code de confirmation: 456789"
        )

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=emails_output, stderr=""),
            MagicMock(returncode=0, stdout=thread_output, stderr=""),
        ]

        reader = OtpMailReader(timeout=10, poll_interval=1)
        code = reader.wait_for_otp(
            sender_keywords=["free.fr"],
            subject_keywords=["code", "connexion"],
            started_at=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc),
        )
        assert code == "456789"
        # Should only have called thread for ID 201, not 200
        assert mock_run.call_count == 2

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_accepts_otp_subject_when_spark_truncates_sender(self, mock_run):
        emails_output = "  201  noreply@authentifi…  Votre code de sécurité  2026-08-05 14:12"
        thread_output = (
            "Message 201\n  From: noreply@authentification.engie.fr\n\n"
            "Body:\nVotre code de sécurité: 192837"
        )
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=emails_output, stderr=""),
            MagicMock(returncode=0, stdout=thread_output, stderr=""),
        ]

        reader = OtpMailReader(timeout=1)
        code = reader._try_find_otp(
            sender_keywords=["engie.fr"],
            subject_keywords=["code", "sécurité"],
            started_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
            code_length=6,
            include_read=True,
        )

        assert code == "192837"

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_force_refresh_includes_already_read_otp_mail(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        reader = OtpMailReader(timeout=1)

        reader._try_find_otp(
            sender_keywords=["free.fr"],
            subject_keywords=["code"],
            started_at=datetime.now(timezone.utc),
            code_length=6,
            include_read=True,
        )

        command = mock_run.call_args.args[0]
        assert "is:unread" not in command[3]
        assert "newer_than:1d" in command[3]

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_ignores_messages_present_before_the_otp_request(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="  201  noreply@free.fr  Code connexion  2026-06-08 12:05",
            stderr="",
        )
        reader = OtpMailReader(timeout=1)

        code = reader._try_find_otp(
            sender_keywords=["free.fr"],
            subject_keywords=["code"],
            started_at=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc),
            code_length=6,
            include_read=True,
            excluded_message_ids={"201"},
        )

        assert code is None
        assert mock_run.call_count == 1


@patch("compta_auto.otp_reader.subprocess.run")
def test_latest_mail_summary_returns_newest_spark_row(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="  ID  From  Subject  Date\n  42001  noreply@free.fr  Code connexion  2026-08-05",
        stderr="",
    )

    assert latest_mail_summary() == "42001 noreply@free.fr Code connexion 2026-08-05"


@patch("compta_auto.otp_reader.subprocess.run")
def test_recent_mail_ids_snapshots_spark_message_ids(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="  ID  From  Subject  Date\n  42001  noreply@free.fr  Code\n  42002  test@example.com  Hello",
        stderr="",
    )

    assert recent_mail_ids() == {"42001", "42002"}

def test_filter_prefers_candidates_after_started_at():
    emails_output = "\n".join(
        [
            "  200  noreply@free.fr  Code connexion  2026-06-08 10:00",
            "  201  noreply@free.fr  Code connexion  2026-06-08 10:05",
        ]
    )
    reader = OtpMailReader(timeout=10, poll_interval=1)

    local_tz = datetime.now().astimezone().tzinfo
    candidates = reader._filter_candidates(
        emails_output,
        sender_keywords=["free.fr"],
        subject_keywords=["code"],
        started_at=datetime(2026, 6, 8, 10, 3, tzinfo=local_tz),
    )

    assert candidates == ["201"]


def test_filter_accepts_a_code_from_the_same_request_minute():
    emails_output = "  201  noreply@free.fr  Code connexion  2026-06-08 10:03"
    reader = OtpMailReader(timeout=10, poll_interval=1)

    local_tz = datetime.now().astimezone().tzinfo
    candidates = reader._filter_candidates(
        emails_output,
        sender_keywords=["free.fr"],
        subject_keywords=["code"],
        started_at=datetime(2026, 6, 8, 10, 3, 45, tzinfo=local_tz),
    )

    assert candidates == ["201"]


def test_filter_prioritizes_the_newest_eligible_message():
    emails_output = "\n".join(
        [
            "  201  noreply@free.fr  Code connexion  2026-06-08 10:04",
            "  202  noreply@free.fr  Code connexion  2026-06-08 10:05",
            "  203  noreply@free.fr  Code connexion  2026-06-08 10:05",
        ]
    )
    reader = OtpMailReader(timeout=10, poll_interval=1)
    local_tz = datetime.now().astimezone().tzinfo

    candidates = reader._filter_candidates(
        emails_output,
        sender_keywords=["free.fr"],
        subject_keywords=["code"],
        started_at=datetime(2026, 6, 8, 10, 0, tzinfo=local_tz),
    )

    assert candidates == ["203", "202", "201"]


def test_filter_rejects_candidates_without_a_precise_timestamp():
    emails_output = "  201  noreply@free.fr  Code connexion  2026-06-08"
    reader = OtpMailReader(timeout=10, poll_interval=1)

    candidates = reader._filter_candidates(
        emails_output,
        sender_keywords=["free.fr"],
        subject_keywords=["code"],
        started_at=datetime(2026, 6, 8, 10, 3, tzinfo=timezone.utc),
    )

    assert candidates == []


def test_free_mobile_reader_wrapper_uses_longer_timeout_and_delay():
    started_at = datetime(2026, 6, 8, 10, 3, tzinfo=timezone.utc)
    with patch("compta_auto.otp_reader.OtpMailReader") as reader_cls:
        reader = reader_cls.return_value
        reader.wait_for_otp.return_value = "123456"

        assert read_free_mobile_otp(started_at=started_at) == "123456"

    reader_cls.assert_called_once_with(timeout=180, initial_delay=3)
    _, kwargs = reader.wait_for_otp.call_args
    assert kwargs["started_at"] == started_at


def test_engie_reader_wrapper_uses_longer_timeout_and_delay():
    started_at = datetime(2026, 6, 8, 10, 3, tzinfo=timezone.utc)
    with patch("compta_auto.otp_reader.OtpMailReader") as reader_cls:
        reader = reader_cls.return_value
        reader.wait_for_otp.return_value = "654321"

        assert read_engie_otp(started_at=started_at) == "654321"

    reader_cls.assert_called_once_with(timeout=180, initial_delay=3)
    _, kwargs = reader.wait_for_otp.call_args
    assert kwargs["started_at"] == started_at
