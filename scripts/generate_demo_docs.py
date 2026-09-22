"""
Generate the demo documents for the fictional company "Ridgeline Equipment Rentals".

    .venv/bin/python scripts/generate_demo_docs.py

Input:  the text sources in `sample_data/source/*.md` (edit these to change content).
Output: five files in `documents/`, deliberately in mixed formats so the demo proves
        the assistant handles what real small businesses actually have:

    Ridgeline_Rental_Agreement_2026.pdf       normal PDF with a text layer
    Returns_and_Damages_Policy_scanned.pdf    image-only PDF, like a scanned printout (needs OCR)
    Fleet_Maintenance_Manual.pdf              normal PDF with a text layer
    Employee_Handbook_2026.docx               Word document
    Branch_FAQ_and_Hours.txt                  plain text

The sources use a tiny Markdown-like format that this script understands:
    "# Title", "## Heading", "### Sub-heading", "- bullet", "| table | rows |",
    and blank lines between paragraphs.
"""

from __future__ import annotations

import io
import random
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz  # PyMuPDF: used here to turn PDF pages into images for the "scanned" copy
from docx import Document
from docx.shared import Pt
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "sample_data" / "source"
OUTPUT_DIR = PROJECT_ROOT / "documents"
COMPANY = "Ridgeline Equipment Rentals, LLC"


# ---------------------------------------------------------------------------
# 1. Parse the simple source format into a list of blocks
# ---------------------------------------------------------------------------

@dataclass
class Block:
    kind: str                 # "title" | "h1" | "h2" | "para" | "bullets" | "table"
    text: str = ""            # for title / headings / paragraphs
    items: list | None = None  # bullet strings, or table rows (list of cell lists)


def parse_source(path: Path) -> list[Block]:
    """Turn a source file into blocks. Consecutive bullet or table lines are grouped."""
    blocks: list[Block] = []
    para_lines: list[str] = []

    def flush_para() -> None:
        # A paragraph is every non-special line up to the next blank line.
        if para_lines:
            blocks.append(Block("para", " ".join(para_lines)))
            para_lines.clear()

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            flush_para()
        elif line.startswith("### "):
            flush_para(); blocks.append(Block("h2", line[4:]))
        elif line.startswith("## "):
            flush_para(); blocks.append(Block("h1", line[3:]))
        elif line.startswith("# "):
            flush_para(); blocks.append(Block("title", line[2:]))
        elif line.startswith("- "):
            flush_para()
            if not blocks or blocks[-1].kind != "bullets":
                blocks.append(Block("bullets", items=[]))
            blocks[-1].items.append(line[2:])
        elif line.startswith("|"):
            flush_para()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} for c in cells):
                continue  # the |---|---| separator line under a table header
            if not blocks or blocks[-1].kind != "table":
                blocks.append(Block("table", items=[]))
            blocks[-1].items.append(cells)
        else:
            para_lines.append(line)
    flush_para()
    return blocks


# ---------------------------------------------------------------------------
# 2. PDF output (reportlab)
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """reportlab paragraphs use mini-HTML, so escape the three special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


STYLES = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=10),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=12, spaceAfter=5),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=8, spaceAfter=3),
    "para": ParagraphStyle("para", fontName="Times-Roman", fontSize=11, leading=14.5, spaceAfter=6, alignment=TA_JUSTIFY),
    "cell": ParagraphStyle("cell", fontName="Times-Roman", fontSize=9.5, leading=11.5),
    "cellhead": ParagraphStyle("cellhead", fontName="Helvetica-Bold", fontSize=9, leading=11),
}


def make_numbered_canvas(doc_code: str, doc_title: str):
    """
    Build a canvas class that draws a header and a "Page X of Y" footer.
    "Y" is only known after all pages are laid out, so pages are buffered and
    the header/footer is drawn on each one at save time (standard reportlab recipe).
    """
    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self._draw_frame(total)
                super().showPage()
            super().save()

        def _draw_frame(self, total: int) -> None:
            width, height = LETTER
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#444444"))
            # Header: company on the left, document code on the right, thin rule below.
            self.drawString(inch, height - 0.6 * inch, COMPANY)
            self.drawRightString(width - inch, height - 0.6 * inch, doc_code)
            self.setStrokeColor(colors.HexColor("#999999"))
            self.line(inch, height - 0.65 * inch, width - inch, height - 0.65 * inch)
            # Footer: title, page number, and the usual "uncontrolled" note.
            self.drawString(inch, 0.55 * inch, f"{doc_title} | Uncontrolled when printed")
            self.drawRightString(width - inch, 0.55 * inch, f"Page {self._pageNumber} of {total}")

    return NumberedCanvas


def build_pdf(blocks: list[Block], out_path: Path, doc_code: str) -> None:
    """Lay the blocks out as a letter-size PDF with header, footer and page numbers."""
    title = next(b.text for b in blocks if b.kind == "title")
    story = []
    for b in blocks:
        if b.kind in ("title", "h1", "h2", "para"):
            story.append(Paragraph(_esc(b.text), STYLES[b.kind]))
        elif b.kind == "bullets":
            story.append(ListFlowable(
                [ListItem(Paragraph(_esc(t), STYLES["para"]), leftIndent=14) for t in b.items],
                bulletType="bullet", start="•", leftIndent=14,
            ))
        elif b.kind == "table":
            header, *rows = b.items
            data = [[Paragraph(_esc(c), STYLES["cellhead"]) for c in header]]
            data += [[Paragraph(_esc(c), STYLES["cell"]) for c in r] for r in rows]
            table = Table(data, repeatRows=1, hAlign="LEFT", colWidths=_col_widths(header))
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#888888")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6E6E6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story += [Spacer(1, 4), table, Spacer(1, 8)]

    doc = SimpleDocTemplate(
        str(out_path), pagesize=LETTER, title=title, author=COMPANY,
        leftMargin=inch, rightMargin=inch, topMargin=0.95 * inch, bottomMargin=0.9 * inch,
    )
    doc.build(story, canvasmaker=make_numbered_canvas(doc_code, title))


def _col_widths(header: list[str]) -> list[float]:
    """Give text-heavy columns more room: the widest header word count wins space."""
    usable = LETTER[0] - 2 * inch
    if len(header) == 2:
        return [usable * 0.62, usable * 0.38]
    if len(header) == 3:
        return [usable * 0.22, usable * 0.48, usable * 0.30]
    # Rate-schedule style tables: code, long name, then short numeric columns.
    first, second = 0.11, 0.37
    rest = (1 - first - second) / (len(header) - 2)
    return [usable * first, usable * second] + [usable * rest] * (len(header) - 2)


# ---------------------------------------------------------------------------
# 3. "Scanned" PDF: print the PDF to images, degrade them, rebuild as image-only
# ---------------------------------------------------------------------------

def make_scanned_copy(clean_pdf: Path, out_path: Path, dpi: int = 300, seed: int = 7) -> None:
    """
    Simulate a photocopied / scanned document: every page becomes a slightly tilted,
    slightly noisy grayscale image with no text layer at all. The assistant can only
    read this file through OCR, which is exactly what the demo needs to prove.
    """
    rng = random.Random(seed)  # fixed seed = identical output on every run
    src = fitz.open(clean_pdf)
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)

        # Tilt the page, as if the sheet went into the scanner crooked. Each page
        # gets its own angle, because a stack of paper never feeds in straight.
        # A minimum angle, so no page comes out looking perfectly straight.
        angle = rng.choice([-1, 1]) * rng.uniform(0.9, 1.7)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
        # Slight blur (toner spread), a grey paper tone, and specks of dust.
        img = img.filter(ImageFilter.GaussianBlur(radius=0.7))
        img = Image.blend(img, Image.new("L", img.size, 224), 0.13)
        img = _add_edge_shadow(img, rng)
        img = _add_grain(img, rng)

        # Store as JPEG, like most office scanners do, and place it on a letter page.
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=62)
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=buf.getvalue())

    out.set_metadata({"title": "Scanned document", "producer": "Office scanner"})
    out.save(out_path, garbage=4, deflate=True)


def _add_edge_shadow(img: Image.Image, rng: random.Random) -> Image.Image:
    """
    Darken one vertical edge of the page. Real scans and photocopies show this
    band where the sheet lifts away from the glass, and it is the detail that
    makes a page read as "scanned" at a glance. The band is kept away from the
    text margin so it never darkens words enough to hurt OCR.
    """
    w, h = img.size
    band = int(w * 0.055)                      # about half of the 1-inch margin
    left_edge = rng.random() < 0.5             # which side the sheet lifted from
    gradient = Image.linear_gradient("L").resize((band, h))   # 0 (black) -> 255 (white)
    if not left_edge:
        gradient = gradient.transpose(Image.FLIP_LEFT_RIGHT)
    # Lighten the gradient so the darkest point is mid-grey, not black.
    shade = gradient.point(lambda v: 150 + (v * 105) // 255)
    strip = img.crop((0, 0, band, h)) if left_edge else img.crop((w - band, 0, w, h))
    darkened = Image.blend(strip, shade, 0.55)
    img.paste(darkened, (0, 0) if left_edge else (w - band, 0))
    return img


def _add_grain(img: Image.Image, rng: random.Random) -> Image.Image:
    """Sprinkle a few thousand grey specks, like dust on the scanner glass."""
    px = img.load()
    w, h = img.size
    for _ in range(4000):
        x, y = rng.randrange(w), rng.randrange(h)
        px[x, y] = rng.randrange(90, 200)
    return img


# ---------------------------------------------------------------------------
# 4. DOCX output (python-docx)
# ---------------------------------------------------------------------------

def build_docx(blocks: list[Block], out_path: Path) -> None:
    """Write the blocks as a Word document using Word's built-in heading styles."""
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.sections[0].header.paragraphs[0].text = f"{COMPANY} | Employee Handbook 2026"

    for b in blocks:
        if b.kind == "title":
            doc.add_heading(b.text, level=0)
        elif b.kind == "h1":
            doc.add_heading(b.text, level=1)
        elif b.kind == "h2":
            doc.add_heading(b.text, level=2)
        elif b.kind == "para":
            doc.add_paragraph(b.text)
        elif b.kind == "bullets":
            for item in b.items:
                doc.add_paragraph(item, style="List Bullet")
        elif b.kind == "table":
            header, *rows = b.items
            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            for cell, text in zip(table.rows[0].cells, header):
                cell.text = text
                cell.paragraphs[0].runs[0].bold = True
            for row in rows:
                for cell, text in zip(table.add_row().cells, row):
                    cell.text = text
    doc.save(out_path)


# ---------------------------------------------------------------------------
# 5. Plain-text output
# ---------------------------------------------------------------------------

def build_txt(blocks: list[Block], out_path: Path) -> None:
    """Write the blocks as plain text: headings underlined, paragraphs wrapped at 88 chars."""
    lines: list[str] = []
    for b in blocks:
        if b.kind == "title":
            lines += [b.text.upper(), "=" * len(b.text), ""]
        elif b.kind == "h1":
            lines += ["", b.text.upper(), "-" * len(b.text), ""]
        elif b.kind == "h2":
            lines += [b.text, ""]
        elif b.kind == "para":
            lines += [textwrap.fill(b.text, 88), ""]
        elif b.kind == "bullets":
            lines += [textwrap.fill(t, 88, initial_indent="  * ", subsequent_indent="    ") for t in b.items] + [""]
        elif b.kind == "table":
            lines += ["  " + " | ".join(r) for r in b.items] + [""]
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Normal PDFs with a text layer.
    build_pdf(parse_source(SOURCE_DIR / "rental_agreement.md"),
              OUTPUT_DIR / "Ridgeline_Rental_Agreement_2026.pdf", "RER-LEG-001 Rev. 7")
    build_pdf(parse_source(SOURCE_DIR / "maintenance_manual.md"),
              OUTPUT_DIR / "Fleet_Maintenance_Manual.pdf", "RER-MNT-002 Rev. 11")

    # Scanned PDF: build a clean PDF in a temp location, then convert it to images only.
    clean_tmp = OUTPUT_DIR / ".returns_clean_tmp.pdf"
    build_pdf(parse_source(SOURCE_DIR / "returns_damages_policy.md"), clean_tmp, "RER-OPS-014 Rev. 4")
    make_scanned_copy(clean_tmp, OUTPUT_DIR / "Returns_and_Damages_Policy_scanned.pdf")
    clean_tmp.unlink()

    build_docx(parse_source(SOURCE_DIR / "employee_handbook.md"), OUTPUT_DIR / "Employee_Handbook_2026.docx")
    build_txt(parse_source(SOURCE_DIR / "branch_faq.md"), OUTPUT_DIR / "Branch_FAQ_and_Hours.txt")

    for f in sorted(OUTPUT_DIR.iterdir()):
        if not f.name.startswith("."):
            print(f"created {f.relative_to(PROJECT_ROOT)}  ({f.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
