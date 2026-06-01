from __future__ import annotations

import base64
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from .models import ExtractedMetadata
from .normalize import normalize_vendor


DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-_/\.](0?[1-9]|1[0-2])[-_/\.](0?[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])[-_/\.](0?[1-9]|1[0-2])[-_/\.](20\d{2})(?!\d)"),
)

OPENAI_EXTRACTION_PROMPT = """\
You are an invoice metadata extractor. Analyze the provided document and extract:
- vendor: If VENDOR_NAME is provided, you MUST use it exactly as the vendor value. Do not use any other name from the document.
- date: the invoice date in YYYY-MM-DD format
- confidence: your confidence from 0.0 to 1.0

Respond ONLY with valid JSON: {"vendor": "...", "date": "YYYY-MM-DD", "confidence": 0.XX}
If you cannot determine a field, set it to null but still provide your confidence estimate.
"""


APPLE_EXTRACTOR_PATH = Path(__file__).parent.parent.parent / "tools" / "apple-extractor" / ".build" / "release" / "apple-extractor"


class MetadataExtractor:
    def __init__(
        self,
        llm_command: str | None = None,
        openai_api_key: str | None = None,
        openai_model: str = "gpt-4o-mini",
        use_apple_llm: bool = False,
    ):
        self.llm_command = llm_command
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.use_apple_llm = use_apple_llm

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_command or self.openai_api_key or self._apple_available)

    @property
    def _apple_available(self) -> bool:
        return self.use_apple_llm and APPLE_EXTRACTOR_PATH.exists()

    def extract(self, path: Path, mail_subject: str = "", sender: str = "") -> ExtractedMetadata:
        text = self._read_text(path)
        if self.has_llm:
            try:
                llm = self._llm_extract(path, text, mail_subject, sender)
                if llm and llm.vendor:
                    return llm
            except Exception:
                pass
        # Fallback to heuristic only if no LLM available or LLM failed
        return heuristic_extract(path, text, mail_subject, sender)

    def _read_text(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            try:
                import pdfplumber

                with pdfplumber.open(path) as pdf:
                    return "\n".join(page.extract_text() or "" for page in pdf.pages)
            except Exception:
                return ""
        if path.suffix.lower() in {".txt", ".md"}:
            return path.read_text(errors="ignore")
        try:
            import pytesseract
            from PIL import Image

            return pytesseract.image_to_string(Image.open(path))
        except Exception:
            return ""

    def _llm_extract(
        self, path: Path, text: str, mail_subject: str, sender: str
    ) -> ExtractedMetadata | None:
        if self.openai_api_key:
            return self._openai_extract(path, text, mail_subject, sender)
        if self._apple_available:
            return self._apple_extract(path, text, mail_subject, sender)
        if self.llm_command:
            return self._command_extract(path)
        return None

    def _apple_extract(
        self, path: Path, text: str, mail_subject: str, sender: str
    ) -> ExtractedMetadata | None:
        """Use Apple FoundationModels via the bundled Swift tool."""
        # Derive vendor hint from sender domain (e.g. "noreply@ovh.com" -> "OVH")
        vendor_hint = ""
        if sender and "@" in sender:
            domain = sender.split("@")[-1].strip(">").lower()
            # Use the second-level domain as vendor hint (e.g. ovh.com -> OVH)
            parts = domain.split(".")
            if len(parts) >= 2:
                vendor_hint = parts[-2].upper()

        context_parts: list[str] = []
        if vendor_hint:
            context_parts.append(f"VENDOR_NAME: {vendor_hint}")
        if sender:
            context_parts.append(f"Sender email: {sender}")
        if mail_subject:
            context_parts.append(f"Mail subject: {mail_subject}")
        context = "\n".join(context_parts) if context_parts else ""

        args = [str(APPLE_EXTRACTOR_PATH), str(path)]
        if context:
            args.append(context)

        try:
            result = subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(result.stdout)
        except Exception:
            return None

        vendor = payload.get("vendor")
        date_val = payload.get("date")
        confidence = float(payload.get("confidence", 0))
        if not vendor and not date_val:
            return None
        # If we provided the vendor hint and it was used, boost confidence
        if vendor and date_val:
            confidence = max(confidence, 0.9)
        elif vendor:
            confidence = max(confidence, 0.5)
        return ExtractedMetadata(
            vendor=vendor,
            date=date_val,
            confidence=confidence,
            method="apple_llm",
        )

    def _command_extract(self, path: Path) -> ExtractedMetadata | None:
        if not self.llm_command:
            return None
        cmd = [*self.llm_command.split(), str(path)]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            payload = json.loads(result.stdout)
        except Exception:
            return None
        return ExtractedMetadata(
            vendor=payload.get("vendor"),
            date=payload.get("date"),
            confidence=float(payload.get("confidence", 0)),
            method="llm",
        )

    def _openai_extract(
        self, path: Path, text: str, mail_subject: str, sender: str
    ) -> ExtractedMetadata | None:
        try:
            from openai import OpenAI
        except ImportError:
            return None

        client = OpenAI(api_key=self.openai_api_key)
        messages: list[dict] = [{"role": "system", "content": OPENAI_EXTRACTION_PROMPT}]

        # Build context from available text
        context_parts = []
        # Derive vendor hint from sender domain
        if sender and "@" in sender:
            domain = sender.split("@")[-1].strip(">").lower()
            domain_parts = domain.split(".")
            if len(domain_parts) >= 2:
                context_parts.append(f"VENDOR_NAME: {domain_parts[-2].upper()}")
        if sender:
            context_parts.append(f"Sender: {sender}")
        if mail_subject:
            context_parts.append(f"Mail subject: {mail_subject}")
        if text.strip():
            context_parts.append(f"Document text:\n{text[:4000]}")

        # For images, include the image directly via vision
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
            content: list[dict] = []
            if context_parts:
                content.append({"type": "text", "text": "\n".join(context_parts)})
            image_data = base64.b64encode(path.read_bytes()).decode()
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "webp": "image/webp", "tif": "image/tiff", "tiff": "image/tiff"}
            media_type = mime.get(suffix.lstrip("."), "image/png")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{image_data}"},
            })
            messages.append({"role": "user", "content": content})
        else:
            user_text = "\n".join(context_parts) if context_parts else f"Filename: {path.name}"
            messages.append({"role": "user", "content": user_text})

        try:
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
            raw = response.choices[0].message.content or ""
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"\{[^}]+\}", raw)
            if not json_match:
                return None
            payload = json.loads(json_match.group(0))
        except Exception:
            return None

        return ExtractedMetadata(
            vendor=payload.get("vendor"),
            date=payload.get("date"),
            confidence=float(payload.get("confidence", 0)),
            method="openai",
        )


def heuristic_extract(path: Path, text: str, mail_subject: str, sender: str) -> ExtractedMetadata:
    haystack = "\n".join([path.name, mail_subject, text[:5000]])
    detected_date = find_date(haystack)
    vendor = vendor_from_sender(sender) or find_vendor(text) or vendor_from_filename(path)
    confidence = 0.0
    if detected_date:
        confidence += 0.45
    if vendor:
        confidence += 0.35
    if text.strip():
        confidence += 0.15
    if path.suffix.lower() == ".pdf":
        confidence += 0.05
    return ExtractedMetadata(vendor=vendor, date=detected_date, confidence=min(confidence, 1), method="heuristic")


def find_date(value: str) -> str | None:
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(value):
            groups = match.groups()
            if len(groups[0]) == 4:
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                continue
    return None


def find_vendor(text: str) -> str | None:
    patterns = (
        r"(?:vendor|supplier|fournisseur|marchand)\s*[:\-]\s*([A-Za-z0-9 &'.-]{2,80})",
        r"(?:invoice from|facture de)\s+([A-Za-z0-9 &'.-]{2,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_vendor(match.group(1))
    return None


def vendor_from_sender(sender: str) -> str | None:
    if "@" not in sender:
        return normalize_vendor(sender)
    domain = sender.rsplit("@", 1)[1]
    parts = domain.split(".")
    if parts:
        return normalize_vendor(parts[0])
    return None


def vendor_from_filename(path: Path) -> str | None:
    stem = re.sub(r"20\d{2}[-_.]\d{1,2}[-_.]\d{1,2}", "", path.stem)
    stem = re.sub(r"\b(invoice|facture|receipt|recu|reçu)\b", "", stem, flags=re.IGNORECASE)
    return normalize_vendor(stem)
