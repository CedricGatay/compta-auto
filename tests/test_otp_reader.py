"""Tests for the OTP mail reader module."""

from unittest.mock import patch, MagicMock
import subprocess

import pytest

from compta_auto.otp_reader import (
    extract_otp_code,
    OtpMailReader,
    OtpReadError,
    read_free_mobile_otp,
    read_engie_otp,
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


class TestOtpMailReader:
    """Tests for OtpMailReader with mocked spark CLI."""

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_finds_otp_on_first_poll(self, mock_run):
        # Mock spark emails output
        emails_output = "  42001  noreply@free.fr  Code de vérification  2026-06-08"
        # Mock spark thread output
        thread_output = "Message 42001\nFrom: noreply@free.fr\nSubject: Code de vérification\n\nBody:\nVotre code est 839201."

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=emails_output, stderr=""),
            MagicMock(returncode=0, stdout=thread_output, stderr=""),
        ]

        reader = OtpMailReader(timeout=10, poll_interval=1)
        code = reader.wait_for_otp(
            sender_keywords=["free.fr"],
            subject_keywords=["code", "vérification"],
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
        emails_output = "  100  noreply@okta.com  Votre code de sécurité  2026-06-08"
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
        )
        assert code == "192837"

    @patch("compta_auto.otp_reader.subprocess.run")
    def test_filter_by_sender(self, mock_run):
        # Email from wrong sender should be filtered out
        emails_output = "  200  amazon@notifications.com  Your order  2026-06-08\n  201  noreply@free.fr  Code connexion  2026-06-08"
        thread_output = "Message 201\nFrom: noreply@free.fr\n\nBody:\nVotre code de confirmation: 456789"

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=emails_output, stderr=""),
            MagicMock(returncode=0, stdout=thread_output, stderr=""),
        ]

        reader = OtpMailReader(timeout=10, poll_interval=1)
        code = reader.wait_for_otp(
            sender_keywords=["free.fr"],
            subject_keywords=["code", "connexion"],
        )
        assert code == "456789"
        # Should only have called thread for ID 201, not 200
        assert mock_run.call_count == 2
