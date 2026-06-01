# Compta Auto

**Local-first accounting automation for SALE_MARKER_1rs on macOS.**

Scans email inboxes and local folders for invoices, extracts metadata via LLM, renames documents with a consistent `YYYY_MM_DD_vendor.ext` convention, and provides a web UI to triage and organize everything — all without sending data to the cloud (unless you opt into OpenAI).

---

## Features

### 📬 Email Ingestion
- Reads billing-related emails from **Spark Desktop** (macOS)
- Auto-selects mails sent to your accounting domain (e.g. `@ACCOUNTING_DOMAIN_PLACEHOLDER`)
- Downloads PDF/image attachments automatically
- Detects invoice download links and provider portal URLs
- Whitelist/blacklist senders with one click — rules persist across runs

### 📁 Local Folder Scanning
- Point to any local folder containing scanned receipts
- Native macOS folder picker (no typing paths)
- Configurable timespan (1 week → 3 months, or "since last scan")
- Original files stay untouched; renamed copies go to the output directory

### 🤖 LLM-Powered Metadata Extraction
- **OpenAI** (cloud), **Apple Intelligence** (on-device via FoundationModels), or a custom command
- Extracts vendor name, invoice date, and confidence score from PDF content
- Uses sender domain as a strong hint for vendor identification
- Heuristic fallback when LLM is unavailable

### 📋 Document Triage (Kanban UI)
- **Rename triage**: review and fix auto-generated filenames
- **3-column kanban**: To Sort → Included / Skipped
- Bulk actions: whitelist/blacklist a sender moves all related documents
- Move documents between states with one click

### 🏷️ Smart Renaming
- Pattern: `YYYY_MM_DD_vendor.ext`
- Confidence threshold prevents bad renames (configurable)
- Manual override always available

---

## Quick Start

### Prerequisites
- Python 3.12+
- macOS (for Spark integration and Apple Intelligence)
- [Spark Desktop](https://sparkmailapp.com/) running (for email scanning)

### Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,docs,llm]"
```

### Run

```bash
compta-auto web
```

Open **http://127.0.0.1:8765** — scan, triage, and rename from the browser.

### CLI

```bash
compta-auto scan --months 1
compta-auto add-provider --vendor OpenAI --url https://platform.openai.com/...
```

---

## Configuration

All settings via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `COMPTA_DB_PATH` | `data/compta.sqlite3` | SQLite database location |
| `COMPTA_RAW_DIR` | `data/raw` | Downloaded attachments storage |
| `COMPTA_RENAMED_DIR` | `data/renamed` | Output directory for renamed files |
| `COMPTA_ACCOUNTING_DOMAIN` | `ACCOUNTING_DOMAIN_PLACEHOLDER` | Domain that triggers auto-selection |
| `COMPTA_MIN_RENAME_CONFIDENCE` | `0.82` | LLM confidence threshold for auto-rename |
| `COMPTA_SCAN_FOLDER` | *(none)* | Default local folder to scan |
| `COMPTA_LLM_EXTRACTOR_COMMAND` | *(none)* | Custom extraction command |
| `OPENAI_API_KEY` | *(none)* | Enables OpenAI extraction backend |

### Custom Extractor Command

`COMPTA_LLM_EXTRACTOR_COMMAND` receives the document path as its last argument and must output JSON:

```json
{"vendor": "OVH", "date": "2026-05-29", "confidence": 0.95}
```

---

## Architecture

```
src/compta_auto/
├── app.py            # FastAPI routes & web UI
├── cli.py            # CLI entry point
├── config.py         # Pydantic settings
├── db.py             # SQLite schema & connection
├── extraction.py     # LLM + heuristic metadata extraction
├── files.py          # File download & management
├── models.py         # Data models
├── normalize.py      # Text normalization utilities
├── pipeline.py       # Orchestration (scan mails, scan folder)
├── renamer.py        # Filename generation logic
├── repositories.py   # Data access layer
└── web/
    ├── templates/    # Jinja2 HTML templates
    └── static/       # CSS + JS

tools/
└── apple-extractor/  # Swift CLI using FoundationModels + PDFKit
```

---

## Development

```bash
# Run tests
pytest

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

---

## License

Private — personal use only.

