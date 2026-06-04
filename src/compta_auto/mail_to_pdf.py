"""Convert a mail record to a PDF file suitable for accounting."""

from __future__ import annotations

import html
import re
from pathlib import Path


def _strip_spark_preamble(body: str) -> str:
    """Remove the Spark CLI metadata header, keep only the mail content."""
    lines = body.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("──") or line.strip().startswith("---"):
            body_start = i + 1
            break

    clean_lines = lines[body_start:]
    # Skip leading metadata lines after separator
    content_start = 0
    for i, line in enumerate(clean_lines):
        stripped = line.strip()
        if stripped and not any(
            stripped.startswith(prefix)
            for prefix in ("ID:", "Subject:", "From:", "To:", "Date:", "Type:", "CC:", "BCC:")
        ):
            content_start = i
            break

    return "\n".join(clean_lines[content_start:]).strip()


def mail_to_pdf(
    subject: str,
    sender: str,
    recipients: str,
    sent_at: str | None,
    body: str,
    output_path: Path,
) -> Path:
    """Render mail as HTML then print to PDF via Playwright (headless Chromium)."""
    import markdown

    clean_body = _strip_spark_preamble(body)
    body_html = markdown.markdown(clean_body, extensions=["tables"])

    date_line = f'<p class="meta">Date: {html.escape(sent_at)}</p>' if sent_at else ""

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
    max-width: 680px;
    margin: 0 auto;
    padding: 40px 30px;
  }}
  .header {{
    margin-bottom: 20px;
    padding-bottom: 14px;
    border-bottom: 2px solid #e5e5e5;
  }}
  .header h1 {{
    font-size: 16pt;
    margin: 0 0 6px 0;
    color: #111;
  }}
  .meta {{
    font-size: 9pt;
    color: #666;
    margin: 2px 0;
  }}
  .body h1 {{ font-size: 14pt; margin: 18px 0 8px 0; font-weight: 600; }}
  .body h2 {{ font-size: 12pt; margin: 14px 0 6px 0; font-weight: 600; color: #333; }}
  .body h3 {{ font-size: 10pt; margin: 12px 0 4px 0; font-weight: 600; color: #555; }}
  .body p {{ margin: 4px 0; }}
  .body a {{ color: #0066cc; text-decoration: none; }}
  .body table {{ border-collapse: collapse; width: 100%; margin: 8px 0; }}
  .body td, .body th {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
</style>
</head>
<body>
  <div class="header">
    <h1>{html.escape(subject)}</h1>
    <p class="meta">From: {html.escape(sender)}</p>
    <p class="meta">To: {html.escape(recipients)}</p>
    {date_line}
  </div>
  <div class="body">
    {body_html}
  </div>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(full_html, wait_until="networkidle")
        page.pdf(path=str(output_path), format="A4", margin={
            "top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"
        })
        browser.close()

    return output_path
