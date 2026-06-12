# Compta Auto

**Local-first accounting automation for freelancers on macOS.**

Scans email inboxes and provider portals for invoices, extracts metadata via LLM, renames documents with a consistent `YYYY_MM_DD_vendor.ext` convention, uploads them to your accountant's platform, and provides a web UI to triage and organize everything — all without sending data to the cloud (unless you opt into OpenAI).

---

## Features

### 📬 Email Ingestion
- Reads billing-related emails from **Spark Desktop** (macOS CLI)
- Auto-selects mails sent to your accounting domain
- Downloads PDF/image attachments automatically
- Detects invoice download links and provider portal URLs
- Whitelist/blacklist senders with one click — rules persist across runs
- Re-scans previously blank mails and refreshes their metadata

### 📁 Local Folder Scanning
- Point to any local folder containing scanned receipts
- Native macOS folder picker (no typing paths)
- Configurable timespan (1 week → 3 months, or "since last scan")
- Original files stay untouched; renamed copies go to the output directory

### 🤖 LLM-Powered Metadata Extraction
- **Apple Intelligence** (on-device via FoundationModels + PDFKit — default)
- **OpenAI** (cloud, configurable model)
- Custom CLI command (pipe any local model)
- Extracts vendor name, invoice date, and confidence score from PDF content
- Uses sender domain as a strong hint for vendor identification
- Heuristic regex fallback when no LLM is available

### 🔌 Provider Fetchers (Automated Invoice Download)
Built-in scrapers for common service providers:
- **Spotify** — headless Playwright login, downloads monthly invoices
- **OpenAI** — fetches billing history from platform.openai.com
- **Free Mobile / Freebox** — OTP-based authentication via mailbox polling
- **Orange / Sosh** — mobile plan invoices
- **OVH** — cloud hosting invoices
- **Engie** — energy bills with OTP support
- **Henrri** — invoicing platform API (sale invoices with PDF download)

Each fetcher authenticates (with encrypted stored credentials), downloads new invoices, and feeds them into the pipeline automatically. Credentials are encrypted at rest with a Fernet key derived from the local database path.

### 📋 Document Triage (Web UI)
- **Mail triage**: review incoming accounting emails, accept/reject
- **Rename triage**: review and fix auto-generated filenames
- **3-column kanban**: To Sort → Included / Skipped
- Bulk actions: whitelist/blacklist a sender moves all related documents
- Move documents between states with one click
- Real-time progress via **Server-Sent Events (SSE)**

### 🏷️ Smart Renaming
- Pattern: `YYYY_MM_DD_vendor.ext`
- Confidence threshold prevents bad renames (configurable, default 0.82)
- Collision-safe with automatic suffix numbering
- Manual override always available from the web UI

### 📤 Inqom Upload
- Uploads finalized documents to [Inqom](https://www.inqom.com/) (accounting platform)
- Automatic document type classification (purchase vs. sale)
- Fiscal year–aware grouping
- Dry-run mode to preview before uploading
- Browser-based authentication via Playwright

### 🔐 OTP Reader
- Automatic OTP code extraction from Spark mailbox
- Polls for incoming OTP emails (Free Mobile, Engie/Okta)
- Configurable timeout and polling interval
- Used internally by provider fetchers requiring 2FA

---

## Quick Start

### Prerequisites
- **Python 3.12+**
- **macOS** (required for Spark CLI and Apple Intelligence)
- [Spark Desktop](https://sparkmailapp.com/) with the `spark` CLI tool available
- (Optional) [Playwright](https://playwright.dev/) for provider fetchers and Inqom upload
- (Optional) [Ezida](https://github.com/anthropics/ezida) for Kanban-based task tracking via `kanban.toml`

### Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,docs,llm]"

# For provider fetchers and Inqom upload:
pip install playwright
playwright install chromium
```

### Run

```bash
compta-auto web
```

Open **http://127.0.0.1:8765** — scan, triage, rename, and upload from the browser.

### CLI Commands

```bash
# Scan emails from the last month
compta-auto scan --months 1

# Auto-categorize uncategorized documents
compta-auto categorize

# Register a provider portal URL
compta-auto add-provider --vendor OpenAI --url https://platform.openai.com/...

# Upload finalized documents to Inqom
compta-auto inqom-upload
compta-auto inqom-upload --dry-run --type purchase

# List / download Henrri invoices
compta-auto henrri-invoices --type all
compta-auto henrri-invoices --type Invoice --download-pdf ./invoices

# Explore Inqom UI interactively (debug)
compta-auto inqom-explore
```

---

## Configuration

All settings via environment variables or a `.env` file at the project root:

| Variable | Default | Description |
|----------|---------|-------------|
| `COMPTA_DB_PATH` | `data/compta.sqlite3` | SQLite database location |
| `COMPTA_RAW_DIR` | `data/raw` | Downloaded attachments storage |
| `COMPTA_RENAMED_DIR` | `data/renamed` | Output directory for renamed files |
| `COMPTA_OUTPUT_DIR` | `data/output` | General output directory |
| `COMPTA_ACCOUNTING_DOMAIN` | *(empty)* | Email domain that triggers auto-selection (e.g. `mycompany.com`) |
| `COMPTA_MIN_RENAME_CONFIDENCE` | `0.82` | LLM confidence threshold for auto-rename |
| `COMPTA_SCAN_FOLDER` | *(none)* | Default local folder to scan |
| `COMPTA_LLM_EXTRACTOR_COMMAND` | *(none)* | Custom extraction CLI command |
| `COMPTA_OPENAI_API_KEY` | *(none)* | Enables OpenAI extraction backend |
| `COMPTA_OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model for extraction |
| `COMPTA_USE_APPLE_LLM` | `true` | Use Apple Intelligence on-device extraction |
| `COMPTA_INQOM_EMAIL` | *(none)* | Inqom account email |
| `COMPTA_INQOM_PASSWORD` | *(none)* | Inqom account password |
| `COMPTA_INQOM_CLIENT_ID` | *(empty)* | Inqom enterprise/client ID |
| `COMPTA_INQOM_FISCAL_YEAR_START_MONTH` | `8` | Fiscal year start (1=Jan, 8=Aug) |
| `COMPTA_SALE_VENDOR_MARKERS` | *(empty)* | Comma-separated vendor keywords that indicate a "sale" invoice |
| `COMPTA_HENRRI_CLIENT_ID` | *(none)* | Henrri API client ID |
| `COMPTA_HENRRI_CLIENT_SECRET` | *(none)* | Henrri API client secret |
| `COMPTA_HENRRI_BASE_URL` | `https://api-sandbox.henrri.io/v1` | Henrri API base URL (switch to `https://api.henrri.io/v1` for production) |

### Custom Extractor Command

`COMPTA_LLM_EXTRACTOR_COMMAND` receives the document path as its last argument and must output JSON to stdout:

```json
{"vendor": "OVH", "date": "2026-05-29", "confidence": 0.95}
```

### Document Type Classification

Documents are auto-categorized as `purchase` (default) or `sale`. Sale detection is controlled by `COMPTA_SALE_VENDOR_MARKERS` — a comma-separated list of vendor name substrings that indicate outgoing invoices (e.g. `clientA,clientB`).

---

## Architecture

```
src/compta_auto/
├── app.py              # FastAPI application factory & dependency injection
├── cli.py              # CLI entry point (argparse subcommands)
├── config.py           # Pydantic settings (env-based configuration)
├── db.py              # SQLite schema definition & migrations
├── extraction.py       # LLM + heuristic metadata extraction
├── files.py            # File I/O, SHA-256 hashing, attachment writing
├── inqom_upload.py     # Inqom upload orchestration & candidate selection
├── inqom_uploader.py   # Playwright-based Inqom authentication & HTTP upload
├── links.py            # Invoice URL detection & provider matching
├── mail_to_pdf.py      # Convert raw email body to PDF for archival
├── models.py           # Domain models (MailMessage, ExtractedMetadata, etc.)
├── normalize.py        # Email, vendor, URL normalization
├── otp_reader.py       # OTP code polling from Spark mailbox
├── pipeline.py         # Main orchestrator (scan → extract → rename → categorize)
├── renamer.py          # Filename generation (YYYY_MM_DD_vendor.ext)
├── repositories.py     # Data access layer (SQLite queries)
├── spark_client.py     # Spark Desktop CLI wrapper (search, read threads)
│
├── providers/
│   └── base.py         # Shared provider utilities (cookie jar, auth errors)
│
├── routes/
│   ├── credentials.py  # Encrypted credential storage endpoints
│   ├── deps.py         # FastAPI dependency injection helpers
│   ├── documents.py    # Document CRUD & rename endpoints
│   ├── inqom.py        # Inqom upload UI & SSE streaming
│   ├── mails.py        # Mail triage endpoints
│   ├── providers.py    # Provider fetch trigger endpoints (SSE)
│   ├── rules.py        # Vendor rule management
│   └── scan.py         # Scan trigger endpoints (mail & folder)
│
├── services/
│   ├── categorize.py   # Auto-categorization logic (purchase vs. sale)
│   ├── crypto.py       # Fernet key derivation & credential encryption
│   └── fetch_service.py # Generic SSE provider fetch orchestrator
│
├── web/
│   ├── templates/      # Jinja2 HTML templates (single-page + HTMX partials)
│   └── static/         # CSS + vanilla JS (SSE handling, UI interactions)
│
├── # Provider-specific fetchers:
├── engie_invoices.py
├── free_invoices.py
├── freebox_invoices.py
├── henrri_invoices.py
├── openai_invoices.py
├── orange_invoices.py
├── ovh_invoices.py
└── spotify.py

tools/
├── apple-extractor/    # Swift CLI — PDFKit text extraction + FoundationModels inference
│   ├── Package.swift
│   └── Sources/
└── spotify-invoices/   # Standalone Spotify invoice fetcher (Playwright)
    └── fetch_invoices.py
```

### Data Flow

```
┌─────────────┐    ┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│ Spark Mail  │───▶│   Pipeline   │───▶│  Extraction    │───▶│   Renamer    │
│  (or folder)│    │ (filter/save)│    │ (LLM/heuristic)│    │(YYYY_MM_DD_X)│
└─────────────┘    └──────┬───────┘    └────────────────┘    └──────┬───────┘
                          │                                         │
                          ▼                                         ▼
                   ┌──────────────┐                         ┌──────────────┐
                   │   SQLite DB  │◀────────────────────────│  Categorize  │
                   │ (mails, docs,│                         │(purchase/sale)│
                   │  rules, runs)│                         └──────────────┘
                   └──────┬───────┘
                          │
                          ▼
                   ┌──────────────┐    ┌──────────────┐
                   │   Web UI     │───▶│ Inqom Upload │
                   │(triage/review)│    │  (Playwright) │
                   └──────────────┘    └──────────────┘
```

### Database Schema (key tables)

| Table | Purpose |
|-------|---------|
| `runs` | Scan execution history with status and summary |
| `vendor_rules` | Whitelist/blacklist rules (sender, domain, or vendor match) |
| `mails` | Ingested email metadata and processing status |
| `documents` | Extracted documents with paths, metadata, and lifecycle status |
| `credentials` | Encrypted provider credentials (Fernet) |

### Document Lifecycle

```
mail_needs_triage → mail_auto_selected → doc_needs_extraction → doc_extracted
    → doc_renamed → doc_included → (uploaded to Inqom)
```

---

## Web UI

The web interface is a single-page application served by FastAPI with Jinja2 templates, vanilla JavaScript, and Server-Sent Events for real-time progress.

Key pages:
- **Dashboard** — overview with scan triggers, accounting domain status
- **Mail triage** — accept/reject incoming emails, bulk operations
- **Documents** — kanban-style board for document lifecycle management
- **Rename review** — approve or correct auto-generated filenames
- **Providers** — trigger fetches from configured provider portals
- **Rules** — manage sender/domain/vendor whitelist and blacklist
- **Inqom** — upload finalized documents to the accounting platform

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev,docs,llm]"

# Run tests
pytest

# Run a specific test
pytest tests/test_pipeline.py::test_scan_attaches_pdf_to_mail -x

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type checking (if mypy is installed)
mypy src/
```

### Project Conventions
- Python 3.12+ with type hints on all function signatures
- Formatter/linter: **ruff** (line length 100)
- Testing: **pytest**
- All emails normalized to lowercase on storage
- Vendor names normalized (lowercase, stripped)
- File extensions always lowercase in renamed output

---

## Security & Privacy

- **Local-first**: all data stays on your machine by default
- **No cloud dependency**: Apple Intelligence runs on-device; OpenAI is opt-in
- **Encrypted credentials**: provider passwords stored with Fernet (key derived from DB path)
- **No telemetry**: the application makes no outbound requests except to configured providers
- **Git-clean**: no personal data committed to the repository

---

## License

Licensed under the [Apache License, Version 2.0](LICENSE).

