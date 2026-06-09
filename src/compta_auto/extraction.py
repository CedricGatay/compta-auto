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

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# "May 29, 2026" or "29 May 2026" or "29 mai 2026"
_MONTH_NAME_RE = re.compile(
    r"(?:(\d{1,2})\s+)?("
    + "|".join(sorted(MONTH_NAMES.keys(), key=len, reverse=True))
    + r")\.?\s+(\d{1,2})?,?\s*(20\d{2})",
    re.IGNORECASE,
)

OPENAI_EXTRACTION_PROMPT = """\
You are an invoice metadata extractor. Analyze the provided document and extract:
- vendor: If VENDOR_NAME is provided, you MUST use it exactly as the vendor value. Do not use any other name from the document.
- date: the invoice date in YYYY-MM-DD format
- confidence: your confidence from 0.0 to 1.0

Respond ONLY with valid JSON: {"vendor": "...", "date": "YYYY-MM-DD", "confidence": 0.XX}
If you cannot determine a field, set it to null but still provide your confidence estimate.
"""

OPENAI_DATE_EXTRACTION_PROMPT = """\
You are an invoice date extractor. Find the invoice date from the document text.
Look specifically for patterns like:
- "votre facture du", "facture du", "date de facture", "date de la facture"
- "invoice date", "date of invoice", "billed on", "billing date"
- Any date clearly associated with when the invoice was issued

Do NOT use: due dates, payment deadlines, billing period start/end dates, next invoice dates.
The invoice date is when the document was issued.

Respond ONLY with valid JSON: {"date": "YYYY-MM-DD"}
If you cannot determine the date, respond: {"date": null}
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

    def extract_date_only(self, path: Path) -> str | None:
        """Extract only the invoice date using LLM, with targeted prompt."""
        text = self._read_text(path)
        if not text.strip():
            return None
        if self.openai_api_key:
            return self._openai_extract_date(text)
        if self._apple_available:
            return self._apple_extract_date(path, text)
        return None

    def _openai_extract_date(self, text: str) -> str | None:
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client = OpenAI(api_key=self.openai_api_key)
        messages: list[dict] = [
            {"role": "system", "content": OPENAI_DATE_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Document text:\n{text[:4000]}"},
        ]
        try:
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                temperature=0.0,
                max_tokens=50,
            )
            raw = response.choices[0].message.content or ""
            json_match = re.search(r"\{[^}]+\}", raw)
            if not json_match:
                return None
            payload = json.loads(json_match.group(0))
            return payload.get("date")
        except Exception:
            return None

    def _apple_extract_date(self, path: Path, text: str) -> str | None:
        """Use Apple FoundationModels for date-only extraction."""
        args = [str(APPLE_EXTRACTOR_PATH), str(path), f"EXTRACT_DATE_ONLY: {OPENAI_DATE_EXTRACTION_PROMPT}"]
        try:
            result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)
            payload = json.loads(result.stdout)
            return payload.get("date")
        except Exception:
            return None

    def _read_text(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            try:
                import logging

                import pdfplumber

                logging.getLogger("pdfminer").setLevel(logging.ERROR)
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
        messages = self._build_openai_messages(path, text, mail_subject, sender)

        try:
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
            return self._parse_openai_response(response.choices[0].message.content or "")
        except Exception:
            return None

    async def async_extract(self, path: Path, mail_subject: str = "", sender: str = "") -> ExtractedMetadata:
        """Async version of extract() — uses AsyncOpenAI for LLM calls."""
        text = self._read_text(path)
        if self.has_llm:
            try:
                llm = await self._async_llm_extract(path, text, mail_subject, sender)
                if llm and llm.vendor:
                    return llm
            except Exception:
                pass
        return heuristic_extract(path, text, mail_subject, sender)

    async def async_extract_date_only(self, path: Path) -> str | None:
        """Async version of extract_date_only()."""
        text = self._read_text(path)
        if not text.strip():
            return None
        if self.openai_api_key:
            return await self._async_openai_extract_date(text)
        if self._apple_available:
            return await self._async_apple_extract_date(path, text)
        return None

    async def _async_llm_extract(
        self, path: Path, text: str, mail_subject: str, sender: str
    ) -> ExtractedMetadata | None:
        if self.openai_api_key:
            return await self._async_openai_extract(path, text, mail_subject, sender)
        if self._apple_available:
            return await self._async_apple_extract(path, text, mail_subject, sender)
        if self.llm_command:
            return await self._async_command_extract(path)
        return None

    async def _async_openai_extract(
        self, path: Path, text: str, mail_subject: str, sender: str
    ) -> ExtractedMetadata | None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return None

        client = AsyncOpenAI(api_key=self.openai_api_key)
        messages = self._build_openai_messages(path, text, mail_subject, sender)

        try:
            response = await client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
            return self._parse_openai_response(response.choices[0].message.content or "")
        except Exception:
            return None

    async def _async_openai_extract_date(self, text: str) -> str | None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return None
        client = AsyncOpenAI(api_key=self.openai_api_key)
        messages: list[dict] = [
            {"role": "system", "content": OPENAI_DATE_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Document text:\n{text[:4000]}"},
        ]
        try:
            response = await client.chat.completions.create(
                model=self.openai_model,
                messages=messages,
                temperature=0.0,
                max_tokens=50,
            )
            raw = response.choices[0].message.content or ""
            json_match = re.search(r"\{[^}]+\}", raw)
            if not json_match:
                return None
            payload = json.loads(json_match.group(0))
            return payload.get("date")
        except Exception:
            return None

    async def _async_apple_extract(
        self, path: Path, text: str, mail_subject: str, sender: str
    ) -> ExtractedMetadata | None:
        """Async version of _apple_extract using asyncio subprocess."""
        import asyncio

        vendor_hint = ""
        if sender and "@" in sender:
            domain = sender.split("@")[-1].strip(">").lower()
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
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return None
            payload = json.loads(stdout.decode())
        except Exception:
            return None

        vendor = payload.get("vendor")
        date_val = payload.get("date")
        confidence = float(payload.get("confidence", 0))
        if not vendor and not date_val:
            return None
        if vendor and date_val:
            confidence = max(confidence, 0.9)
        elif vendor:
            confidence = max(confidence, 0.5)
        return ExtractedMetadata(
            vendor=vendor, date=date_val, confidence=confidence, method="apple_llm",
        )

    async def _async_apple_extract_date(self, path: Path, text: str) -> str | None:
        """Async version of _apple_extract_date."""
        import asyncio

        args = [str(APPLE_EXTRACTOR_PATH), str(path), f"EXTRACT_DATE_ONLY: {OPENAI_DATE_EXTRACTION_PROMPT}"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return None
            payload = json.loads(stdout.decode())
            return payload.get("date")
        except Exception:
            return None

    async def _async_command_extract(self, path: Path) -> ExtractedMetadata | None:
        """Async version of _command_extract."""
        import asyncio

        if not self.llm_command:
            return None
        cmd = [*self.llm_command.split(), str(path)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                return None
            payload = json.loads(stdout.decode())
        except Exception:
            return None
        return ExtractedMetadata(
            vendor=payload.get("vendor"),
            date=payload.get("date"),
            confidence=float(payload.get("confidence", 0)),
            method="llm",
        )

    def _build_openai_messages(
        self, path: Path, text: str, mail_subject: str, sender: str
    ) -> list[dict]:
        """Build the OpenAI messages list (shared between sync and async)."""
        messages: list[dict] = [{"role": "system", "content": OPENAI_EXTRACTION_PROMPT}]

        context_parts = []
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

        return messages

    def _parse_openai_response(self, raw: str) -> ExtractedMetadata | None:
        """Parse OpenAI response JSON (shared between sync and async)."""
        json_match = re.search(r"\{[^}]+\}", raw)
        if not json_match:
            return None
        try:
            payload = json.loads(json_match.group(0))
        except (json.JSONDecodeError, ValueError):
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
    # Try month name patterns ("May 29, 2026" or "29 May 2026")
    for m in _MONTH_NAME_RE.finditer(value):
        day_before, month_name, day_after, year_str = m.groups()
        month_num = MONTH_NAMES.get(month_name.lower())
        if not month_num:
            continue
        day_str = day_before or day_after
        day_num = int(day_str) if day_str else 1
        try:
            return date(int(year_str), month_num, day_num).isoformat()
        except ValueError:
            continue
    # Fallback: YYYY-MM without day (use 1st of month)
    ym_match = re.search(r"(?<!\d)(20\d{2})[-_/\.](1[0-2]|0?[1-9])(?=[-_/\.\s]|$)", value)
    if ym_match:
        year, month = int(ym_match.group(1)), int(ym_match.group(2))
        try:
            return date(year, month, 1).isoformat()
        except ValueError:
            pass
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
    # Also strip YYYY_MM patterns (no day)
    stem = re.sub(r"20\d{2}[-_.](1[0-2]|0?[1-9])(?=[-_.\s]|$)", "", stem)
    stem = re.sub(r"(?:^|[-_.\s])(invoice|facture|receipt|recu|reçu)(?=[-_.\s]|$)", "", stem, flags=re.IGNORECASE)
    # Strip French/English month names
    months = r"(?:^|[-_.\s])(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre|january|february|march|april|may|june|july|august|september|october|november|december)(?=[-_.\s]|$)"
    stem = re.sub(months, "", stem, flags=re.IGNORECASE)
    # Strip standalone year (e.g. trailing _2026)
    stem = re.sub(r"[-_.]20\d{2}(?=[-_.\s]|$)", "", stem)
    # Strip alphanumeric reference codes (e.g. FR72332983)
    stem = re.sub(r"[A-Z]{1,3}\d{6,}", "", stem)
    # Strip long standalone numbers (10+ digits, likely IDs not vendor names)
    stem = re.sub(r"\d{10,}", "", stem)
    return normalize_vendor(stem)


# Known vendor prefixes from fetchers — shared between pipeline and re-rename
FETCHER_PREFIXES: dict[str, str] = {
    "spotify": "spotify",
    "openai": "openai",
    "free_mobile": "free_mobile",
    "orange": "orange",
    "sosh": "sosh",
    "freebox": "freebox",
    "ovh": "ovh",
    "engie_pro": "engie",
    "engie": "engie",
}


def detect_fetcher_vendor(filename: str) -> str | None:
    """If the filename matches a known fetcher prefix, return the vendor."""
    lower = filename.lower()
    for prefix, vendor in sorted(FETCHER_PREFIXES.items(), key=lambda x: -len(x[0])):
        if lower.startswith(prefix + "_") or lower.startswith(prefix + "."):
            return vendor
    return None


def extract_fetcher_metadata(
    file_path: Path,
    known_vendor: str,
    extractor: "MetadataExtractor",
) -> ExtractedMetadata:
    """Extract metadata for a file with a known vendor (from fetcher).

    Uses filename-first date extraction, then LLM, then text scan.
    """
    detected_date = find_date(file_path.name)
    if not detected_date:
        detected_date = extractor.extract_date_only(file_path)
    if not detected_date:
        text = extractor._read_text(file_path)
        detected_date = find_date(text[:5000])
    return ExtractedMetadata(
        vendor=known_vendor,
        date=detected_date,
        confidence=1.0 if detected_date else 0.9,
        method="fetcher",
    )


async def async_extract_fetcher_metadata(
    file_path: Path,
    known_vendor: str,
    extractor: "MetadataExtractor",
) -> ExtractedMetadata:
    """Async version of extract_fetcher_metadata."""
    detected_date = find_date(file_path.name)
    if not detected_date:
        detected_date = await extractor.async_extract_date_only(file_path)
    if not detected_date:
        text = extractor._read_text(file_path)
        detected_date = find_date(text[:5000])
    return ExtractedMetadata(
        vendor=known_vendor,
        date=detected_date,
        confidence=1.0 if detected_date else 0.9,
        method="fetcher",
    )
