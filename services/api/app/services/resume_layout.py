"""Read a resume as styled visual lines.

The parser works from lines that keep their typography (font, size, bold,
italic), position (indent, right-aligned text on the same row), bullets, and
heading rules. That is what lets ApplyPilot rebuild a tailored resume in the
original layout instead of a generic template.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

BULLET_GLYPHS = {"●", "•", "▪", "◦", "·", "‣", "⁃", "∙", "■", "□", "○", "➢", "➤", "►", "▶", "✓", "✔", "-", "–", "*", "o", "", "§"}
_BULLET_PREFIX = re.compile(r"^\s*([●•▪◦·‣⁃∙■□○➢➤►▶✓✔\-–*§])\s+")


@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    size: float = 10.0
    font: str = ""


@dataclass
class Line:
    text: str
    spans: list[Span] = field(default_factory=list)
    right: str = ""
    right_spans: list[Span] = field(default_factory=list)
    x0: float = 0.0
    x1: float = 0.0
    text_x: float = 0.0
    y: float = 0.0
    height: float = 0.0
    page: int = 0
    size: float = 10.0
    bold: bool = False
    italic: bool = False
    bullet: bool = False
    bullet_glyph: str | None = None
    bullet_x: float | None = None
    bullet_size: float | None = None
    align: str = "left"
    rule_below: bool = False
    style_name: str = ""
    source: str = "text"

    @property
    def caps(self) -> bool:
        letters = [char for char in self.text if char.isalpha()]
        return bool(letters) and sum(char.isupper() for char in letters) / len(letters) > 0.85

    def to_dict(self) -> dict:
        data = asdict(self)
        data["caps"] = self.caps
        return data


@dataclass
class LayoutResult:
    lines: list[Line]
    style: dict
    pages: int = 1
    fmt: str = "text"


def _majority(spans: list[Span], attr: str) -> bool:
    total = sum(len(span.text.strip()) for span in spans) or 1
    return sum(len(span.text.strip()) for span in spans if getattr(span, attr)) / total > 0.6


def _main_size(spans: list[Span]) -> float:
    counts: Counter[float] = Counter()
    for span in spans:
        counts[round(span.size * 2) / 2] += len(span.text.strip())
    return counts.most_common(1)[0][0] if counts else 10.0


def _font_family(name: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", name or "")
    name = re.split(r"[-,]", name)[0]
    name = re.sub(r"(MT|PS|PSMT|Std|Pro)$", "", name)
    return name.strip() or "Helvetica"


def _merge_spans(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for span in spans:
        if merged and merged[-1].bold == span.bold and merged[-1].italic == span.italic:
            merged[-1].text += span.text
        else:
            merged.append(Span(span.text, span.bold, span.italic, span.size, span.font))
    return merged


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def read_pdf(path: Path) -> LayoutResult:
    import pymupdf

    document = pymupdf.open(str(path))
    raw_rows = []
    fonts: Counter[str] = Counter()
    page_width = 612.0
    page_height = 792.0
    rules: list[tuple[int, float, float, float]] = []
    for page_index, page in enumerate(document):
        page_width, page_height = page.rect.width, page.rect.height
        for drawing in page.get_drawings():
            rect = drawing.get("rect")
            if rect is not None and rect.height <= 2.5 and rect.width >= page_width * 0.4:
                rules.append((page_index, rect.y0, rect.x0, rect.x1))
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                spans = []
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if not text:
                        continue
                    flags = span.get("flags", 0)
                    font = span.get("font", "")
                    bold = bool(flags & 16) or bool(re.search(r"bold|black|heavy|semibold|demi", font, re.I))
                    italic = bool(flags & 2) or bool(re.search(r"italic|oblique", font, re.I))
                    spans.append({"text": text, "bold": bold, "italic": italic, "size": span.get("size", 10.0), "font": font, "bbox": span.get("bbox")})
                    if text.strip():
                        fonts[_font_family(font)] += len(text.strip())
                if not spans or not "".join(item["text"] for item in spans).strip():
                    continue
                x0, y0, x1, y1 = line["bbox"]
                raw_rows.append({"page": page_index, "x0": x0, "x1": x1, "y0": y0, "y1": y1, "spans": spans})
    pages = len(document)
    document.close()

    # Group fragments that share a baseline into one visual row.
    raw_rows.sort(key=lambda row: (row["page"], round((row["y0"] + row["y1"]) / 2, 1), row["x0"]))
    rows: list[list[dict]] = []
    for row in raw_rows:
        center = (row["y0"] + row["y1"]) / 2
        if rows:
            last = rows[-1]
            last_center = sum((item["y0"] + item["y1"]) / 2 for item in last) / len(last)
            height = max(item["y1"] - item["y0"] for item in last)
            if last[0]["page"] == row["page"] and abs(center - last_center) < max(2.5, height * 0.45):
                last.append(row)
                continue
        rows.append([row])

    body_x0 = Counter(round(item["x0"]) for row in rows for item in row)
    left_margin = min((x for x, count in body_x0.items() if count >= 2), default=36)
    right_edge = max((item["x1"] for row in rows for item in row), default=page_width - 36)
    if rules:
        # Heading rules span the text block exactly, which is a better right edge than ragged text.
        right_edge = max(rx1 for _page, _y, _rx0, rx1 in rules)

    lines: list[Line] = []
    for row in rows:
        row.sort(key=lambda item: item["x0"])
        bullet_glyph = None
        bullet_x = None
        bullet_size = None
        first_text = "".join(span["text"] for span in row[0]["spans"]).strip()
        segments = row
        if first_text in BULLET_GLYPHS and len(row) > 1:
            bullet_glyph = first_text
            bullet_x = row[0]["x0"]
            bullet_size = row[0]["spans"][0]["size"]
            segments = row[1:]
        elif len(first_text) > 1 and first_text[0] in BULLET_GLYPHS - {"-", "*", "o", "–"} and first_text[1] == " ":
            bullet_glyph = first_text[0]
            bullet_x = row[0]["x0"]
            bullet_size = row[0]["spans"][0]["size"]
        left = segments
        right = []
        if len(segments) > 1:
            last = segments[-1]
            gap = last["x0"] - segments[-2]["x1"]
            if last["x1"] >= right_edge - 25 and gap > 25:
                left, right = segments[:-1], [last]
        spans = _merge_spans([Span(s["text"], s["bold"], s["italic"], s["size"], s["font"]) for item in left for s in item["spans"]])
        right_spans = _merge_spans([Span(s["text"], s["bold"], s["italic"], s["size"], s["font"]) for item in right for s in item["spans"]])
        text = re.sub(r"\s+", " ", "".join(span.text for span in spans)).strip()
        if bullet_glyph and text.startswith(bullet_glyph):
            text = text[len(bullet_glyph):].strip()
            if spans:
                spans[0].text = spans[0].text.lstrip()[len(bullet_glyph):].lstrip()
        x0 = min(item["x0"] for item in row)
        x1 = max(item["x1"] for item in row)
        y0 = min(item["y0"] for item in row)
        y1 = max(item["y1"] for item in row)
        width = x1 - x0
        center = (x0 + x1) / 2
        align = "center" if abs(center - page_width / 2) < 18 and width < (right_edge - left_margin) * 0.85 and x0 > left_margin + 20 else "left"
        page_index = row[0]["page"]
        rule_below = any(page == page_index and y1 - 1 <= ry <= y1 + 9 and rx0 <= x0 + 5 for page, ry, rx0, _ in rules)
        lines.append(
            Line(
                text=text,
                spans=spans,
                right=re.sub(r"\s+", " ", "".join(span.text for span in right_spans)).strip(),
                right_spans=right_spans,
                x0=x0,
                x1=x1,
                text_x=left[0]["x0"] if left else x0,
                y=y0,
                height=y1 - y0,
                page=page_index,
                size=_main_size(spans) if spans else 10.0,
                bold=_majority(spans, "bold") if spans else False,
                italic=_majority(spans, "italic") if spans else False,
                bullet=bullet_glyph is not None,
                bullet_glyph=bullet_glyph,
                bullet_x=bullet_x,
                bullet_size=bullet_size,
                align=align,
                rule_below=rule_below,
                source="pdf",
            )
        )
    # When the bullet glyph is inline ("● Text"), the text itself starts further right than the row.
    # Wrapped lines of that bullet start where the text starts, which is how they are recognized.
    for index, line in enumerate(lines):
        if line.bullet and line.bullet_x is not None and abs(line.text_x - line.bullet_x) < 1:
            follower = next((row for row in lines[index + 1 : index + 3] if not row.bullet and row.page == line.page), None)
            if follower is not None and line.bullet_x + 6 < follower.text_x < line.bullet_x + 40:
                line.text_x = follower.text_x
            else:
                line.text_x = line.bullet_x + line.size * 1.6
    style = _style_from_lines(lines, fonts, page_width=page_width, page_height=page_height, left_margin=left_margin, right_edge=right_edge, pages=pages)
    style["has_rules"] = bool(rules)
    return LayoutResult(lines=lines, style=style, pages=pages, fmt="pdf")


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def read_docx(path: Path) -> LayoutResult:
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(str(path))
    lines: list[Line] = []
    fonts: Counter[str] = Counter()
    default_size = 11.0
    try:
        normal = document.styles["Normal"]
        if normal.font.size:
            default_size = normal.font.size.pt
        if normal.font.name:
            fonts[normal.font.name] += 1
    except KeyError:
        pass

    def paragraph_line(paragraph, index: int, right_text: str = "", right_runs=None) -> Line | None:
        text = paragraph.text
        if not text.strip() and not right_text:
            return None
        spans = []
        for run in paragraph.runs:
            if not run.text:
                continue
            size = run.font.size.pt if run.font.size else (paragraph.style.font.size.pt if paragraph.style is not None and paragraph.style.font.size else default_size)
            bold = bool(run.bold) if run.bold is not None else bool(paragraph.style is not None and paragraph.style.font.bold)
            italic = bool(run.italic) if run.italic is not None else bool(paragraph.style is not None and paragraph.style.font.italic)
            name = run.font.name or (paragraph.style.font.name if paragraph.style is not None else "") or ""
            if name:
                fonts[name] += len(run.text.strip())
            spans.append(Span(run.text, bold, italic, size, name))
        style_name = paragraph.style.name if paragraph.style is not None else ""
        ppr = paragraph._p.pPr
        numbered = ppr is not None and ppr.find(qn("w:numPr")) is not None
        bordered = False
        if ppr is not None:
            border = ppr.find(qn("w:pBdr"))
            bordered = border is not None and border.find(qn("w:bottom")) is not None
        is_bullet = numbered or "List" in style_name or "Bullet" in style_name
        glyph = "•" if is_bullet else None
        match = _BULLET_PREFIX.match(text)
        if match:
            is_bullet, glyph = True, match.group(1)
            text = text[match.end():]
            if spans:
                spans[0].text = _BULLET_PREFIX.sub("", spans[0].text, count=1)
        left, right = text, right_text
        if "\t" in text and not right_text:
            parts = [part for part in text.split("\t") if part.strip()]
            if len(parts) >= 2:
                left, right = " ".join(parts[:-1]), parts[-1]
                spans = _split_spans_at(spans, left)
        alignment = paragraph.alignment
        align = "center" if alignment is not None and int(alignment) == 1 else ("right" if alignment is not None and int(alignment) == 2 else "left")
        spans = _merge_spans(spans) or [Span(left)]
        return Line(
            text=re.sub(r"\s+", " ", left).strip(),
            spans=spans,
            right=re.sub(r"\s+", " ", right or "").strip(),
            right_spans=right_runs or ([Span(right)] if right else []),
            y=float(index),
            size=_main_size(spans),
            bold=_majority(spans, "bold"),
            italic=_majority(spans, "italic"),
            bullet=is_bullet,
            bullet_glyph=glyph,
            align=align,
            rule_below=bordered,
            style_name=style_name,
            source="docx",
        )

    index = 0
    body = document.element.body
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            line = paragraph_line(Paragraph(child, document), index)
            if line:
                if line.style_name.lower().startswith("heading") or line.style_name.lower() == "title":
                    line.bold = True
                lines.append(line)
            index += 1
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    if not cells or cell._tc is not cells[-1]._tc:
                        cells.append(cell)
                if len(cells) >= 2 and len(cells[-1].paragraphs) <= 3:
                    left_pars = [p for p in cells[0].paragraphs if p.text.strip()]
                    right_pars = [p for p in cells[-1].paragraphs if p.text.strip()]
                    for position, paragraph in enumerate(left_pars):
                        right_text = right_pars[position].text if position < len(right_pars) else ""
                        line = paragraph_line(paragraph, index, right_text=right_text)
                        if line:
                            lines.append(line)
                        index += 1
                else:
                    for cell in cells:
                        for paragraph in cell.paragraphs:
                            line = paragraph_line(paragraph, index)
                            if line:
                                lines.append(line)
                            index += 1
    section = document.sections[0] if document.sections else None
    style = _style_from_lines(
        lines,
        fonts,
        page_width=section.page_width.pt if section and section.page_width else 612,
        page_height=section.page_height.pt if section and section.page_height else 792,
        left_margin=section.left_margin.pt if section and section.left_margin else 54,
        right_edge=(section.page_width.pt - section.right_margin.pt) if section and section.page_width and section.right_margin else 558,
        pages=1,
    )
    if section is not None and section.top_margin:
        style["page"]["margin_top"] = round(section.top_margin.pt, 1)
    if section is not None and section.bottom_margin:
        style["page"]["margin_bottom"] = round(section.bottom_margin.pt, 1)
    return LayoutResult(lines=lines, style=style, pages=1, fmt="docx")


def _split_spans_at(spans: list[Span], left_text: str) -> list[Span]:
    """Keep only the spans that make up `left_text` (text before the tab)."""
    remaining = len(left_text)
    kept: list[Span] = []
    for span in spans:
        if remaining <= 0:
            break
        piece = span.text.replace("\t", " ")
        kept.append(Span(piece[:remaining], span.bold, span.italic, span.size, span.font))
        remaining -= len(piece)
    return kept


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

_RIGHT_GAP = re.compile(r"^(.*?\S)\s{3,}(\S.*)$")


def read_text(text: str) -> LayoutResult:
    lines: list[Line] = []
    for index, raw in enumerate(text.splitlines()):
        if not raw.strip():
            continue
        match = _BULLET_PREFIX.match(raw)
        bullet = bool(match)
        glyph = match.group(1) if match else None
        body = raw[match.end():] if match else raw.strip()
        right = ""
        if "\t" in body:
            parts = [part for part in body.split("\t") if part.strip()]
            if len(parts) >= 2:
                body, right = " ".join(parts[:-1]), parts[-1]
        else:
            gap = _RIGHT_GAP.match(body)
            if gap and not bullet:
                body, right = gap.group(1), gap.group(2)
        body = re.sub(r"\s+", " ", body).strip()
        lines.append(Line(text=body, spans=[Span(body)], right=right.strip(), y=float(index), bullet=bullet, bullet_glyph=glyph, source="text"))
    style = default_style()
    return LayoutResult(lines=lines, style=style, pages=1, fmt="text")


# ---------------------------------------------------------------------------
# Style profile
# ---------------------------------------------------------------------------


def default_style() -> dict:
    return {
        "font_family": "Carlito",
        "original_font": None,
        "page": {"width": 612, "height": 792, "margin_left": 40, "margin_right": 40, "margin_top": 30, "margin_bottom": 30},
        "name": {"size": 20, "bold": True, "align": "center", "caps": False},
        "contact": {"size": 9.5, "align": "center", "separator": " | "},
        "heading": {"size": 11, "bold": True, "caps": True, "rule": True, "space_before": 6, "space_after": 3},
        "entry_title": {"size": 10.5, "bold": True},
        "entry_right": {"size": 10, "italic": True, "bold": False},
        "subtitle": {"size": 10, "italic": True},
        "body": {"size": 10, "leading": 12.2},
        "bullet": {"glyph": "●", "size": 8, "indent": 7, "text_indent": 20},
        "tech": {"size": 9.5, "italic": True},
        "skills": {"label_bold": True},
        "pages": 1,
        "inline_bold": True,
    }


def _style_from_lines(lines: list[Line], fonts: Counter, *, page_width: float, page_height: float, left_margin: float, right_edge: float, pages: int) -> dict:
    style = default_style()
    original = fonts.most_common(1)[0][0] if fonts else None
    style["original_font"] = original
    style["font_family"] = map_font(original)
    style["pages"] = pages
    style["page"].update(
        width=round(page_width, 1),
        height=round(page_height, 1),
        margin_left=round(max(18.0, left_margin), 1),
        margin_right=round(max(18.0, page_width - right_edge), 1),
    )
    if lines:
        style["page"]["margin_top"] = round(max(14.0, min(line.y for line in lines if line.page == 0) - 4), 1) if lines[0].source == "pdf" else style["page"]["margin_top"]
    body_sizes = Counter(round(line.size * 2) / 2 for line in lines if not line.bold and len(line.text) > 25)
    if body_sizes:
        style["body"]["size"] = body_sizes.most_common(1)[0][0]
    if lines:
        biggest = max(lines[:4], key=lambda line: line.size)
        style["name"]["size"] = biggest.size
        style["name"]["align"] = biggest.align
        style["name"]["bold"] = biggest.bold
        style["name"]["caps"] = biggest.caps
    bullets = [line for line in lines if line.bullet]
    if bullets:
        glyphs = Counter(line.bullet_glyph for line in bullets if line.bullet_glyph)
        style["bullet"]["glyph"] = glyphs.most_common(1)[0][0] if glyphs else "•"
        if bullets[0].source == "pdf":
            xs = Counter(round(line.bullet_x - left_margin, 1) for line in bullets if line.bullet_x is not None)
            text_xs = Counter(round(line.text_x - left_margin, 1) for line in bullets)
            if xs:
                style["bullet"]["indent"] = max(0.0, xs.most_common(1)[0][0])
            if text_xs:
                style["bullet"]["text_indent"] = max(8.0, text_xs.most_common(1)[0][0])
            sizes = [line.bullet_size for line in bullets if line.bullet_size]
            if sizes:
                style["bullet"]["size"] = Counter(sizes).most_common(1)[0][0]
    # Line spacing from consecutive body rows on the same page.
    gaps = []
    for previous, current in zip(lines, lines[1:]):
        if previous.source != "pdf" or previous.page != current.page:
            continue
        gap = current.y - previous.y
        if 8 < gap < 20 and not previous.bold and not current.bold:
            gaps.append(round(gap, 1))
    if gaps:
        style["body"]["leading"] = Counter(gaps).most_common(1)[0][0]
    return style


FONT_FILES = {
    "Carlito": "Carlito",
    "Calibri": "Carlito",
    "Lato": "Lato",
    "Tinos": "Tinos",
    "Times": "Tinos",
    "TimesNewRoman": "Tinos",
    "Times New Roman": "Tinos",
    "Georgia": "Tinos",
    "Garamond": "Tinos",
    "CMU Serif": "Tinos",
    "CMUSerif": "Tinos",
    "LMRoman10": "Tinos",
    "SFRM1000": "Tinos",
    "Cambria": "Tinos",
    "Book Antiqua": "Tinos",
    "Palatino": "Tinos",
}


def map_font(name: str | None) -> str:
    """Pick a bundled font that matches (or is metric-compatible with) the original."""
    if not name:
        return "Carlito"
    clean = _font_family(name)
    for key, value in FONT_FILES.items():
        if clean.lower().replace(" ", "") == key.lower().replace(" ", ""):
            return value
    lowered = clean.lower()
    if any(word in lowered for word in ("times", "serif", "roman", "georgia", "garamond", "cambria", "palatino", "minion", "baskerville")) and "sans" not in lowered:
        return "Tinos"
    if any(word in lowered for word in ("arial", "helvetica", "liberation", "roboto", "opensans", "open sans", "inter", "sourcesans", "source sans", "nunito", "montserrat", "poppins", "segoe", "verdana", "tahoma")):
        return "Helvetica"
    return "Carlito"


def read_layout(path: Path, content_type: str = "") -> LayoutResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf" or "pdf" in content_type:
        return read_pdf(path)
    if suffix == ".docx" or "wordprocessingml" in content_type:
        if not zipfile.is_zipfile(path):
            raise ValueError("The DOCX file is not a valid document.")
        return read_docx(path)
    return read_text(path.read_text(errors="replace"))
