"""
report_pdf.py — the ONE PDF builder.

Imported by both app.py (sidebar download button) and send_report.py (daily
email), so the emailed PDF is byte-for-byte the same layout as the one you
download from the dashboard. Change the report here and both update together.
"""
import io
import os
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")


def pdf_safe(s):
    """reportlab core fonts are latin-1; swap symbols and drop the rest."""
    s = (str(s).replace("\u20b9", "Rs ").replace("\u25b2", "+")
         .replace("\u25bc", "-").replace("\u2013", "-").replace("\u00b7", "."))
    return s.encode("latin-1", "replace").decode("latin-1")


def pdf_markup(s):
    """Convert the dashboard's coloured HTML spans into reportlab markup, so up
    moves print green and down moves red. Hyperlinks are kept clickable."""
    s = str(s)
    s = s.replace("color:var(--pos)", "C_POS").replace("color:var(--neg)", "C_NEG")
    s = re.sub(r'<span[^>]*C_POS[^>]*>', '<font color="#0a8f3c">', s)
    s = re.sub(r'<span[^>]*C_NEG[^>]*>', '<font color="#c0392b">', s)
    s = re.sub(r'<span class="muted"[^>]*>', '<font color="#9aa0a6">', s)
    s = re.sub(r'<span[^>]*>', '<font>', s)
    s = s.replace("</span>", "</font>")
    s = s.replace("<small>", "").replace("</small>", "")
    s = s.replace("<br>", "<br/>")
    s = re.sub(r'<a\s+href="([^"]*)"[^>]*>', r'<a href="\1" color="blue">', s)
    return pdf_safe(s)


def build_pdf(report, meta, summary=None, chart_png=None, dashboard_url=None):
    """Build the daily report PDF.

    report        : [{"title": str, "tables": [{"headers": [...], "rows": [[...]]}]}]
    meta          : [str]  — lines under the title (timestamp, etc.)
    summary       : [str]  — "Biggest move" bullets
    chart_png     : BytesIO of the 5-year yield chart, or None
    dashboard_url : link printed in the header and footer, or None
    """
    bio = io.BytesIO()
    has_logo = os.path.exists(LOGO_PATH)

    def watermark(canvas, doc):
        if not has_logo:
            return
        try:
            canvas.saveState()
            pw, ph = A4
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(LOGO_PATH).getSize()
            scale = (pw * 0.5) / iw
            dw, dh = iw * scale, ih * scale
            canvas.setFillAlpha(0.06)
            canvas.drawImage(LOGO_PATH, (pw - dw) / 2, (ph - dh) / 2, dw, dh,
                             preserveAspectRatio=True, mask="auto")
            canvas.restoreState()
        except Exception:
            pass

    doc = SimpleDocTemplate(bio, pagesize=A4, topMargin=12 * mm,
                            bottomMargin=12 * mm, leftMargin=10 * mm,
                            rightMargin=10 * mm)
    ss = getSampleStyleSheet()
    cell_st = ParagraphStyle("c", fontName="Helvetica", fontSize=6.4, leading=7.4)
    head_st = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=6.4, leading=7.4)
    el = []

    if has_logo:
        try:
            el.append(Image(LOGO_PATH, width=120, height=26))
            el.append(Spacer(1, 4))
        except Exception:
            pass

    el.append(Paragraph("Daily Market Dashboard", ss["Title"]))
    for m in meta:
        el.append(Paragraph(pdf_safe(m), ss["Normal"]))
    if dashboard_url:
        el.append(Paragraph(
            f'<a href="{dashboard_url}" color="#1E2761"><u>{dashboard_url}</u></a>',
            ss["Normal"]))
    el.append(Spacer(1, 8))

    if summary:
        el.append(Paragraph("Today's summary", ss["Heading2"]))
        bullet_st = ParagraphStyle("b", fontName="Helvetica", fontSize=8.5,
                                   leading=12, leftIndent=8, spaceAfter=2)
        for s in summary:
            el.append(Paragraph("&bull;&nbsp; " + pdf_safe(s), bullet_st))
        el.append(Spacer(1, 10))

    def para(x, hdr=False):
        return Paragraph(pdf_markup(x).replace("\n", "<br/>"),
                         head_st if hdr else cell_st)

    for sec in report:
        el.append(Paragraph(pdf_safe(sec["title"]), ss["Heading2"]))
        for tbl in sec["tables"]:
            headers = tbl["headers"]
            ncol = max(1, len(headers))
            data = [[para(h, True) for h in headers]]
            data += [[para(x) for x in row] for row in tbl["rows"]]
            first = doc.width * (0.20 if ncol > 3 else 0.40)
            rest = (doc.width - first) / (ncol - 1) if ncol > 1 else doc.width
            widths = [first] + [rest] * (ncol - 1)
            t = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
            t.setStyle(TableStyle([
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#9db8ff")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#f3f4f6")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d7de")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            el.append(t)
            el.append(Spacer(1, 6))
        # the 5-year yield chart sits inside section 2
        if sec["title"].lstrip().startswith("2") and chart_png is not None:
            try:
                el.append(Spacer(1, 4))
                el.append(Image(chart_png, width=doc.width, height=doc.width * 0.42))
                el.append(Spacer(1, 6))
            except Exception:
                pass

    if dashboard_url:
        el.append(Spacer(1, 8))
        el.append(Paragraph(
            f'<a href="{dashboard_url}" color="blue"><u>Open live dashboard</u></a>',
            ParagraphStyle("ft", fontName="Helvetica", fontSize=7,
                           textColor=colors.grey)))

    doc.build(el, onFirstPage=watermark, onLaterPages=watermark)
    return bio.getvalue()
