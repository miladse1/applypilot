"""Resume extraction from styled lines.

The parser rebuilds the resume as a document model (sections, entries, bullets,
skill groups, in the original order and wording) and derives the structured
profile facts from it. It never invents employers, dates, degrees, or skills:
everything comes from the document text. Items that look like parsing
artifacts are flagged so the user can correct them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.resume_layout import LayoutResult, Line, Span, default_style, read_layout, read_text
from app.services.skills import find_skills_in_text, normalize_skill

SECTION_NAMES = {
    "summary": {"summary", "professional summary", "profile", "objective", "about", "about me", "career objective", "career summary", "professional profile", "summary of qualifications", "highlights"},
    "experience": {
        "experience", "work experience", "professional experience", "employment", "work history", "employment history",
        "professional history", "relevant experience", "experience and leadership", "career history", "internships",
        "technical experience", "industry experience", "other experience", "additional experience", "work",
    },
    "education": {"education", "academic background", "education and training", "academics", "academic history", "education & training"},
    "skills": {
        "skills", "technical skills", "core skills", "technologies", "skills and tools", "tools", "core competencies",
        "competencies", "technical tools", "skills & interests", "skills and interests", "technical proficiencies",
        "tools and technologies", "tools & technologies", "key skills", "skills summary", "relevant skills",
    },
    "projects": {"projects", "selected projects", "personal projects", "academic projects", "key projects", "project experience", "technical projects", "relevant projects", "side projects", "engineering projects"},
    "certifications": {"certifications", "certificates", "licenses", "licenses and certifications", "certifications and licenses", "licenses & certifications", "courses and certifications", "certifications & training"},
    "awards": {"awards", "honors", "honours", "awards and honors", "awards & honours", "achievements", "accomplishments", "scholarships", "honors and awards"},
    "volunteer": {"volunteer", "volunteering", "volunteer experience", "community involvement", "community service"},
    "leadership": {"leadership", "leadership experience", "extracurricular", "extracurriculars", "extracurricular activities", "activities", "involvement", "campus involvement", "clubs"},
    "publications": {"publications", "research", "research experience", "papers"},
    "interests": {"interests", "hobbies", "hobbies and interests"},
    "languages": {"languages", "spoken languages"},
    "courses": {"relevant coursework", "coursework", "courses"},
}
ENTRY_SECTIONS = {"experience", "education", "projects", "volunteer", "leadership", "publications", "awards", "certifications", "other"}
LIST_SECTIONS = {"certifications", "awards", "interests", "languages", "courses"}

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]\d{4}")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_%-]+/?", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_-]+/?", re.I)
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|ca|io|dev|app|me|net|org|ai|xyz|tech|site|page|co)(?:/[^\s|,)]*)?", re.I)
PLACEHOLDER_RE = re.compile(r"\[(?:add|insert|your)[^\]]*\]|\<(?:add|insert|your)[^>]*\>", re.I)

_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Spring|Summer|Fall|Autumn|Winter)\.?"
_DATE = rf"(?:{_MONTH}\s*,?\s*\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}}-\d{{2}}|\d{{4}})"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE})\s*(?:[–—-]|to|until)\s*(?P<end>Present|Current|Now|Ongoing|Today|{_DATE})(?:\s*\((?:expected|anticipated)\))?",
    re.I,
)
SINGLE_DATE_RE = re.compile(rf"(?:(?P<expected>expected|anticipated|graduating|grad\.?|est\.?)\s*:?\s*)?(?P<date>{_DATE})(?:\s*\((?P<expected2>expected|anticipated)\))?", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
LOCATION_RE = re.compile(
    r"^(?:[A-Z][A-Za-zÀ-ÿ.'\- ]+,\s*(?:[A-Z]{2}|Ontario|Quebec|Québec|British Columbia|Alberta|Manitoba|Saskatchewan|Nova Scotia|New Brunswick|Canada|USA|United States|UK|India)(?:,\s*(?:Canada|CA|USA|US))?|Remote(?:\s*[-(].*)?|Hybrid(?:\s*[-(].*)?)$"
)
_LOCATION_TAIL = re.compile(
    r",\s*((?:[A-Z][A-Za-zÀ-ÿ.'\-]+(?: [A-Z][A-Za-zÀ-ÿ.'\-]+){0,3}),\s*(?:[A-Z]{2}|Ontario|Quebec|Québec|British Columbia|Alberta|Canada|USA)(?:,\s*(?:Canada|CA|USA|US))?|Remote|Hybrid)\s*$"
)
TITLE_HINT = re.compile(
    r"\b(intern(ship)?|co-?op|engineer(ing)?|developer|analyst|associate|assistant|manager|specialist|coordinator|representative|technician|"
    r"consultant|lead|director|cashier|clerk|tutor|volunteer|researcher|scientist|designer|administrator|officer|advisor|adviser|agent|"
    r"operator|supervisor|president|vice[- ]president|founder|co-founder|member|ambassador|mentor|instructor|teacher|student|worker|"
    r"crew|server|barista|host|receptionist|programmer|architect|tester|trainee|apprentice|fellow|captain|chair|treasurer|secretary|"
    r"organizer|editor|writer|counsel(l)?or|lifeguard|cook|driver|attendant|stocker|merchandiser|handler|labourer|laborer|"
    r"teaching assistant|ta|research assistant|executive|head|owner|freelance(r)?|contractor)\b",
    re.I,
)
_INSTITUTION_RE = re.compile(r"\b(university|universit[ée]|college|coll[eè]ge|institute|school|polytechnic|academy|cegep|cégep|seminary)\b", re.I)
_DEGREE_RE = re.compile(
    r"\b(Bachelor(?:'s)?|Master(?:'s)?|Doctor(?:ate)?|Ph\.?\s?D\.?|B\.?\s?A\.?Sc\.?|B\.?\s?Sc\.?|B\.?\s?Eng\.?|M\.?\s?Eng\.?|M\.?\s?Sc\.?|B\.?\s?S\.?|M\.?\s?S\.?|B\.?\s?A\.?|M\.?\s?A\.?|MBA|B\.?\s?Comm?\.?|"
    r"B\.?\s?Tech\.?|Diploma|Advanced Diploma|Certificate|Associate(?:'s)? (?:Degree|of)|Honou?rs|High School|OSSD|Secondary School)\b",
)
_TECH_PREFIX = re.compile(r"^(?:technologies|tech(?:nology)? stack|tech|tools(?: used)?|built with|stack|languages and tools|skills used)\s*[:\-–]\s*", re.I)
_COURSEWORK_RE = re.compile(r"^(?:relevant\s+)?(?:coursework|courses)\s*[:\-–]\s*", re.I)
_GPA_RE = re.compile(r"\b(?:c?gpa|grade point average)\s*[:\-]?\s*([\d.]+(?:\s*/\s*[\d.]+)?)", re.I)
_SPLIT_ITEMS = re.compile(r"\s*(?:,|;|\s\|\s|•|·|●|•)\s*(?![^()]*\))")


def _clean_heading(text: str) -> str:
    cleaned = re.sub(r"[^a-z&\s]", " ", text.lower())
    cleaned = cleaned.replace("&", " and ")
    return re.sub(r"\s+", " ", cleaned).strip()


def section_key(text: str) -> str | None:
    cleaned = _clean_heading(text)
    if not cleaned or len(cleaned) > 45:
        return None
    for key, names in SECTION_NAMES.items():
        normalized = {_clean_heading(name) for name in names}
        if cleaned in normalized:
            return key
    for key, names in SECTION_NAMES.items():
        if any(cleaned.startswith(_clean_heading(name) + " ") for name in names) and len(cleaned.split()) <= 4:
            return key
    return None


# ---------------------------------------------------------------------------
# Logical lines (wrapped rows rejoined)
# ---------------------------------------------------------------------------


@dataclass
class Logical:
    text: str
    spans: list[Span]
    right: str = ""
    bullet: bool = False
    bold: bool = False
    italic: bool = False
    size: float = 10.0
    x: float = 0.0
    source: str = "text"
    rows: list[Line] = field(default_factory=list)

    @property
    def markup(self) -> str:
        return spans_to_markup(self.spans, whole_bold=self.bold)


def spans_to_markup(spans: list[Span], *, whole_bold: bool = False) -> str:
    """Text with **bold** around emphasized runs, unless the whole line is bold."""
    if whole_bold or not spans:
        return re.sub(r"\s+", " ", "".join(span.text for span in spans)).strip()
    parts = []
    for span in spans:
        text = span.text
        if span.bold and text.strip():
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            parts.append(f"{lead}**{text.strip()}**{trail}")
        else:
            parts.append(text)
    markup = re.sub(r"\s+", " ", "".join(parts)).strip()
    markup = markup.replace("** **", " ").replace("****", "")
    return markup


def strip_markup(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text or "").replace("**", "")


def _join_text(left: str, right: str) -> str:
    if left.endswith("-") and right[:1].islower():
        return left + right
    return f"{left} {right}"


def _join_spans(left: list[Span], right: list[Span], hyphen: bool) -> list[Span]:
    joined = [Span(span.text, span.bold, span.italic, span.size, span.font) for span in left]
    if joined and not hyphen:
        joined[-1].text = joined[-1].text.rstrip() + " "
    elif joined:
        joined[-1].text = joined[-1].text.rstrip()
    return joined + [Span(span.text, span.bold, span.italic, span.size, span.font) for span in right]


def _is_continuation(previous: Logical, line: Line, *, right_edge: float, section: str) -> bool:
    if line.bullet or line.right:
        return False
    if previous.right and not previous.bullet:
        return False
    if line.source == "pdf":
        last = previous.rows[-1]
        same_indent = abs(line.text_x - last.text_x) < 3
        filled = last.x1 >= right_edge - 60
        same_style = line.bold == last.bold and abs(line.size - last.size) < 0.6 and line.italic == last.italic
        if previous.bullet and same_indent and not line.bold:
            return True
        # Wrapped bullet text sits right of the bullet glyph even when the row itself is bold-heavy.
        bullet_x = last.bullet_x if last.bullet_x is not None else None
        if previous.bullet and bullet_x is not None and line.text_x > bullet_x + 6 and same_indent:
            return True
        if not previous.bullet and same_indent and filled and same_style and not line.bold:
            return True
        return False
    if line.source == "text":
        if previous.bullet and line.text[:1].islower():
            return True
        if section == "summary" and not previous.bullet:
            return True
    return False


def _logical_lines(lines: list[Line], *, right_edge: float, section: str) -> list[Logical]:
    result: list[Logical] = []
    for line in lines:
        if result and _is_continuation(result[-1], line, right_edge=right_edge, section=section):
            previous = result[-1]
            hyphen = previous.text.endswith("-") and line.text[:1].islower()
            previous.text = _join_text(previous.text, line.text)
            previous.spans = _join_spans(previous.spans, line.spans, hyphen)
            previous.rows.append(line)
            continue
        result.append(
            Logical(
                text=line.text,
                spans=[Span(span.text, span.bold, span.italic, span.size, span.font) for span in line.spans] or [Span(line.text)],
                right=line.right,
                bullet=line.bullet,
                bold=line.bold,
                italic=line.italic,
                size=line.size,
                x=line.text_x,
                source=line.source,
                rows=[line],
            )
        )
    return result


# ---------------------------------------------------------------------------
# Dates, skills, and small field parsers
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12", "spring": "04", "summer": "06", "fall": "09", "autumn": "09", "winter": "01",
}


def month_year(token: str | None) -> str | None:
    if not token:
        return None
    token = token.strip()
    if token.lower() in {"present", "current", "now", "ongoing", "today"}:
        return None
    slash = re.match(r"(\d{1,2})/(\d{4})", token)
    if slash:
        return f"{slash.group(2)}-{int(slash.group(1)):02d}-01"
    iso = re.match(r"(\d{4})-(\d{2})", token)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-01"
    year = re.search(r"(19|20)\d{2}", token)
    if not year:
        return None
    month = "01"
    lowered = token.lower()
    for name, number in _MONTHS.items():
        if lowered.startswith(name):
            month = number
            break
    return f"{year.group(0)}-{month}-01"


def find_dates(*texts: str) -> dict:
    for text in texts:
        if not text:
            continue
        match = DATE_RANGE_RE.search(text)
        if match:
            end = match.group("end")
            return {
                "start_date": month_year(match.group("start")),
                "end_date": month_year(end),
                "is_current": end.lower() in {"present", "current", "now", "ongoing", "today"},
                "label": match.group(0),
                "expected": bool(re.search(r"expected|anticipated", match.group(0), re.I)),
            }
    for text in texts:
        if not text:
            continue
        match = SINGLE_DATE_RE.search(text)
        if match and (match.group("expected") or match.group("expected2") or YEAR_RE.search(match.group("date"))):
            return {
                "start_date": None,
                "end_date": month_year(match.group("date")),
                "is_current": False,
                "label": match.group(0),
                "expected": bool(match.group("expected") or match.group("expected2")),
            }
    return {}


def _strip_dates(text: str) -> str:
    text = DATE_RANGE_RE.sub("", text)
    return re.sub(r"\s*[|,–—-]\s*$", "", text).strip()


def split_items(text: str) -> list[str]:
    items = []
    for piece in _SPLIT_ITEMS.split(text):
        piece = piece.strip(" .")
        piece = re.sub(r"^(?:and|&)\s+", "", piece, flags=re.I)
        if piece:
            items.append(piece)
    return items


def _skill_record(name: str, *, group: str | None, found_in: str) -> dict:
    key, display, category = normalize_skill(name)
    malformed = len(name) > 45 or len(name.split()) > 5 or ":" in name or bool(re.search(r"[.!?]\s|\b(and|with|using|for)\b.*\b(and|with|using|for)\b", name))
    known = category != "other"
    return {
        "name": display if known else name.strip(),
        "original": name.strip(),
        "normalized_name": key,
        "category": category,
        "group": group,
        "source": "resume_extracted",
        "confidence": "high" if (known or not malformed) else "low",
        "needs_review": malformed,
        "found_in": found_in,
    }


def _looks_like_tech_line(line: Logical) -> bool:
    if _TECH_PREFIX.match(line.text):
        return True
    items = split_items(line.text)
    if len(items) < 3:
        return False
    known = sum(1 for item in items if normalize_skill(item)[2] != "other" or find_skills_in_text(item, list_context=True))
    short = all(len(item.split()) <= 4 for item in items)
    return short and (known / len(items) >= 0.5 or (line.italic and known >= 2))


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


@dataclass
class RawEntry:
    headers: list[Logical] = field(default_factory=list)
    bullets: list[Logical] = field(default_factory=list)
    tech: Logical | None = None
    extra: list[Logical] = field(default_factory=list)


def _segment_entries(lines: list[Logical], *, styled: bool) -> list[RawEntry]:
    entries: list[RawEntry] = []
    current: RawEntry | None = None
    for line in lines:
        if line.bullet:
            if current is None:
                current = RawEntry()
                entries.append(current)
            current.bullets.append(line)
            continue
        if current is not None and (current.bullets or current.headers) and current.tech is None and _looks_like_tech_line(line) and not (styled and line.bold):
            current.tech = line
            continue
        starts_new = (
            current is None
            or bool(current.bullets)
            or current.tech is not None
            or (styled and line.bold and any(not header.bold for header in current.headers))
            or (styled and line.bold and current.headers and current.headers[-1].bold and bool(line.right) and bool(current.headers[-1].right) and find_dates(line.right) and find_dates(current.headers[-1].right))
        )
        if starts_new:
            current = RawEntry(headers=[line])
            entries.append(current)
        else:
            current.headers.append(line)
    return entries


def _split_title_employer(text: str) -> tuple[str, str, str | None]:
    """Return (title, employer, location) from one header line."""
    location = None
    tail = _LOCATION_TAIL.search(text)
    working = text
    if tail:
        location = tail.group(1).strip()
        working = text[: tail.start()].strip()
    for separator in (" — ", " – ", " | ", " - ", " @ ", " at "):
        if separator in working:
            left, right = [part.strip() for part in working.split(separator, 1)]
            if LOCATION_RE.match(right):
                return "", left, location or right
            left_hint = bool(TITLE_HINT.search(left))
            right_hint = bool(TITLE_HINT.search(right))
            if separator.strip() in {"@", "at"}:
                return left, right, location
            if right_hint and not left_hint:
                return right, left, location
            if left_hint and not right_hint:
                return left, right, location
            # Both or neither look like titles. Resumes usually put the employer first after an em dash.
            return (right, left, location) if separator in {" — ", " – "} else (left, right, location)
    if "," in working:
        left, right = [part.strip() for part in working.split(",", 1)]
        if TITLE_HINT.search(left) and not TITLE_HINT.search(right):
            return left, right, location
    if TITLE_HINT.search(working):
        return working, "", location
    return "", working, location


def _experience(entry: RawEntry) -> dict:
    header_texts = [strip_markup(line.text) for line in entry.headers]
    rights = [line.right for line in entry.headers if line.right]
    dates = find_dates(*rights, *header_texts)
    title = employer = ""
    location = None
    for right in rights:
        if LOCATION_RE.match(right.strip()) and not find_dates(right):
            location = right.strip()
    pieces = [_strip_dates(text) for text in header_texts]
    pieces = [piece for piece in pieces if piece and not (find_dates(piece) and len(_strip_dates(piece)) < 3)]
    pieces = [piece for piece in pieces if not re.fullmatch(_DATE, piece.strip(), re.I)]
    inline = next((piece for piece in pieces if piece.count("|") >= 1), None)
    if inline and len(pieces) == 1:
        parts = [part.strip() for part in inline.split("|") if part.strip() and not find_dates(part)]
        if len(parts) >= 2:
            titled = [part for part in parts if TITLE_HINT.search(part)]
            title = titled[0] if titled else parts[0]
            employer = next(part for part in parts if part != title)
            extra = [part for part in parts if part not in {title, employer}]
            if extra and LOCATION_RE.match(extra[0]):
                location = location or extra[0]
            pieces = []
    if pieces and not title and not employer:
        first_title, first_employer, first_location = _split_title_employer(pieces[0])
        location = location or first_location
        if len(pieces) >= 2:
            second_title, second_employer, second_location = _split_title_employer(pieces[1])
            location = location or second_location
            if first_title and first_employer:
                title, employer = first_title, first_employer
            elif first_title and not first_employer:
                title = first_title
                employer = second_employer or second_title
            elif first_employer and not first_title:
                employer = first_employer
                title = second_title or second_employer
            else:
                title, employer = second_title, second_employer
        else:
            title, employer = first_title, first_employer
    if not title and employer and len(entry.headers) > 1:
        title = strip_markup(entry.headers[1].text)
    bullets = [strip_markup(line.text) for line in entry.bullets]
    tech = split_items(_TECH_PREFIX.sub("", entry.tech.text)) if entry.tech else []
    technologies = list(dict.fromkeys([*tech, *[display for _key, display, _cat in find_skills_in_text(" ".join(bullets))]]))
    needs_review = not (title and employer) or not dates
    return {
        "title": title.strip(" ,|"),
        "employer": employer.strip(" ,|"),
        "location": location,
        "start_date": dates.get("start_date"),
        "end_date": dates.get("end_date"),
        "is_current": bool(dates.get("is_current")),
        "date_label": dates.get("label"),
        "responsibilities": bullets,
        "technologies": technologies,
        "source": "resume_extracted",
        "confidence": "high" if not needs_review else "medium",
        "needs_review": needs_review,
    }


def _education(entry: RawEntry) -> dict:
    texts = [strip_markup(line.text) for line in entry.headers]
    rights = [line.right for line in entry.headers if line.right]
    all_texts = texts + rights
    institution = next((text for text in texts if _INSTITUTION_RE.search(text)), "")
    degree_line = next((text for text in texts if _DEGREE_RE.search(text) and text != institution), None)
    if degree_line is None and institution and _DEGREE_RE.search(institution) and "," in institution:
        # "B.A. Economics, City College"
        left, right = [part.strip() for part in institution.rsplit(",", 1)]
        if _INSTITUTION_RE.search(right):
            degree_line, institution = left, right
    if not institution:
        institution = next((text for text in texts if text != degree_line and not find_dates(text)), "")
        if degree_line is None and "," in institution and _DEGREE_RE.search(institution):
            left, right = [part.strip() for part in institution.rsplit(",", 1)]
            degree_line, institution = left, right
    location = None
    tail = _LOCATION_TAIL.search(institution or "")
    if tail:
        location = tail.group(1)
        institution = institution[: tail.start()].strip()
    for right in rights:
        if LOCATION_RE.match(right) and not find_dates(right):
            location = location or right
    degree = program = None
    if degree_line:
        degree_line = _strip_dates(degree_line)
        if "," in degree_line:
            degree, program = [part.strip() for part in degree_line.split(",", 1)]
        else:
            match = re.match(r"^(.*?\b(?:of|in)\b\s+[A-Z][\w&\s]+?)(?:\s+in\s+(.+))?$", degree_line)
            short = re.match(r"^((?:[A-Z]\.){1,3}[A-Z]?\.?|[A-Z]{2,5}\.?|B\.?\s?A\.?Sc\.?|B\.?\s?Eng\.?|M\.?\s?Eng\.?)\s+(.+)$", degree_line)
            if short:
                degree, program = short.group(1).strip(), short.group(2).strip()
            elif match and match.group(2):
                degree, program = match.group(1).strip(), match.group(2).strip()
            else:
                degree = degree_line
    dates = find_dates(*all_texts)
    coursework = None
    gpa = None
    achievements = []
    for bullet in [strip_markup(line.text) for line in entry.bullets] + [strip_markup(line.text) for line in entry.headers if line.text not in {institution, degree_line}]:
        if _COURSEWORK_RE.match(bullet):
            coursework = _COURSEWORK_RE.sub("", bullet).strip()
            continue
        gpa_match = _GPA_RE.search(bullet)
        if gpa_match:
            gpa = gpa_match.group(1)
        if bullet in texts:
            continue
        achievements.append(bullet)
    graduation = dates.get("end_date")
    return {
        "institution": institution,
        "degree": degree,
        "program": program,
        "location": location,
        "start_date": dates.get("start_date"),
        "graduation_date": graduation,
        "expected": bool(dates.get("expected")) or bool(dates.get("is_current")),
        "date_label": dates.get("label"),
        "coursework": coursework,
        "gpa": gpa,
        "achievements": "\n".join(achievements) or None,
        "source": "resume_extracted",
        "confidence": "high" if degree and institution else "medium",
        "needs_review": not degree or not institution,
    }


def _project(entry: RawEntry) -> dict:
    header = entry.headers[0] if entry.headers else None
    name = strip_markup(header.text) if header else ""
    inline_tech: list[str] = []
    if " | " in name:
        left, right = [part.strip() for part in name.split(" | ", 1)]
        right_items = split_items(right)
        if right_items and sum(1 for item in right_items if normalize_skill(item)[2] != "other") >= max(1, len(right_items) // 2):
            name, inline_tech = left, right_items
    rights = [line.right for line in entry.headers if line.right]
    dates = find_dates(*rights)
    status = next((right for right in rights if not find_dates(right)), None)
    urls = [match.group(0) for text in [line.text for line in entry.headers] + rights for match in URL_RE.finditer(text) if "." in match.group(0)]
    bullets = [strip_markup(line.text) for line in entry.bullets]
    subtitle = " ".join(strip_markup(line.text) for line in entry.headers[1:]) or None
    tech = split_items(_TECH_PREFIX.sub("", entry.tech.text)) if entry.tech else []
    technologies = list(dict.fromkeys([*inline_tech, *tech]))
    if not technologies:
        technologies = [display for _key, display, _cat in find_skills_in_text(" ".join(bullets))]
    return {
        "name": name,
        "subtitle": subtitle,
        "status": status,
        "date_label": dates.get("label"),
        "description": " ".join(bullets) if bullets else (subtitle or ""),
        "bullets": bullets,
        "technologies": technologies,
        "responsibilities": "\n".join(bullets),
        "results": "",
        "url": urls[0] if urls else None,
        "source": "resume_extracted",
        "confidence": "high" if name and (bullets or subtitle) else "medium",
        "needs_review": not name,
    }


def _certification(text: str, right: str = "") -> dict:
    text = strip_markup(text)
    dates = find_dates(right, text)
    clean = _strip_dates(text)
    clean = re.sub(r"\(\s*\)", "", clean).strip()
    issuer = None
    for separator in (" — ", " – ", " - ", " | ", ", "):
        if separator in clean:
            name, issuer = [part.strip() for part in clean.split(separator, 1)]
            break
    else:
        name = clean
    year = re.search(r"\((\d{4})\)", text)
    return {
        "name": name.strip(),
        "issuer": issuer,
        "issue_date": dates.get("end_date") or (f"{year.group(1)}-01-01" if year else None),
        "expiration_date": None,
        "source": "resume_extracted",
        "confidence": "medium" if issuer else "low",
        "needs_review": issuer is None,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _header_contact(header: list[Line], full_text: str) -> dict:
    name_line = next((line for line in header if line.text.strip()), None)
    name = name_line.text.strip() if name_line else ""
    if name and (EMAIL_RE.search(name) or PHONE_RE.search(name)):
        name = re.split(r"\s*[|•·]\s*", name)[0]
    contact_lines = [line.text for line in header[1:]] + [line.right for line in header if line.right]
    blob = " | ".join(contact_lines)
    email = EMAIL_RE.search(blob) or EMAIL_RE.search(full_text)
    phone = PHONE_RE.search(blob)
    linkedin = LINKEDIN_RE.search(full_text)
    github = GITHUB_RE.search(full_text)
    placeholders = PLACEHOLDER_RE.findall(blob)
    items = [item.strip() for line in contact_lines for item in re.split(r"\s*(?:\||•|·|⋄|◇|●|•|\s{3,})\s*", line) if item.strip()]
    location = None
    for item in items:
        if LOCATION_RE.match(item) and not EMAIL_RE.search(item):
            location = item
            break
    other_links = []
    for item in items:
        if EMAIL_RE.search(item) or PLACEHOLDER_RE.search(item):
            continue
        for match in URL_RE.finditer(item):
            value = match.group(0)
            if "linkedin.com" in value.lower() or "github.com" in value.lower():
                continue
            other_links.append(value)
    return {
        "full_name": name,
        "email": email.group(0) if email else None,
        "phone": phone.group(0) if phone else None,
        "location": location,
        "linkedin_url": linkedin.group(0) if linkedin else None,
        "github_url": github.group(0) if github else None,
        "portfolio_url": other_links[0] if other_links else None,
        "items": items,
        "placeholders": placeholders,
        "needs_review": not email or not name,
        "confidence": "high" if email and name else "low",
    }


def parse_layout(layout: LayoutResult, raw_text: str = "") -> dict:
    lines = layout.lines
    full_text = raw_text or "\n".join(line.text + ("  " + line.right if line.right else "") for line in lines)
    styled = layout.fmt in {"pdf", "docx"} and any(line.bold for line in lines)
    right_edge = max((line.x1 for line in lines), default=600) if layout.fmt == "pdf" else 600

    # Section boundaries
    headings: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        if line.bullet:
            continue
        key = section_key(line.text)
        looks_like_heading = (
            len(line.text) <= 45
            and not line.right
            and (line.rule_below or (line.caps and (line.bold or layout.fmt == "text") and len(line.text.split()) <= 5) or line.style_name.lower().startswith("heading"))
            and index > 0
        )
        if key or (looks_like_heading and not EMAIL_RE.search(line.text) and not PHONE_RE.search(line.text)):
            if key is None and layout.fmt == "text" and not line.caps:
                continue
            headings.append((index, key or "other", line.text.strip()))
    header_end = headings[0][0] if headings else min(3, len(lines))
    header = lines[:header_end]
    contact = _header_contact(header, full_text)

    document = {
        "version": 1,
        "format": layout.fmt,
        "header": {"name": contact["full_name"], "contact_items": contact["items"], "lines": [line.text for line in header[1:]]},
        "sections": [],
    }
    parsed = {
        "contact": contact,
        "summary": "",
        "skills": [],
        "skill_groups": [],
        "education": [],
        "experience": [],
        "projects": [],
        "certifications": [],
        "other_sections": [],
        "warnings": [],
    }
    known_skills: set[str] = set()

    for position, (start, key, title) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = lines[start + 1 : end]
        logical = _logical_lines(body, right_edge=right_edge, section=key)
        section_id = f"s{position + 1}"
        section = {"id": section_id, "key": key, "title": title}
        if key == "summary":
            paragraphs = [{"id": f"{section_id}p{i + 1}", "text": item.markup} for i, item in enumerate(logical)]
            section.update(kind="paragraphs", paragraphs=paragraphs)
            parsed["summary"] = " ".join(strip_markup(item["text"]) for item in paragraphs)[:3000]
        elif key == "skills":
            groups = []
            for i, item in enumerate(logical):
                text = strip_markup(item.text)
                label = None
                inline_bullets = bool(re.search(r"\s[●•▪◦·]\s", text))
                label_match = None if inline_bullets else re.match(r"^([^:]{2,45}):\s*(.+)$", text)
                if label_match:
                    label, text = label_match.group(1).strip(), label_match.group(2)
                values = [piece.strip() for piece in re.split(r"\s[●•▪◦·]\s", text)] if inline_bullets else split_items(text)
                group = {"id": f"{section_id}g{i + 1}", "label": label, "items": values, "bullet": item.bullet}
                if inline_bullets:
                    # A row of side-by-side bulleted skills: keep the columns when rebuilding.
                    group["columns"] = len(values)
                groups.append(group)
                parsed["skill_groups"].append({"label": label, "items": values})
                for value in values:
                    record = _skill_record(value, group=label, found_in="skills_section")
                    if record["normalized_name"] in known_skills:
                        continue
                    known_skills.add(record["normalized_name"])
                    parsed["skills"].append(record)
            section.update(kind="skills", groups=groups)
        elif key in LIST_SECTIONS and not any(item.bullet for item in logical[1:]) or key in {"interests", "languages", "courses"}:
            items = [{"id": f"{section_id}i{i + 1}", "text": item.markup, "right": item.right, "bullet": item.bullet} for i, item in enumerate(logical)]
            section.update(kind="list", items=items)
            if key == "certifications":
                for item in logical:
                    if item.text.strip().lower() in {"none", "none listed", "n/a", "na", "not applicable"}:
                        continue
                    parsed["certifications"].append(_certification(item.text, item.right))
            else:
                parsed["other_sections"].append({"key": key, "title": title, "items": [strip_markup(item.text) for item in logical]})
        else:
            raw_entries = _segment_entries(logical, styled=styled)
            entries = []
            for i, raw in enumerate(raw_entries):
                entry_id = f"{section_id}e{i + 1}"
                entry = {
                    "id": entry_id,
                    "headers": [{"text": header.markup, "right": header.right, "bold": header.bold, "italic": header.italic} for header in raw.headers],
                    "bullets": [{"id": f"{entry_id}b{j + 1}", "text": bullet.markup} for j, bullet in enumerate(raw.bullets)],
                    "tech": raw.tech.text if raw.tech else None,
                    "tech_italic": bool(raw.tech and raw.tech.italic),
                }
                if key == "experience" or (key in {"volunteer", "leadership"} and raw.headers):
                    fields = _experience(raw)
                    fields["entry_id"] = entry_id
                    if key == "experience":
                        parsed["experience"].append(fields)
                    else:
                        parsed["other_sections"].append({"key": key, "title": title, "entry": fields})
                    entry["fields"] = {k: fields[k] for k in ("title", "employer", "location", "start_date", "end_date", "is_current")}
                elif key == "education":
                    fields = _education(raw)
                    fields["entry_id"] = entry_id
                    parsed["education"].append(fields)
                    entry["fields"] = {k: fields[k] for k in ("institution", "degree", "program", "graduation_date")}
                elif key == "projects":
                    fields = _project(raw)
                    fields["entry_id"] = entry_id
                    if fields["name"] and fields["name"].lower() != "none listed":
                        parsed["projects"].append(fields)
                    entry["fields"] = {"name": fields["name"], "technologies": fields["technologies"]}
                elif key == "certifications":
                    for header in raw.headers:
                        parsed["certifications"].append(_certification(header.text, header.right))
                else:
                    parsed["other_sections"].append({"key": key, "title": title, "items": [strip_markup(h.text) for h in raw.headers] + [strip_markup(b.text) for b in raw.bullets]})
                entries.append(entry)
            section.update(kind="entries", entries=entries)
        document["sections"].append(section)

    # Skills mentioned in experience and projects but not in the skills list.
    added = 0
    for origin, texts in (
        ("experience", [" ".join(item["responsibilities"]) + " " + " ".join(item["technologies"]) for item in parsed["experience"]]),
        ("project", [" ".join(item["bullets"]) + " " + ", ".join(item["technologies"]) for item in parsed["projects"]]),
    ):
        for text in texts:
            for key, display, category in find_skills_in_text(text):
                if key in known_skills or category == "soft_skill":
                    continue
                known_skills.add(key)
                parsed["skills"].append(
                    {
                        "name": display,
                        "original": display,
                        "normalized_name": key,
                        "category": category,
                        "group": None,
                        "source": "resume_extracted",
                        "confidence": "high",
                        "needs_review": False,
                        "found_in": origin,
                    }
                )
                added += 1

    if not headings:
        parsed["warnings"].append("No section headings were recognized. Review every section below.")
    if not any(section["key"] == "skills" for section in document["sections"]):
        parsed["warnings"].append("No skills heading was found. Tools mentioned in your experience and projects were collected instead." if added else "No skills section was detected.")
    elif added:
        parsed["warnings"].append(f"{added} tool(s) appear in your experience or projects but not in your skills list. They were added and marked with where they were found.")
    if not contact["email"]:
        parsed["warnings"].append("No email address was found. Review contact information.")
    if contact["placeholders"]:
        parsed["warnings"].append(
            "Your resume still contains placeholder text: " + ", ".join(contact["placeholders"]) + ". Add the real links in your profile; tailored resumes leave placeholders out."
        )
    if any(item["needs_review"] for item in parsed["experience"]):
        parsed["warnings"].append("Some roles are missing a title, employer, or dates. Check them below.")

    parsed["document"] = document
    parsed["style"] = layout.style
    parsed["parser"] = f"layout-{layout.fmt}"
    parsed["pages"] = layout.pages
    return parsed


def parse_resume_file(path: Path, content_type: str = "", raw_text: str = "") -> dict:
    layout = read_layout(path, content_type)
    return parse_layout(layout, raw_text)


def parse_resume_text(text: str) -> dict:
    """Parse plain text. Used for pasted resumes and older uploads without a stored file."""
    result = parse_layout(read_text(text), text)
    if result.get("style") is None:
        result["style"] = default_style()
    return result
