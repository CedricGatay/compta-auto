"""Convert a mail record to a PDF file suitable for accounting."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF


def mail_to_pdf(
    subject: str,
    sender: str,
    recipients: str,
    sent_at: str | None,
    body: str,
    output_path: Path,
) -> Path:
    """Render mail metadata + body as a clean PDF invoice-style document."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 7, subject)
    pdf.ln(4)

    # Metadata block
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f"From: {sender}")
    pdf.ln()
    pdf.cell(0, 5, f"To: {recipients}")
    pdf.ln()
    if sent_at:
        pdf.cell(0, 5, f"Date: {sent_at}")
        pdf.ln()
    pdf.ln(6)

    # Separator
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    # Body
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "", 10)

    # Strip Spark CLI preamble (everything before the first separator line)
    lines = body.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("──") or line.strip().startswith("---"):
            body_start = i + 1
            break

    clean_lines = lines[body_start:]
    # Skip leading metadata lines after separator (ID, Subject, From, To, Date, Type)
    content_start = 0
    for i, line in enumerate(clean_lines):
        stripped = line.strip()
        if stripped and not any(
            stripped.startswith(prefix)
            for prefix in ("ID:", "Subject:", "From:", "To:", "Date:", "Type:", "CC:", "BCC:")
        ):
            content_start = i
            break

    final_body = "\n".join(clean_lines[content_start:]).strip()

    # Wrap long lines and write
    usable_width = pdf.w - pdf.l_margin - pdf.r_margin
    for paragraph in final_body.split("\n"):
        if not paragraph.strip():
            pdf.ln(4)
            continue
        pdf.multi_cell(usable_width, 5, paragraph)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path
