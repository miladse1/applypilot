"""Render a resume document model in the typography and layout of the original.

The style profile comes from the uploaded file (font family, sizes, margins,
heading rules, bullet glyph and indents, right-aligned dates). PDF output uses
the bundled metric-compatible fonts; DOCX output mirrors the same structure with
tab stops, paragraph borders, and hanging indents so it stays editable in Word.
"""

from __future__ import annotations

import copy
import io
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle

from app.services.resume_layout import default_style

FONT_DIR = Path(__file__).resolve().parents[1] / "data" / "fonts"
_REGISTERED: set[str] = set()
DOCX_FONT_NAMES = {"Carlito": "Calibri", "Lato": "Lato", "Tinos": "Times New Roman", "Helvetica": "Arial"}


def _register(family: str) -> dict[str, str]:
    if family == "Helvetica" or not (FONT_DIR / f"{family}-Regular.ttf").exists():
        return {"normal": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique", "bolditalic": "Helvetica-BoldOblique"}
    names = {"normal": family, "bold": f"{family}-Bold", "italic": f"{family}-Italic", "bolditalic": f"{family}-BoldItalic"}
    if family not in _REGISTERED:
        files = {"normal": "Regular", "bold": "Bold", "italic": "Italic", "bolditalic": "BoldItalic"}
        for key, suffix in files.items():
            pdfmetrics.registerFont(TTFont(names[key], str(FONT_DIR / f"{family}-{suffix}.ttf")))
        pdfmetrics.registerFontFamily(family, normal=names["normal"], bold=names["bold"], italic=names["italic"], boldItalic=names["bolditalic"])
        _REGISTERED.add(family)
    return names


def markup_to_xml(text: str) -> str:
    """`**bold**` markup to reportlab paragraph XML, escaping everything else."""
    parts = re.split(r"(\*\*.+?\*\*)", text or "")
    out = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(f"<b>{escape(part[2:-2])}</b>")
        else:
            out.append(escape(part.replace("**", "")))
    return "".join(out)


class _Rule(Flowable):
    def __init__(self, width: float, thickness: float = 0.6, space_before: float = 1.0, space_after: float = 3.0):
        super().__init__()
        self.width = width
        self.thickness = thickness
        self.space_before = space_before
        self.space_after = space_after

    def wrap(self, available_width, available_height):
        return self.width, self.thickness + self.space_before + self.space_after

    def draw(self):
        self.canv.setStrokeColor(black)
        self.canv.setLineWidth(self.thickness)
        y = self.space_after
        self.canv.line(0, y, self.width, y)


def _contact_items(document: dict, contact_overrides: dict | None) -> list[str]:
    items = list((document.get("header") or {}).get("contact_items") or [])
    overrides = contact_overrides or {}
    result = []
    for item in items:
        lowered = item.lower()
        if re.search(r"\[(?:add|insert|your)[^\]]*\]", item, re.I):
            if "linkedin" in lowered and overrides.get("linkedin_url"):
                result.append(overrides["linkedin_url"])
            elif "github" in lowered and overrides.get("github_url"):
                result.append(overrides["github_url"])
            elif ("portfolio" in lowered or "website" in lowered) and overrides.get("portfolio_url"):
                result.append(overrides["portfolio_url"])
            continue
        result.append(item)
    for key in ("linkedin_url", "github_url", "portfolio_url"):
        value = overrides.get(key)
        if value and not any(value.split("//")[-1].rstrip("/").lower() in existing.lower() for existing in result):
            result.append(value)
    return result


def _styles(style: dict, scale: float, font_delta: float) -> dict:
    fonts = _register(style.get("font_family") or "Carlito")
    body = style["body"]
    size = max(7.5, body["size"] + font_delta)
    leading = max(size * 1.08, (body.get("leading") or size * 1.22) * scale + font_delta * 1.1)
    bullet = style["bullet"]
    page = style["page"]
    del page
    styles = {
        "fonts": fonts,
        "name": ParagraphStyle(
            "name",
            fontName=fonts["bold"] if style["name"].get("bold", True) else fonts["normal"],
            fontSize=style["name"]["size"],
            leading=style["name"]["size"] * 1.15,
            alignment=TA_CENTER if style["name"].get("align") == "center" else TA_LEFT,
            spaceAfter=2 * scale,
        ),
        "contact": ParagraphStyle(
            "contact",
            fontName=fonts["normal"],
            fontSize=style["contact"]["size"] + font_delta,
            leading=(style["contact"]["size"] + font_delta) * 1.25,
            alignment=TA_CENTER if style["contact"].get("align", "center") == "center" else TA_LEFT,
            spaceAfter=3 * scale,
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName=fonts["bold"] if style["heading"].get("bold", True) else fonts["normal"],
            fontSize=style["heading"]["size"] + font_delta,
            leading=(style["heading"]["size"] + font_delta) * 1.15,
            spaceBefore=style["heading"].get("space_before", 6) * scale,
            spaceAfter=0,
        ),
        "body": ParagraphStyle("body", fontName=fonts["normal"], fontSize=size, leading=leading, alignment=TA_LEFT),
        "entry_left": ParagraphStyle("entry_left", fontName=fonts["bold"], fontSize=style["entry_title"]["size"] + font_delta, leading=(style["entry_title"]["size"] + font_delta) * 1.18),
        "entry_right": ParagraphStyle(
            "entry_right",
            fontName=fonts["italic"] if style["entry_right"].get("italic", True) else (fonts["bold"] if style["entry_right"].get("bold") else fonts["normal"]),
            fontSize=style["entry_right"]["size"] + font_delta,
            leading=(style["entry_right"]["size"] + font_delta) * 1.18,
            alignment=TA_RIGHT,
        ),
        "subtitle": ParagraphStyle("subtitle", fontName=fonts["italic"], fontSize=style["subtitle"]["size"] + font_delta, leading=(style["subtitle"]["size"] + font_delta) * 1.18),
        "plain_header": ParagraphStyle("plain_header", fontName=fonts["normal"], fontSize=size, leading=leading),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=fonts["normal"],
            fontSize=size,
            leading=leading,
            leftIndent=bullet.get("text_indent", 20),
            bulletIndent=bullet.get("indent", 7),
            bulletFontName=fonts["normal"],
            bulletFontSize=bullet.get("size", 8) + font_delta * 0.5,
        ),
        "tech": ParagraphStyle(
            "tech",
            fontName=fonts["italic"] if style["tech"].get("italic", True) else fonts["normal"],
            fontSize=style["tech"]["size"] + font_delta,
            leading=(style["tech"]["size"] + font_delta) * 1.2,
            spaceAfter=0,
        ),
        "skill": ParagraphStyle("skill", fontName=fonts["normal"], fontSize=size, leading=leading * 1.02),
    }
    return styles


def _flowables(document: dict, style: dict, *, width: float, scale: float, font_delta: float, contact_overrides: dict | None) -> list:
    st = _styles(style, scale, font_delta)
    story: list = []
    header = document.get("header") or {}
    name = header.get("name") or ""
    if style["name"].get("caps"):
        name = name.upper()
    story.append(Paragraph(escape(name), st["name"]))
    contact = _contact_items(document, contact_overrides)
    if contact:
        separator = escape(style["contact"].get("separator", " | "))
        story.append(Paragraph(separator.join(escape(item) for item in contact), st["contact"]))
    entry_gap = 3.2 * scale
    bullet_glyph = style["bullet"].get("glyph") or "•"
    for section in document.get("sections") or []:
        title = section.get("title") or ""
        if style["heading"].get("caps", True):
            title = title.upper()
        heading = [Paragraph(escape(title), st["heading"])]
        if style["heading"].get("rule", True):
            heading.append(_Rule(width, space_before=0.5, space_after=style["heading"].get("space_after", 3) * scale))
        else:
            heading.append(Spacer(1, 2 * scale))
        kind = section.get("kind")
        groups: list[list] = []  # each group is kept together on one page
        if kind == "paragraphs":
            for paragraph in section.get("paragraphs") or []:
                groups.append([Paragraph(markup_to_xml(paragraph["text"]), st["body"])])
        elif kind == "skills":
            for group in section.get("groups") or []:
                if group.get("columns") and not group.get("label"):
                    # Side-by-side bulleted skills, as in the original.
                    columns = max(2, int(group["columns"]))
                    cells = [Paragraph(escape(item), st["bullet"], bulletText=bullet_glyph) for item in group.get("items") or []]
                    cells += [Paragraph("", st["body"])] * (columns - len(cells) % columns if len(cells) % columns else 0)
                    rows = [cells[index : index + columns] for index in range(0, len(cells), columns)]
                    table = Table(rows, colWidths=[width / columns] * columns)
                    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                    groups.append([table])
                    continue
                items = ", ".join(group.get("items") or [])
                label = group.get("label")
                text = f"<b>{escape(label)}:</b> {escape(items)}" if label else escape(items)
                groups.append([Paragraph(text, st["bullet"] if group.get("bullet") else st["skill"], bulletText=bullet_glyph if group.get("bullet") else None)])
        elif kind == "list":
            for item in section.get("items") or []:
                text = markup_to_xml(item["text"])
                if item.get("right"):
                    groups.append([_two_column(Paragraph(text, st["plain_header"]), Paragraph(escape(item["right"]), st["entry_right"]), width, st)])
                elif item.get("bullet"):
                    groups.append([Paragraph(text, st["bullet"], bulletText=bullet_glyph)])
                else:
                    groups.append([Paragraph(text, st["body"])])
        else:
            for index, entry in enumerate(section.get("entries") or []):
                parts: list = []
                if index > 0:
                    parts.append(Spacer(1, entry_gap))
                for position, header_line in enumerate(entry.get("headers") or []):
                    if header_line.get("bold") or (position == 0 and not header_line.get("italic")):
                        left_style = st["entry_left"] if header_line.get("bold") else st["plain_header"]
                    elif header_line.get("italic"):
                        left_style = st["subtitle"]
                    else:
                        left_style = st["plain_header"]
                    left = Paragraph(markup_to_xml(header_line.get("text") or ""), left_style)
                    if header_line.get("right"):
                        parts.append(_two_column(left, Paragraph(escape(header_line["right"]), st["entry_right"]), width, st))
                    else:
                        parts.append(left)
                for bullet in entry.get("bullets") or []:
                    if bullet.get("hidden"):
                        continue
                    parts.append(Paragraph(markup_to_xml(bullet["text"]), st["bullet"], bulletText=bullet_glyph))
                if entry.get("tech"):
                    parts.append(Paragraph(escape(entry["tech"]), st["tech"] if entry.get("tech_italic", True) else st["body"]))
                # Keep an entry's header with its first two bullets; long entries may continue on the next page.
                head = parts[: (len(parts) - len(entry.get("bullets") or []) - (1 if entry.get("tech") else 0)) + 2]
                groups.append(head)
                for flowable in parts[len(head):]:
                    groups.append([flowable])
        if groups:
            story.append(KeepTogether(heading + groups[0]))
            for group in groups[1:]:
                story.append(KeepTogether(group) if len(group) > 1 else group[0])
        else:
            story.extend(heading)
    return story


def _two_column(left: Paragraph, right: Paragraph, width: float, st: dict) -> Table:
    text = re.sub(r"<[^>]+>", "", right.text)
    right_width = min(width * 0.45, pdfmetrics.stringWidth(text, right.style.fontName, right.style.fontSize) + 6)
    table = Table([[left, right]], colWidths=[width - right_width, right_width])
    table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ]
        )
    )
    return table


class _CountingDoc(BaseDocTemplate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages_used = 0
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
        self.addPageTemplates([PageTemplate(id="page", frames=[frame])])

    def afterPage(self):
        self.pages_used += 1


def _build(document: dict, style: dict, scale: float, font_delta: float, contact_overrides: dict | None, title: str) -> tuple[bytes, int]:
    page = style["page"]
    buffer = io.BytesIO()
    margin_top = max(14.0, page.get("margin_top", 30))
    doc = _CountingDoc(
        buffer,
        pagesize=(page.get("width", 612), page.get("height", 792)),
        leftMargin=page.get("margin_left", 40),
        rightMargin=page.get("margin_right", 40),
        topMargin=margin_top,
        bottomMargin=max(18.0, page.get("margin_bottom", 30)),
        title=title,
        author=(document.get("header") or {}).get("name") or "",
        creator="ApplyPilot",
    )
    width = doc.width
    doc.build(_flowables(document, style, width=width, scale=scale, font_delta=font_delta, contact_overrides=contact_overrides))
    return buffer.getvalue(), doc.pages_used


def render_document_pdf(document: dict, style: dict | None = None, *, contact_overrides: dict | None = None, title: str = "Resume", target_pages: int | None = None) -> tuple[bytes, dict]:
    """Render and fit to the original page count. Returns (pdf bytes, fit report)."""
    style = _complete_style(style)
    target = target_pages or style.get("pages") or 1
    attempts = [(1.0, 0.0), (0.92, 0.0), (0.85, -0.25), (0.8, -0.5), (0.75, -0.75)]
    data, pages = b"", 0
    for scale, delta in attempts:
        data, pages = _build(document, style, scale, delta, contact_overrides, title)
        if pages <= target:
            return data, {"pages": pages, "target_pages": target, "scale": scale, "font_delta": delta, "fits": True}
    return data, {"pages": pages, "target_pages": target, "scale": attempts[-1][0], "font_delta": attempts[-1][1], "fits": False}


def _complete_style(style: dict | None) -> dict:
    base = default_style()
    if not style:
        return base
    merged = copy.deepcopy(base)
    for key, value in style.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def render_document_docx(document: dict, style: dict | None = None, *, contact_overrides: dict | None = None) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    style = _complete_style(style)
    page = style["page"]
    doc = Document()
    section = doc.sections[0]
    section.page_width = Pt(page.get("width", 612))
    section.page_height = Pt(page.get("height", 792))
    section.left_margin = Pt(page.get("margin_left", 40))
    section.right_margin = Pt(page.get("margin_right", 40))
    section.top_margin = Pt(max(14, page.get("margin_top", 30)))
    section.bottom_margin = Pt(max(18, page.get("margin_bottom", 30)))
    content_width = page.get("width", 612) - page.get("margin_left", 40) - page.get("margin_right", 40)
    font_name = DOCX_FONT_NAMES.get(style.get("font_family") or "Carlito", "Calibri")
    normal = doc.styles["Normal"]
    normal.font.name = font_name
    normal.font.size = Pt(style["body"]["size"])
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.0

    def add_runs(paragraph, text: str, *, bold=False, italic=False, size=None):
        for part in re.split(r"(\*\*.+?\*\*)", text or ""):
            if not part:
                continue
            is_bold = part.startswith("**") and part.endswith("**") and len(part) > 4
            run = paragraph.add_run(part[2:-2] if is_bold else part.replace("**", ""))
            run.bold = bold or is_bold
            run.italic = italic
            if size:
                run.font.size = Pt(size)
        return paragraph

    def right_tab(paragraph):
        paragraph.paragraph_format.tab_stops.add_tab_stop(Pt(content_width), WD_TAB_ALIGNMENT.RIGHT)

    def bottom_border(paragraph):
        ppr = paragraph._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "000000")
        borders.append(bottom)
        ppr.append(borders)

    header = document.get("header") or {}
    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER if style["name"].get("align") == "center" else WD_ALIGN_PARAGRAPH.LEFT
    add_runs(name, (header.get("name") or "").upper() if style["name"].get("caps") else header.get("name") or "", bold=style["name"].get("bold", True), size=style["name"]["size"])
    contact = _contact_items(document, contact_overrides)
    if contact:
        line = doc.add_paragraph()
        line.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_runs(line, style["contact"].get("separator", " | ").join(contact), size=style["contact"]["size"])
        line.paragraph_format.space_after = Pt(3)
    glyph = style["bullet"].get("glyph") or "•"
    indent = style["bullet"].get("indent", 7)
    text_indent = style["bullet"].get("text_indent", 20)

    def bullet_paragraph(text: str):
        paragraph = doc.add_paragraph()
        fmt = paragraph.paragraph_format
        fmt.left_indent = Pt(text_indent)
        fmt.first_line_indent = Pt(indent - text_indent)
        fmt.tab_stops.add_tab_stop(Pt(text_indent))
        run = paragraph.add_run(glyph + "\t")
        run.font.size = Pt(style["bullet"].get("size", 8))
        add_runs(paragraph, text)
        return paragraph

    for section_data in document.get("sections") or []:
        heading = doc.add_paragraph()
        heading.paragraph_format.space_before = Pt(style["heading"].get("space_before", 6))
        heading.paragraph_format.space_after = Pt(style["heading"].get("space_after", 3))
        title = section_data.get("title") or ""
        add_runs(heading, title.upper() if style["heading"].get("caps", True) else title, bold=True, size=style["heading"]["size"])
        if style["heading"].get("rule", True):
            bottom_border(heading)
        kind = section_data.get("kind")
        if kind == "paragraphs":
            for paragraph in section_data.get("paragraphs") or []:
                add_runs(doc.add_paragraph(), paragraph["text"])
        elif kind == "skills":
            for group in section_data.get("groups") or []:
                if group.get("columns") and not group.get("label"):
                    columns = max(2, int(group["columns"]))
                    paragraph = doc.add_paragraph()
                    for index, item in enumerate(group.get("items") or []):
                        paragraph.paragraph_format.tab_stops.add_tab_stop(Pt(content_width * index / columns))
                        run = paragraph.add_run(("\t" if index else "") + glyph + " ")
                        run.font.size = Pt(style["bullet"].get("size", 8))
                        add_runs(paragraph, item)
                    continue
                paragraph = bullet_paragraph("") if group.get("bullet") else doc.add_paragraph()
                if group.get("label"):
                    add_runs(paragraph, f"{group['label']}: ", bold=True)
                add_runs(paragraph, ", ".join(group.get("items") or []))
        elif kind == "list":
            for item in section_data.get("items") or []:
                paragraph = bullet_paragraph(item["text"]) if item.get("bullet") else add_runs(doc.add_paragraph(), item["text"])
                if item.get("right"):
                    right_tab(paragraph)
                    add_runs(paragraph, "\t" + item["right"], italic=True)
        else:
            for index, entry in enumerate(section_data.get("entries") or []):
                for position, header_line in enumerate(entry.get("headers") or []):
                    paragraph = doc.add_paragraph()
                    if index > 0 and position == 0:
                        paragraph.paragraph_format.space_before = Pt(3)
                    bold = bool(header_line.get("bold"))
                    italic = bool(header_line.get("italic")) and not bold
                    add_runs(paragraph, header_line.get("text") or "", bold=bold, italic=italic, size=style["entry_title"]["size"] if bold else None)
                    if header_line.get("right"):
                        right_tab(paragraph)
                        add_runs(paragraph, "\t" + header_line["right"], italic=style["entry_right"].get("italic", True))
                for bullet in entry.get("bullets") or []:
                    if not bullet.get("hidden"):
                        bullet_paragraph(bullet["text"])
                if entry.get("tech"):
                    add_runs(doc.add_paragraph(), entry["tech"], italic=entry.get("tech_italic", True), size=style["tech"]["size"])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def edit_original_docx(original_path: Path, original_document: dict, tailored_document: dict) -> bytes | None:
    """Apply tailored text to a copy of the user's own DOCX, keeping its formatting.

    Bullets are matched by their original text, rewritten in place with the first
    run's formatting, and reordered within their entry. Returns None when the
    document cannot be mapped safely (the caller then uses the reconstruction).
    """
    from docx import Document

    try:
        doc = Document(str(original_path))
    except Exception:  # noqa: BLE001
        return None

    def norm(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", re.sub(r"\*\*", "", text or "").lower())

    paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    by_text: dict[str, list] = {}
    for paragraph in paragraphs:
        key = norm(re.sub(r"^\s*[●•▪◦·\-–*]\s+", "", paragraph.text))
        if key:
            by_text.setdefault(key, []).append(paragraph)

    def rewrite(paragraph, text: str) -> None:
        runs = paragraph.runs
        if not runs:
            return
        prefix = ""
        match = re.match(r"^(\s*[●•▪◦·\-–*]\s+)", paragraph.text)
        if match and runs[0].text.startswith(match.group(1).strip()):
            prefix = match.group(1)
        template = runs[0]
        for run in runs[1:]:
            run._r.getparent().remove(run._r)
        pieces = [piece for piece in re.split(r"(\*\*.+?\*\*)", text) if piece]
        template.text = prefix
        base_bold = template.bold
        for piece in pieces:
            is_bold = piece.startswith("**") and piece.endswith("**") and len(piece) > 4
            new_run = copy.deepcopy(template._r)
            paragraph._p.append(new_run)
            from docx.text.run import Run

            run = Run(new_run, paragraph)
            run.text = piece[2:-2] if is_bold else piece
            run.bold = True if is_bold else base_bold
        if not prefix:
            template._r.getparent().remove(template._r)

    original_sections = {section["id"]: section for section in original_document.get("sections") or []}
    # Projects added from the profile or left out cannot be mapped onto the original file.
    for section in tailored_document.get("sections") or []:
        source = original_sections.get(section["id"])
        if source is not None and section.get("kind") == "entries" and {e["id"] for e in section.get("entries") or []} != {e["id"] for e in source.get("entries") or []}:
            return None
    mapped = 0
    for section in tailored_document.get("sections") or []:
        source = original_sections.get(section["id"])
        if source is None:
            continue
        if section.get("kind") == "paragraphs":
            for old, new in zip(source.get("paragraphs") or [], section.get("paragraphs") or []):
                targets = by_text.get(norm(old["text"])) or []
                if targets and old["text"] != new["text"]:
                    rewrite(targets[0], new["text"])
                    mapped += 1
        elif section.get("kind") == "skills":
            for old, new in zip(source.get("groups") or [], section.get("groups") or []):
                old_text = (f"{old['label']}: " if old.get("label") else "") + ", ".join(old.get("items") or [])
                targets = by_text.get(norm(old_text)) or []
                if targets and old.get("items") != new.get("items"):
                    paragraph = targets[0]
                    label_runs = [run for run in paragraph.runs if run.bold]
                    items_text = ", ".join(new.get("items") or [])
                    if old.get("label") and label_runs:
                        others = [run for run in paragraph.runs if not run.bold]
                        if others:
                            others[0].text = items_text
                            for run in others[1:]:
                                run._r.getparent().remove(run._r)
                    else:
                        rewrite(paragraph, (f"**{new['label']}:** " if new.get("label") else "") + items_text)
                    mapped += 1
        elif section.get("kind") == "entries":
            old_entries = {entry["id"]: entry for entry in source.get("entries") or []}
            for entry in section.get("entries") or []:
                old_entry = old_entries.get(entry["id"])
                if not old_entry:
                    continue
                old_bullets = {bullet["id"]: bullet for bullet in old_entry.get("bullets") or []}
                located = []
                for bullet in old_entry.get("bullets") or []:
                    targets = by_text.get(norm(bullet["text"])) or []
                    located.append(targets[0] if targets else None)
                if any(item is None for item in located):
                    continue
                for bullet in entry.get("bullets") or []:
                    old = old_bullets.get(bullet["id"])
                    if old and old["text"] != bullet["text"]:
                        position = list(old_bullets).index(bullet["id"])
                        rewrite(located[position], bullet["text"])
                        mapped += 1
                order = [list(old_bullets).index(bullet["id"]) for bullet in entry.get("bullets") or [] if bullet["id"] in old_bullets]
                if order != sorted(order) and located:
                    anchor = located[0]._p.getprevious()
                    parent = located[0]._p.getparent()
                    elements = [located[index]._p for index in order]
                    for element in elements:
                        parent.remove(element)
                    for element in reversed(elements):
                        if anchor is not None:
                            anchor.addnext(element)
                        else:
                            parent.insert(0, element)
                    mapped += 1
                hidden = [located[list(old_bullets).index(bullet["id"])] for bullet in entry.get("bullets") or [] if bullet.get("hidden") and bullet["id"] in old_bullets]
                for paragraph in hidden:
                    paragraph._p.getparent().remove(paragraph._p)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def pdf_page_images(data: bytes, zoom: float = 1.5) -> list[bytes]:
    import pymupdf

    document = pymupdf.open(stream=data, filetype="pdf")
    images = [page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png") for page in document]
    document.close()
    return images
