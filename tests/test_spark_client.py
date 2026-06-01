from compta_auto.spark_client import parse_thread_output


def test_parse_thread_output_accepts_markdown_headers() -> None:
    output = """
### Message 12345
**From:** Billing <billing@openai.com>
**To:** Accounting <accounting@ACCOUNTING_DOMAIN_PLACEHOLDER>, Me <me@example.com>
**Subject:** Your invoice
**Date:** 2026-05-29

Body:
Download your invoice.

Attachments:
- invoice_2026-05-29.pdf downloaded to /tmp/invoice_2026-05-29.pdf
"""

    messages = parse_thread_output(output)

    assert len(messages) == 1
    assert messages[0].sender == "billing@openai.com"
    assert messages[0].recipients == ["accounting@ACCOUNTING_DOMAIN_PLACEHOLDER", "me@example.com"]
    assert messages[0].subject == "Your invoice"
    assert messages[0].attachments[0].filename == "invoice_2026-05-29.pdf"


def test_parse_thread_output_accepts_spark_attachment_path_with_spaces() -> None:
    output = """
Thread: Personnel et confidentiel

  ID: 265572
  Subject: Personnel et confidentiel
  From: Jane Doe <jane.doe@example-law.fr>
  To: John Smith <john@example.fr>
  Date: 2026-04-29 18:03
  Flags: attachment

  Attachments:
    - Facture Monsieur John Smith - 04260000031.pdf (Size: 224 KB, Type: file)
      Path: /Users/testuser/Library/Caches/Spark Mail/messagesData/5/265572/Facture Monsieur John Smith - 04260000031.pdf
"""

    messages = parse_thread_output(output)

    assert len(messages) == 1
    assert messages[0].sender == "jane.doe@example-law.fr"
    assert messages[0].recipients == ["john@example.fr"]
    assert messages[0].attachments[0].filename == "Facture Monsieur John Smith - 04260000031.pdf"
    assert "Spark Mail/messagesData" in str(messages[0].attachments[0].path)
