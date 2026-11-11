"""Job description analysis.

External descriptions are untrusted data. Extraction is schema-limited: it can
only emit known categories and phrases grounded in the description.
"""

from __future__ import annotations

import re

from app.services.skills import find_skills_in_text, normalize_skill

_YEARS_RE = re.compile(r"(\d+)\s*\+?\s*(?:years|yrs)\b", re.I)
_EDU_RE = re.compile(r"\b(ph\.?d\.?|master'?s|bachelor'?s|b\.s\.|m\.s\.|associate)\b", re.I)
_AUTH_RE = re.compile(
    r"\b(authorized to work|work authorization|visa sponsorship|sponsorship|security clearance|us citizen)\b",
    re.I,
)
_LICENSE_RE = re.compile(r"\b(professional engineering license|p\.?\s*e\.?\s*license|license required)\b", re.I)
_INJECTION_RE = re.compile(
    r"\b(ignore (all |any )?(previous|prior) instructions|you are now|system prompt|mark all skills|set (the )?score)\b",
    re.I,
)

_PREFERRED_HEAD = re.compile(
    r"\b(preferred|nice[- ]to[- ]haves?|bonus|assets?|pluses|a plus|desired|desirable|ideal(ly)?|would be great|great to have|extra credit|good to have|optional)\b",
    re.I,
)
_MANDATORY_HEAD = re.compile(
    r"\b(requirements?|qualifications?|must[- ]haves?|must have|required|what you(?:'|’)ll need|what you will need|what you bring|what we(?:'|’)re looking for|"
    r"what we are looking for|who you are|you have|about you|skills|experience|you might be|minimum|basic|key qualifications|need to succeed|"
    r"you(?:'|’)re a (?:great )?fit|you should have|looking for someone|ideal candidate|competencies|eligibility|to be successful)\b",
    re.I,
)
_RESPONSIBILITY_HEAD = re.compile(
    r"\b(responsibilit|what you(?:'|’)ll do|what you will do|the role|your role|day[- ]to[- ]day|in this role|key duties|duties|"
    r"what you(?:'|’)ll be doing|job description|about the (?:role|job|position)|the opportunity|your impact|what you(?:'|’)ll work on|mandate)",
    re.I,
)
_IGNORE_HEAD = re.compile(
    r"\b(about us|about the company|who we are|benefits|perks|compensation|salary|pay range|why join|why you(?:'|’)ll love|equal opportunit|"
    r"accommodation|diversity|inclusion|our values|our culture|what we offer|we offer|how to apply|additional information|disclaimer|privacy)\b",
    re.I,
)


def _heading_priority(line: str) -> tuple[str | None, str]:
    """Classify a heading line. Returns (section, trailing text after a colon)."""
    text = line.strip().strip("*#").strip()
    rest = ""
    if ":" in text:
        head, _, tail = text.partition(":")
        if len(head) <= 60 and tail.strip():
            text, rest = head.strip(), tail.strip()
    if not text or len(text) > 70 or (text.endswith(".") and not rest):
        return None, ""
    words = len(text.split())
    ends_with_colon = line.strip().rstrip("*").endswith(":")
    if words > 9 or (not ends_with_colon and not rest and (words > 6 or find_skills_in_text(text))):
        return None, ""
    if _IGNORE_HEAD.search(text):
        return "ignore", rest
    if _RESPONSIBILITY_HEAD.search(text):
        return "responsibilities", rest
    if _PREFERRED_HEAD.search(text):
        return "preferred", rest
    if _MANDATORY_HEAD.search(text):
        return "mandatory", rest
    return None, ""


_ENROLLMENT_RE = re.compile(
    r"\b(currently enrolled|enrolled in|returning to (?:school|studies)|co-?op (?:program|programme|term)|pursuing (?:a |an )?(?:bachelor|degree|undergraduate)|"
    r"graduating (?:in|between)|recent graduate|student status|full[- ]time student)\b",
    re.I,
)


def _education_name(line: str) -> str | None:
    match = _EDU_RE.search(line)
    if not match:
        return None
    token = match.group(1).lower()
    if token.startswith("ph"):
        return "Doctoral degree"
    if token.startswith("m") or "master" in token:
        return "Master's degree"
    if "associate" in token:
        return "Associate degree"
    return "Bachelor's degree"


def analyze_job_text(title: str, description: str) -> dict:
    """Return categorized requirements. Instruction-like text is ignored."""
    cleaned = _INJECTION_RE.sub(" ", (description or "").replace("’", "'").replace("‘", "'"))
    # "Docker required; Kubernetes is a plus" carries two priorities.
    cleaned = re.sub(r";\s+(?=\S)", "\n- ", cleaned)
    priority = "unclear"
    responsibilities: list[str] = []
    requirements: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(item: dict) -> None:
        key = (item["normalized_name"], item["priority"])
        if key in seen:
            return
        seen.add(key)
        requirements.append(item)

    for raw_line in cleaned.splitlines():
        line = raw_line.strip(" \t-*•●▪◦·")
        if not line:
            continue
        is_bullet = bool(re.match(r"^\s*[-*•●▪◦·]\s", raw_line))
        heading, rest = (None, "") if is_bullet else _heading_priority(line)
        if heading:
            priority = heading
            if not rest:
                continue
            line = rest
        if priority == "ignore":
            continue
        if priority == "responsibilities":
            if len(line) > 20:
                responsibilities.append(line.lstrip("-•* ").strip())
            # Responsibilities often name tools ("you will build pipelines in Airflow").
            for key, display, _category in find_skills_in_text(line):
                add(
                    {
                        "name": display,
                        "normalized_name": key,
                        "category": "skill",
                        "priority": "optional",
                        "raw_text": line[:500],
                        "min_years": None,
                        "is_ambiguous": False,
                    }
                )
            continue
        if priority not in {"mandatory", "preferred", "optional", "unclear"}:
            continue
        if priority == "unclear" and not (_EDU_RE.search(line) or _AUTH_RE.search(line) or _YEARS_RE.search(line)):
            # Before a requirements heading, do not treat boilerplate as mandatory skills.
            continue
        enrollment_line = bool(_ENROLLMENT_RE.search(line))
        if enrollment_line:
            add(
                {
                    "name": "Enrolled in a post-secondary program",
                    "normalized_name": "enrollment",
                    "category": "enrollment",
                    "priority": "mandatory" if priority == "unclear" else priority,
                    "raw_text": line[:500],
                    "min_years": None,
                    "is_ambiguous": False,
                }
            )
        line_priority = priority
        if priority == "mandatory" and re.search(r"\b(nice to have|is a plus|an asset|a plus|preferred|bonus|ideally|would be great)\b", line, re.I):
            line_priority = "preferred"
        years = _YEARS_RE.search(line)
        min_years = int(years.group(1)) if years else None
        if _AUTH_RE.search(line):
            add(
                {
                    "name": "Work authorization",
                    "normalized_name": "work-authorization",
                    "category": "authorization",
                    "priority": "mandatory" if priority == "unclear" else priority,
                    "raw_text": line[:500],
                    "min_years": None,
                    "is_ambiguous": False,
                }
            )
        if _LICENSE_RE.search(line):
            add(
                {
                    "name": "Professional license",
                    "normalized_name": "professional-license",
                    "category": "certification",
                    "priority": "mandatory" if priority == "unclear" else priority,
                    "raw_text": line[:500],
                    "min_years": None,
                    "is_ambiguous": False,
                }
            )
        education = _education_name(line)
        if education:
            key, display, _category = normalize_skill(education)
            add(
                {
                    "name": display if display != education else education,
                    "normalized_name": key,
                    "category": "education",
                    "priority": "mandatory" if priority == "unclear" else priority,
                    "raw_text": line[:500],
                    "min_years": None,
                    "is_ambiguous": False,
                }
            )
        skills = find_skills_in_text(line)
        if skills:
            for key, display, category in skills:
                if category == "soft_skill":
                    continue
                add(
                    {
                        "name": display,
                        "normalized_name": key,
                        "category": "skill",
                        "priority": line_priority if line_priority != "unclear" else "unclear",
                        "raw_text": line[:500],
                        "min_years": min_years,
                        "is_ambiguous": False,
                    }
                )
        elif priority in {"mandatory", "preferred", "optional"} and not education and not enrollment_line and not _AUTH_RE.search(line):
            if re.search(r"\bfamiliar|similar|equivalent|other\b", line, re.I):
                add(
                    {
                        "name": line[:180],
                        "normalized_name": "ambiguous-requirement",
                        "category": "other",
                        "priority": "unclear",
                        "raw_text": line[:500],
                        "min_years": min_years,
                        "is_ambiguous": True,
                    }
                )
        if min_years and re.search(r"professional experience|relevant experience|years of experience", line, re.I):
            add(
                {
                    "name": f"{min_years}+ years of experience",
                    "normalized_name": f"experience-{min_years}",
                    "category": "experience",
                    "priority": "mandatory" if priority == "unclear" else priority,
                    "raw_text": line[:500],
                    "min_years": min_years,
                    "is_ambiguous": False,
                }
            )

    rank = {"mandatory": 0, "preferred": 1, "unclear": 2, "optional": 3}
    best: dict[str, dict] = {}
    for item in requirements:
        current = best.get(item["normalized_name"])
        if current is None or rank.get(item["priority"], 9) < rank.get(current["priority"], 9):
            best[item["normalized_name"]] = item
    requirements = [item for item in requirements if best.get(item["normalized_name"]) is item]
    seniority = detect_seniority(title, description)
    arrangement = detect_arrangement(title, description)
    employment = detect_employment(title, description)
    return {
        "seniority": seniority,
        "work_arrangement": arrangement,
        "employment_type": employment,
        "responsibilities": "\n".join(responsibilities),
        "requirements": requirements,
    }


def detect_seniority(title: str, description: str = "") -> str:
    text = f"{title} {description[:400]}".lower()
    if re.search(r"\bintern\b", text):
        return "intern"
    if re.search(r"\b(junior|entry[- ]level|new grad)\b", text):
        return "entry"
    if re.search(r"\b(staff|principal)\b", text):
        return "staff"
    if re.search(r"\b(senior|sr\.?)\b", text):
        return "senior"
    if re.search(r"\blead\b", text):
        return "lead"
    return "mid"


def detect_arrangement(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if "hybrid" in text:
        return "hybrid"
    if re.search(r"\bremote\b", text):
        return "remote"
    if re.search(r"\bon[- ]?site\b", text):
        return "onsite"
    return "unknown"


def detect_employment(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if re.search(r"\bintern(ship)?\b", text):
        return "internship"
    if "contract" in text:
        return "contract"
    if "part-time" in text or "part time" in text:
        return "part_time"
    if "full-time" in text or "full time" in text:
        return "full_time"
    return "unknown"


def validate_grounded_requirements(requirements: list[dict], description: str) -> list[dict]:
    """Drop AI requirements that are not supported by the description text."""
    haystack = description.casefold()
    grounded = []
    for item in requirements:
        raw = (item.get("raw_text") or item.get("name") or "").casefold()
        skill_hits = find_skills_in_text(item.get("name") or "")
        name_in_text = (item.get("name") or "").casefold() in haystack
        raw_in_text = raw and raw in haystack
        skill_in_text = any(display.casefold() in haystack for _key, display, _cat in skill_hits)
        if item.get("category") == "skill" and not (skill_in_text or name_in_text):
            continue
        if not (raw_in_text or name_in_text or skill_in_text):
            continue
        priority = item.get("priority")
        if priority not in {"mandatory", "preferred", "optional", "unclear"}:
            continue
        grounded.append(item)
    return grounded
