"""Renders a SatQuery analysis report (dict built by report_service) to PDF bytes.

Pure presentation: no database, Storage or network access here, and nothing
is invented -- every section renders only the fields the caller filled, and a
missing field is left out rather than shown as a placeholder.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---- Palette ---------------------------------------------------------------
NAVY = colors.HexColor("#0B1F3A")
INK = colors.HexColor("#1E293B")
MUTED = colors.HexColor("#5B6B82")
BLUE = colors.HexColor("#2563EB")
HEADER_BG = colors.HexColor("#E8F4FF")
HEADER_LINE = colors.HexColor("#B9DAF7")
SECTION_LINE = colors.HexColor("#93C5FD")
SOFT_BG = colors.HexColor("#F3F8FD")
SOFT_LINE = colors.HexColor("#D6E6F7")
ROW_ALT = colors.HexColor("#F8FBFE")
FOOTER_BG = colors.HexColor("#F1F5FA")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 22 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
MAX_FIGURE_H = 74 * mm  # lets a typical scene still fit on page 1 under the metadata
MAX_IMAGE_EDGE = 1800  # px; keeps the PDF small without visible loss at print size

FOOTER_TEXT = "SatQuery AI • Satellite Intelligence & Analysis"


def _style(name: str, **kw: Any) -> ParagraphStyle:
    base = {"fontName": "Helvetica", "fontSize": 9.5, "leading": 13.5, "textColor": INK}
    base.update(kw)
    return ParagraphStyle(name, **base)


S_BRAND = _style("brand", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=NAVY)
S_BRAND_SUB = _style("brandSub", fontSize=10, leading=13, textColor=colors.HexColor("#2B4C7E"))
S_TITLE = _style("title", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY)
S_KIND = _style("kind", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=BLUE)
S_H2 = _style("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=NAVY)
S_H3 = _style("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=NAVY)
S_BODY = _style("body")
S_LABEL = _style("label", fontSize=8.5, leading=12, textColor=MUTED)
S_VALUE = _style("value", fontName="Helvetica-Bold", fontSize=9.5, leading=13, textColor=NAVY)
S_QUOTE = _style("quote", fontName="Helvetica-Oblique", fontSize=10.5, leading=15, textColor=NAVY)
S_CAPTION = _style("caption", fontSize=8.5, leading=11, textColor=MUTED, alignment=TA_CENTER)
S_NOTE = _style("note", fontName="Helvetica-Oblique", fontSize=9, leading=12.5, textColor=MUTED)


def _p(text: Any, style: ParagraphStyle = S_BODY) -> Paragraph:
    """A paragraph of untrusted text: escaped, newlines kept."""
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


class _SectionHeading(Flowable):
    """Navy heading with a thin light-blue rule under it."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.para = Paragraph(escape(text), S_H2)

    def wrap(self, avail_w, avail_h):
        self.width = avail_w
        _, h = self.para.wrap(avail_w, avail_h)
        self.height = h + 7
        return self.width, self.height

    def draw(self):
        self.para.drawOn(self.canv, 0, 7)
        self.canv.setStrokeColor(SECTION_LINE)
        self.canv.setLineWidth(0.8)
        self.canv.line(0, 2, self.width, 2)


def _section(title: str, gap: float = 6) -> list[Any]:
    """Section heading + gap, both kept with whatever follows them."""
    heading, spacer = _SectionHeading(title), Spacer(1, gap)
    heading.keepWithNext = spacer.keepWithNext = 1
    return [heading, spacer]


def _boxed(rows: list[list[Any]], col_widths: list[float], *, zebra: bool = False, pad: float = 6) -> Table:
    table = Table(rows, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("BOX", (0, 0), (-1, -1), 0.6, SOFT_LINE),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), pad + 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad + 2),
        ("TOPPADDING", (0, 0), (-1, -1), pad - 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad - 2),
    ]
    if zebra:
        for i in range(len(rows)):
            if i % 2 == 1:
                style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
            if i:
                style.append(("LINEABOVE", (0, i), (-1, i), 0.4, SOFT_LINE))
    table.setStyle(TableStyle(style))
    return table


def _key_values(pairs: list[tuple[str, Any]]) -> Table:
    rows = [[_p(label, S_LABEL), _p(value, S_VALUE)] for label, value in pairs]
    return _boxed(rows, [CONTENT_W * 0.3, CONTENT_W * 0.7], zebra=True)


def _highlight(content: list[Any]) -> Table:
    table = Table([[content]], colWidths=[CONTENT_W])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, SOFT_LINE),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


def _prepare_image(data: bytes) -> tuple[io.BytesIO, int, int]:
    """Decode, downscale, flatten transparency onto white -> JPEG/PNG buffer."""
    img = PILImage.open(io.BytesIO(data))
    img.load()
    if max(img.size) > MAX_IMAGE_EDGE:
        img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = PILImage.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    return buf, img.width, img.height


def _figure(data: bytes, caption: str, heading: list[Any] | None = None) -> list[Any]:
    """Bordered, centred image + caption, kept on one page -- with `heading`
    (a section title) when given, so a title is never stranded above it."""
    buf, w, h = _prepare_image(data)
    max_w = CONTENT_W - 16
    scale = min(max_w / w, MAX_FIGURE_H / h)  # never stretch: one scale for both axes
    image = Image(buf, width=w * scale, height=h * scale)
    frame = Table([[image]], colWidths=[CONTENT_W])
    frame.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BOX", (0, 0), (-1, -1), 0.6, SOFT_LINE),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [KeepTogether([*(heading or []), frame, Spacer(1, 4), _p(caption, S_CAPTION)]), Spacer(1, 10)]


def _header_band(report: dict) -> Table:
    band = Table(
        [[[_p("SatQuery", S_BRAND), Spacer(1, 2), _p("Satellite Intelligence & Analysis Report", S_BRAND_SUB)]]],
        colWidths=[CONTENT_W],
    )
    band.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
                ("BOX", (0, 0), (-1, -1), 0.8, HEADER_LINE),
                ("LINEBEFORE", (0, 0), (0, -1), 3, BLUE),
                ("ROUNDEDCORNERS", [8, 8, 8, 8]),
                ("LEFTPADDING", (0, 0), (-1, -1), 16),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    return band


def _job_block(job: dict, index: int, total: int, figure_no: list[int]) -> list[Any]:
    out: list[Any] = []
    if total > 1:
        out += [_p(f"Query {index} of {total}", S_H3), Spacer(1, 2), _p(f"“{job.get('query') or ''}”", S_NOTE), Spacer(1, 5)]

    details = [(label, job[key]) for label, key in (
        ("Job ID", "job_id"),
        ("Status", "status"),
        ("Submitted", "created_at"),
        ("Model", "model_name"),
        ("Confidence", "confidence"),
    ) if job.get(key) not in (None, "")]
    if details:
        out.append(_key_values(details))
        out.append(Spacer(1, 6))

    if job.get("answer"):
        out.append(_highlight([_p("Model response", S_LABEL), Spacer(1, 3), _p(job["answer"])]))
    elif job.get("error"):
        out.append(_highlight([_p("Processing error", S_LABEL), Spacer(1, 3), _p(job["error"])]))
    else:
        out.append(_p(job.get("pending_note") or "Result not available.", S_NOTE))
    out.append(Spacer(1, 6))

    if job.get("outputs"):
        out.append(_p("Structured output", S_LABEL))
        out.append(Spacer(1, 3))
        out.append(_key_values(job["outputs"]))
        out.append(Spacer(1, 6))

    if job.get("evidence"):
        rows = [[_p("Evidence", S_LABEL), _p("Description", S_LABEL), _p("Confidence", S_LABEL)]]
        for ev in job["evidence"]:
            rows.append([_p(ev.get("type") or "—"), _p(ev.get("description") or "—"), _p(ev.get("confidence") or "—")])
        out.append(_boxed(rows, [CONTENT_W * 0.24, CONTENT_W * 0.56, CONTENT_W * 0.2], zebra=True))
        out.append(Spacer(1, 6))

    for vis in job.get("visualizations", []):
        figure_no[0] += 1
        out += _figure(vis["image"], f"Figure {figure_no[0]} — {vis['caption']}")
    return out


def render_report(report: dict) -> bytes:
    """report: see report_service.build_report for the shape."""
    title = report["title"]
    generated: datetime = report["generated_at"]
    stamp = generated.strftime("%d %b %Y, %H:%M %Z").strip()

    story: list[Any] = [
        _header_band(report),
        Spacer(1, 12),
        _p("Satellite Analysis Report", S_TITLE),
        Spacer(1, 3),
        _p(title, S_KIND),
        Spacer(1, 10),
        _SectionHeading("Analysis Information"),
        Spacer(1, 6),
        _key_values(report["metadata"]),
        Spacer(1, 10),
    ]

    if report["queries"]:
        story += [*_section("Analysis Query", 6)]
        for query in report["queries"]:
            story += [_highlight([_p("User Query", S_LABEL), Spacer(1, 3), _p(f"“{query}”", S_QUOTE)]), Spacer(1, 6)]
        story.append(Spacer(1, 8))

    figure_no = [0]
    if report["input_images"]:
        heading = [_SectionHeading("Input Satellite Image" if len(report["input_images"]) == 1 else "Input Satellite Images"), Spacer(1, 8)]
        for item in report["input_images"]:
            if item.get("image"):
                figure_no[0] += 1
                story += _figure(item["image"], f"Figure {figure_no[0]} — {item['caption']}", heading)
            else:
                story.append(KeepTogether([*(heading or []), _p(f"{item['caption']}: {item['note']}", S_NOTE), Spacer(1, 8)]))
            heading = None  # only the first item carries the section title

    story += [*_section("Analysis Result", 8)]
    if report["jobs"]:
        for i, job in enumerate(report["jobs"], start=1):
            story += _job_block(job, i, len(report["jobs"]), figure_no)
            story.append(Spacer(1, 8))
    else:
        story += [_p("No analysis query has been submitted for this image yet.", S_NOTE), Spacer(1, 10)]

    summary = [(f"Input query{'' if len(report['jobs']) == 1 else f' {i}'}", job["query"], job.get("answer")) for i, job in enumerate(report["jobs"], start=1) if job.get("query")]
    if summary:
        story += [*_section("Analysis Summary", 6)]
        rows: list[tuple[str, Any]] = []
        for label, query, answer in summary:
            rows.append((label.capitalize(), query))
            rows.append(("Output", answer or "Result not available."))
        story += [_key_values(rows), Spacer(1, 14)]

    if report["processing"]:
        story += [*_section("Model & Processing Information", 6), _key_values(report["processing"]), Spacer(1, 10)]

    if report.get("notes"):
        for note in report["notes"]:
            story += [_p(note, S_NOTE), Spacer(1, 4)]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"SatQuery Analysis Report — {title}",
        author="SatQuery AI",
        subject="Satellite Intelligence & Analysis Report",
    )
    doc.build(story, canvasmaker=lambda *a, **kw: _NumberedCanvas(*a, title=title, stamp=stamp, **kw))
    return buf.getvalue()


class _NumberedCanvas(pdf_canvas.Canvas):
    """Draws the footer (and a slim running header after page 1) once the
    total page count is known, so every page can say "Page X of Y"."""

    def __init__(self, *args, title: str, stamp: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []
        self._title = title
        self._stamp = stamp

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int) -> None:
        page = self._pageNumber
        # Footer band
        self.setFillColor(FOOTER_BG)
        self.rect(0, 0, PAGE_W, 13 * mm, stroke=0, fill=1)
        self.setStrokeColor(SECTION_LINE)
        self.setLineWidth(0.6)
        self.line(0, 13 * mm, PAGE_W, 13 * mm)
        self.setFont("Helvetica", 7.8)
        self.setFillColor(MUTED)
        y = 5.2 * mm
        self.drawString(MARGIN_X, y, FOOTER_TEXT)
        self.drawCentredString(PAGE_W / 2, y, f"Generated {self._stamp}")
        self.drawRightString(PAGE_W - MARGIN_X, y, f"Page {page} of {total}")
        # Running header on continuation pages
        if page > 1:
            self.setFont("Helvetica-Bold", 8.5)
            self.setFillColor(NAVY)
            top = PAGE_H - 10 * mm
            self.drawString(MARGIN_X, top, "SatQuery")
            self.setFont("Helvetica", 8.5)
            self.setFillColor(MUTED)
            self.drawRightString(PAGE_W - MARGIN_X, top, f"Satellite Analysis Report — {self._title}"[:110])
            self.setStrokeColor(HEADER_LINE)
            self.line(MARGIN_X, top - 2.5 * mm, PAGE_W - MARGIN_X, top - 2.5 * mm)
