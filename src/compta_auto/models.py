from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


ACCOUNTING_TERMS = (
    "facture",
    "invoice",
    "receipt",
    "recu",
    "reçu",
    "billing",
    "payment",
    "paiement",
    "abonnement",
    "subscription",
)

# Strong signals: terms that almost always indicate an invoice/receipt
INVOICE_STRONG_TERMS = (
    "facture",
    "invoice",
    "receipt",
    "reçu",
    "recu",
    "votre facture",
    "your invoice",
    "your receipt",
    "confirmation de paiement",
    "payment confirmation",
    "payment received",
    "paiement reçu",
    "relevé de compte",
    "account statement",
    "nota fiscal",
)

# Moderate signals: terms that suggest billing context
INVOICE_MODERATE_TERMS = (
    "billing",
    "subscription",
    "abonnement",
    "payment",
    "paiement",
    "montant",
    "amount due",
    "total",
    "échéance",
    "due date",
    "prélèvement",
    "direct debit",
    "charge",
    "renewal",
    "renouvellement",
)

# Sender patterns that typically send invoices (noreply billing addresses)
INVOICE_SENDER_PATTERNS = (
    "billing",
    "invoice",
    "facture",
    "receipt",
    "noreply",
    "no-reply",
    "payment",
    "comptabilite",
    "accounting",
    "finance",
)

DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Attachment:
    filename: str
    path: Path | None = None
    content: bytes | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class MailMessage:
    spark_message_id: str
    sender: str
    recipients: list[str]
    subject: str
    sent_at: str | None
    body: str = ""
    attachments: list[Attachment] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractedMetadata:
    vendor: str | None
    date: str | None
    confidence: float
    method: str

