"""Render a project markdown document to a styled PDF.

Usage:
    python -m scripts.make_pdf BTP_All_Phases_Work_Breakdown.md
    python -m scripts.make_pdf                 # rebuilds every doc in DOCS

Keeps the house style of the original PDFs: navy headings with rules, navy
table headers, shaded code blocks, tinted callout boxes, footer with page number.

Fonts: Arial (body) + Consolas (code). Both carry the rupee sign (U+20B9),
arrows and +/- , which the built-in Type1 Helvetica does not — the document is
full of INR amounts, so this matters. Emoji have no glyph in either face and are
mapped to text markers ([OK], [!], [X]) rather than rendered as blank boxes.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]

DOCS = [
    "BTP_All_Phases_Work_Breakdown.md",
    "TECHNICAL_REVIEW_AND_VERDICT.md",
]

# ---------------------------------------------------------------- palette ---
NAVY = colors.HexColor("#1F3864")
NAVY_MID = colors.HexColor("#2E5C8A")
INK = colors.HexColor("#1A1A1A")
MUTED = colors.HexColor("#6B7280")
CODE_BG = colors.HexColor("#F4F5F7")
CODE_BORDER = colors.HexColor("#DDE2E8")
QUOTE_BG = colors.HexColor("#E8F0FA")
ROW_ALT = colors.HexColor("#F7F9FC")
GRID = colors.HexColor("#C9D3E0")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

BODY_FONT, BODY_BOLD, BODY_ITAL, BODY_BI = "Body", "Body-Bold", "Body-Ital", "Body-BoldItal"
MONO, MONO_BOLD = "Mono", "Mono-Bold"


def register_fonts() -> None:
    win = Path("C:/Windows/Fonts")
    faces = {
        BODY_FONT: "arial.ttf", BODY_BOLD: "arialbd.ttf",
        BODY_ITAL: "ariali.ttf", BODY_BI: "arialbi.ttf",
        MONO: "consola.ttf", MONO_BOLD: "consolab.ttf",
    }
    for name, filename in faces.items():
        pdfmetrics.registerFont(TTFont(name, str(win / filename)))
    pdfmetrics.registerFontFamily(
        BODY_FONT, normal=BODY_FONT, bold=BODY_BOLD, italic=BODY_ITAL, boldItalic=BODY_BI
    )


# ------------------------------------------------------------ text hygiene ---
# Emoji and symbols with no glyph in Arial/Consolas. Rendered as markers so the
# meaning survives; anything unmapped is stripped by _strip_unsupported.
GLYPH_MAP = {
    "\u2705": "[OK]",       # white heavy check mark
    "\u274c": "[X]",        # cross mark
    "\u26a0": "[!]",        # warning sign
    "\U0001f1ee\U0001f1f3": "[IN]",   # flag: India
    "\u2713": "v", "\u2717": "x",
    "\u2190": "<-", "\u2192": "->",   # Arial has these, but keep ASCII in code
    "\ufe0f": "", "\ufe0e": "",       # variation selectors
}
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\u2b00-\u2bff]+"
)

_supported: set[str] | None = None


def _load_supported() -> set[str]:
    global _supported
    if _supported is None:
        from fontTools.ttLib import TTFont as FTFont
        cmap = FTFont("C:/Windows/Fonts/arial.ttf", fontNumber=0).getBestCmap()
        _supported = {chr(c) for c in cmap}
    return _supported


def clean_text(text: str) -> str:
    """Map known emoji to markers, drop anything the font cannot draw."""
    for src, dst in GLYPH_MAP.items():
        if src not in ("\u2190", "\u2192"):      # those two do have glyphs
            text = text.replace(src, dst)
    text = _EMOJI_RE.sub("", text)
    ok = _load_supported()
    return "".join(ch for ch in text if ch in ok or ch in "\n\t")


# --------------------------------------------------------------- inline md ---
_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_SENTINEL = "\x00%d\x00"


def inline(md: str) -> str:
    """Markdown inline syntax -> reportlab mini-HTML.

    Code spans are swapped for sentinels rather than rendered in place. Emphasis
    frequently wraps a code span — **NSE (`.NS`) primary** is all over these
    documents — and rendering code first would leave the ** markers stranded in
    different segments where the bold regex can never pair them up.
    """
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(m.group(1))
        return _SENTINEL % (len(spans) - 1)

    seg = _CODE_SPAN.sub(stash, md)
    seg = _esc(seg)
    seg = _LINK.sub(r'<link href="\2" color="#2E5C8A"><u>\1</u></link>', seg)
    seg = _BOLD.sub(r"<b>\1</b>", seg)
    seg = _ITAL.sub(r"<i>\1</i>", seg)

    for i, code in enumerate(spans):
        seg = seg.replace(
            _SENTINEL % i,
            f'<font face="{MONO}" size="8.4" color="#12355B">{_esc(code)}</font>',
        )
    return seg


def plain(md: str) -> str:
    """Markdown stripped to bare text — used for measuring column widths."""
    s = _LINK.sub(r"\1", md)
    return s.replace("**", "").replace("*", "").replace("`", "")


# ----------------------------------------------------------------- styles ---
def build_styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName=BODY_FONT, alignment=TA_LEFT)
    return {
        "h1": ParagraphStyle("h1", **base, fontSize=19, leading=24, spaceBefore=16,
                             spaceAfter=4, textColor=NAVY),
        "h2": ParagraphStyle("h2", **base, fontSize=14.5, leading=19, spaceBefore=15,
                             spaceAfter=4, textColor=NAVY),
        "h3": ParagraphStyle("h3", **base, fontSize=11.5, leading=15, spaceBefore=12,
                             spaceAfter=3, textColor=NAVY_MID),
        "h4": ParagraphStyle("h4", **base, fontSize=10, leading=13, spaceBefore=9,
                             spaceAfter=2, textColor=NAVY_MID),
        "body": ParagraphStyle("body", **base, fontSize=9.2, leading=13.4, spaceAfter=5,
                               textColor=INK),
        "bullet": ParagraphStyle("bullet", **base, fontSize=9.2, leading=13.4,
                                 leftIndent=13, bulletIndent=3, spaceAfter=2.5,
                                 textColor=INK),
        "quote": ParagraphStyle("quote", **base, fontSize=9.2, leading=13.4, spaceAfter=3,
                                textColor=INK),
        "quoteh": ParagraphStyle("quoteh", **base, fontSize=10.4, leading=14,
                                 spaceAfter=3, textColor=NAVY),
        "cell": ParagraphStyle("cell", **base, fontSize=8.2, leading=11, textColor=INK),
        "cellh": ParagraphStyle("cellh", fontName=BODY_BOLD, fontSize=8.4, leading=11.5,
                                textColor=colors.white, alignment=TA_LEFT),
        "code": ParagraphStyle("code", fontName=MONO, fontSize=7.9, leading=10.6,
                               textColor=colors.HexColor("#12355B")),
    }


# ---------------------------------------------------------------- parsing ---
_TABLE_SEP = re.compile(r"^\|[\s:\-\|]+\|?\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")


_BLOCK_START = re.compile(r"^\s*(#|>|\||```|---|___|\*\*\*\s*$|[-*+]\s|\d+\.\s)")


def join_continuation(lines: list[str], i: int, n: int, first: str) -> tuple[str, int]:
    """Fold soft-wrapped continuation lines into `first`.

    Returns the joined text and the index of the next unconsumed line. Used for
    both paragraphs and list items so a wrapped bullet keeps its indent.
    """
    buf = [first]
    while i < n and lines[i].strip() and not _BLOCK_START.match(lines[i]):
        buf.append(lines[i].strip())
        i += 1
    return " ".join(buf), i


def wrap_code(line: str, limit: int = 100) -> list[str]:
    """Hard-wrap over-long code lines; Preformatted will not wrap them itself."""
    if len(line) <= limit:
        return [line]
    out, indent = [], len(line) - len(line.lstrip())
    pad = " " * (indent + 4)
    while len(line) > limit:
        cut = line.rfind(" ", 0, limit)
        if cut <= indent:
            cut = limit
        out.append(line[:cut])
        line = pad + line[cut:].lstrip()
    out.append(line)
    return out


def code_block(lines: list[str], st) -> Table:
    text = "\n".join(w for line in lines for w in wrap_code(line.rstrip()))
    inner = Preformatted(text, st["code"])
    t = Table([[inner]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, CODE_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def quote_block(lines: list[str], st) -> Table:
    flow = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            flow.append(Paragraph(f"<b>{inline(line)}</b>", st["quoteh"]))
        else:
            m = _BULLET.match(line)
            if m:
                flow.append(Paragraph(inline(m.group(2)), st["bullet"], bulletText="\u2022"))
            else:
                flow.append(Paragraph(inline(line), st["quote"]))
    t = Table([[flow]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), QUOTE_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 3, NAVY_MID),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def md_table(rows: list[str], st) -> Table:
    def split(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = split(rows[0])
    body = [split(r) for r in rows[2:] if r.strip()]
    ncols = len(header)
    body = [r + [""] * (ncols - len(r)) if len(r) < ncols else r[:ncols] for r in body]

    # Width by longest cell, so narrow label columns stay narrow. Measured on
    # stripped text — otherwise "**1**" counts as 5 chars — and floored well
    # above the header word length so a heading never wraps mid-word.
    weights = []
    for c in range(ncols):
        cells = [plain(header[c])] + [plain(r[c]) for r in body]
        longest = max((len(x) for x in cells), default=1)
        floor = max(10, len(plain(header[c])) + 3)
        weights.append(max(floor, min(longest, 60)))
    total = sum(weights)
    widths = [CONTENT_W * w / total for w in weights]

    data = [[Paragraph(inline(c), st["cellh"]) for c in header]]
    data += [[Paragraph(inline(c), st["cell"]) for c in r] for r in body]

    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


def parse(md: str, st) -> list:
    lines = clean_text(md).splitlines()
    flow: list = []
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # fenced code
        if stripped.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            flow.append(code_block(buf, st))
            flow.append(Spacer(1, 6))
            continue

        # blockquote / callout
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            flow.append(quote_block(buf, st))
            flow.append(Spacer(1, 7))
            continue

        # table
        if stripped.startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1].strip()):
            buf = []
            while i < n and lines[i].strip().startswith("|"):
                buf.append(lines[i])
                i += 1
            flow.append(md_table(buf, st))
            flow.append(Spacer(1, 8))
            continue

        # horizontal rule
        if stripped in ("---", "***", "___"):
            flow.append(Spacer(1, 5))
            flow.append(HRFlowable(width="100%", thickness=0.7, color=GRID,
                                   spaceBefore=2, spaceAfter=8))
            i += 1
            continue

        # headings
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped.lstrip("#").strip()
            key = f"h{min(level, 4)}"
            para = Paragraph(f"<b>{inline(text)}</b>", st[key])
            if level <= 2:
                rule = HRFlowable(width="100%", thickness=1.4 if level == 1 else 0.9,
                                  color=NAVY, spaceBefore=3, spaceAfter=7)
                flow.append(KeepTogether([para, rule]))
            else:
                flow.append(para)
            i += 1
            continue

        # lists \u2014 a wrapped list item must stay inside its bullet, not fall out
        # as a fresh left-aligned paragraph on the following line
        m = _BULLET.match(line)
        if m:
            indent = len(m.group(1))
            text, i = join_continuation(lines, i + 1, n, m.group(2))
            style = ParagraphStyle(f"b{indent}", parent=st["bullet"],
                                   leftIndent=13 + indent * 8,
                                   bulletIndent=3 + indent * 8)
            flow.append(Paragraph(inline(text), style,
                                  bulletText="\u2022" if indent == 0 else "\u25e6"))
            continue

        m = _ORDERED.match(line)
        if m:
            indent = len(m.group(1))
            text, i = join_continuation(lines, i + 1, n, m.group(3))
            style = ParagraphStyle(f"o{indent}", parent=st["bullet"],
                                   leftIndent=16 + indent * 8,
                                   bulletIndent=3 + indent * 8)
            flow.append(Paragraph(inline(text), style, bulletText=f"{m.group(2)}."))
            continue

        # paragraph — join continuation lines
        text, i = join_continuation(lines, i + 1, n, stripped)
        buf = [text]
        flow.append(Paragraph(inline(" ".join(buf)), st["body"]))

    return flow


# ------------------------------------------------------------ page furniture ---
def make_footer(title: str):
    def footer(canvas, doc):
        canvas.saveState()
        y = MARGIN - 6 * mm
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, y + 4 * mm, PAGE_W - MARGIN, y + 4 * mm)
        canvas.setFont(BODY_FONT, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, y, title)
        canvas.drawRightString(PAGE_W - MARGIN, y, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()
    return footer


def render(md_path: Path) -> Path:
    pdf_path = md_path.with_suffix(".pdf")
    # Build to a temp file and swap: a PDF open in a viewer holds a lock on
    # Windows, and a direct write would truncate the old file before failing.
    tmp_path = pdf_path.with_suffix(".pdf.tmp")
    title = md_path.stem.replace("_", " ")
    st = build_styles()
    flow = parse(md_path.read_text(encoding="utf-8"), st)

    doc = BaseDocTemplate(
        str(tmp_path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 4 * mm,
        title=title, author="BTP", subject="B.Tech Capstone Project",
    )
    frame = Frame(MARGIN, MARGIN + 4 * mm, CONTENT_W,
                  PAGE_H - MARGIN - (MARGIN + 4 * mm), id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                       onPage=make_footer(title))])
    doc.build(flow)

    try:
        os.replace(tmp_path, pdf_path)
    except PermissionError:
        raise PermissionError(
            f"{pdf_path.name} is locked (open in a PDF viewer?). "
            f"Close it and re-run; the new file is waiting at {tmp_path.name}."
        ) from None
    return pdf_path


def main(argv: list[str]) -> int:
    register_fonts()
    targets = [Path(a) for a in argv[1:]] or [ROOT / d for d in DOCS]
    failed = False
    for md in targets:
        md = md if md.is_absolute() else ROOT / md
        if not md.exists():
            print(f"SKIP  {md} (not found)")
            continue
        try:
            out = render(md)
        except PermissionError as e:
            print(f"LOCK  {e}")
            failed = True
            continue
        print(f"OK    {out.name}  ({out.stat().st_size / 1024:.0f} KB)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
