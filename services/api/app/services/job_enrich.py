"""Fetch a full description for one posting, confirm it is still open, and import postings by URL.

Only public pages are read, one at a time, when the user opens or imports a
job. Sites whose terms prohibit automated access (LinkedIn, Indeed, Glassdoor,
university career portals behind sign-in) are never fetched; the user pastes
the description instead.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.security import ensure_utc
from app.models import JobPosting
from app.services.employers import parse_careers_url
from app.services.http_fetch import Http, ProviderError
from app.services.job_sources import NormalizedJob, _parse_dt, html_to_text

RESTRICTED_HOSTS = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "ca.indeed.com": "Indeed",
    "glassdoor.com": "Glassdoor",
    "glassdoor.ca": "Glassdoor",
    "talentegg.ca": "TalentEgg",
    "experience.yorku.ca": "Experience York",
    "yorku.ca": "York University",
    "orbis": "university career portal",
    "ziprecruiter.com": "ZipRecruiter",
    "monster.ca": "Monster",
    "workopolis.com": "Workopolis",
    "simplyhired.ca": "SimplyHired",
    "handshake.com": "Handshake",
    "joinhandshake.com": "Handshake",
}


def restricted_platform(url: str) -> str | None:
    host = urlparse(url if url.startswith("http") else f"https://{url}").netloc.lower()
    for domain, name in RESTRICTED_HOSTS.items():
        if host == domain or host.endswith("." + domain) or domain in host:
            return name
    return None


# ---------------------------------------------------------------------------
# Structured data on public posting pages
# ---------------------------------------------------------------------------


class _RdfaJobParser(HTMLParser):
    """Collect text of elements carrying schema.org JobPosting properties (Job Bank uses RDFa)."""

    WANTED = {"title", "description", "responsibilities", "qualification", "qualifications", "skills", "experienceRequirements", "educationRequirements", "jobBenefits", "employmentType"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.fields: dict[str, list[str]] = {}
        self.attrs_found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        prop = data.get("property") or data.get("itemprop")
        if prop and data.get("content") and prop in {"validThrough", "datePosted", "title", "name"}:
            self.attrs_found.setdefault(prop, data["content"])
        if tag in {"br", "img", "meta", "link", "input", "hr"}:
            return
        self.stack.append((tag, prop if prop in self.WANTED else None))
        if tag == "li":
            self._append("\n- ")
        elif tag in {"p", "div", "h2", "h3", "h4", "ul"}:
            self._append("\n")

    def handle_endtag(self, tag):
        while self.stack:
            open_tag, _prop = self.stack.pop()
            if open_tag == tag:
                break

    def _append(self, text: str) -> None:
        for _tag, prop in self.stack:
            if prop:
                self.fields.setdefault(prop, []).append(text)

    def handle_data(self, data):
        self._append(data)


def _jsonld_postings(page: str) -> list[dict]:
    found = []
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(match.group(1).strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                kind = item.get("@type")
                if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                    found.append(item)
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return found


def _jsonld_location(posting: dict) -> str | None:
    places = posting.get("jobLocation")
    places = places if isinstance(places, list) else [places] if places else []
    names = []
    for place in places:
        address = (place or {}).get("address") if isinstance(place, dict) else None
        if isinstance(address, dict):
            parts = [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry") if isinstance(address.get("addressCountry"), str) else (address.get("addressCountry") or {}).get("name")]
            names.append(", ".join(part for part in parts if part))
    if posting.get("jobLocationType") == "TELECOMMUTE":
        requirements = posting.get("applicantLocationRequirements")
        requirements = requirements if isinstance(requirements, list) else [requirements] if requirements else []
        regions = [item.get("name") for item in requirements if isinstance(item, dict) and item.get("name")]
        names.insert(0, "Remote" + (f" - {', '.join(regions)}" if regions else ""))
    return "; ".join(name for name in names if name) or None


def parse_posting_page(page: str, url: str) -> dict | None:
    """Return title, company, description, location, dates from a public posting page."""
    postings = _jsonld_postings(page)
    if postings:
        item = postings[0]
        org = item.get("hiringOrganization")
        company = org.get("name") if isinstance(org, dict) else (org if isinstance(org, str) else None)
        return {
            "title": html_to_text(item.get("title") or ""),
            "company": company,
            "description": html_to_text(item.get("description") or ""),
            "location": _jsonld_location(item),
            "posted_at": _parse_dt(item.get("datePosted")),
            "expires_at": _parse_dt(item.get("validThrough")),
            "employment_type": str(item.get("employmentType") or ""),
            "url": item.get("url") or url,
        }
    if 'typeof="JobPosting"' in page or "schema.org/JobPosting" in page:
        parser = _RdfaJobParser()
        parser.feed(page)
        fields = {key: re.sub(r"\n{3,}", "\n\n", "".join(value)).strip() for key, value in parser.fields.items()}
        sections = []
        for key, label in [("description", ""), ("responsibilities", "Responsibilities"), ("qualification", "Qualifications"), ("qualifications", "Qualifications"), ("experienceRequirements", "Experience"), ("educationRequirements", "Education"), ("skills", "Skills"), ("jobBenefits", "Benefits")]:
            if fields.get(key):
                sections.append(f"{label}\n{fields[key]}" if label else fields[key])
        description = re.sub(r"[ \t]+", " ", "\n\n".join(sections)).strip()
        if not description:
            return None
        return {
            "title": fields.get("title") or parser.attrs_found.get("title"),
            "company": None,
            "description": description,
            "location": None,
            "posted_at": _parse_dt(parser.attrs_found.get("datePosted")),
            "expires_at": _parse_dt(parser.attrs_found.get("validThrough")),
            "employment_type": fields.get("employmentType", ""),
            "url": url,
        }
    return None


# ---------------------------------------------------------------------------
# Enrich and verify a stored posting
# ---------------------------------------------------------------------------

VERIFY_EVERY = timedelta(hours=12)


def enrich_posting(db: Session, posting: JobPosting, *, force: bool = False, client=None) -> dict:
    """Fill in a full description and check the posting is still open. Returns what changed."""
    from app.services.privacy import is_restricted

    if posting.is_sample or posting.source in {"manual", "sample"} or is_restricted(posting):
        return {"checked": False}
    now = datetime.now(timezone.utc)
    if not force and posting.detail_checked_at and ensure_utc(posting.detail_checked_at) > now - VERIFY_EVERY:
        return {"checked": False, "recent": True}
    raw = json.loads(posting.raw_payload or "{}")
    result = {"checked": True, "closed": False, "description_updated": False}
    with Http(client) as http:
        try:
            detail = _fetch_detail(http, posting, raw)
        except ProviderError as exc:
            posting.detail_checked_at = now
            if exc.status in {404, 410}:
                posting.is_active = False
                result["closed"] = True
            else:
                result["error"] = str(exc)
            return result
    posting.detail_checked_at = now
    if detail is None:
        return result
    if detail.get("closed"):
        posting.is_active = False
        result["closed"] = True
        return result
    description = detail.get("description") or ""
    if len(description) > len(posting.description or "") + 40:
        from app.services.job_sync import reanalyze

        posting.description = description
        posting.needs_detail = False
        reanalyze(db, posting)
        result["description_updated"] = True
    if detail.get("expires_at"):
        posting.expires_at = detail["expires_at"]
        if ensure_utc(detail["expires_at"]) < now:
            posting.is_active = False
            result["closed"] = True
    if detail.get("posted_at") and not posting.posted_at:
        posting.posted_at = detail["posted_at"]
    posting.last_verified_at = now
    return result


def _fetch_detail(http: Http, posting: JobPosting, raw: dict) -> dict | None:
    source = posting.source
    if source == "greenhouse" and raw.get("board"):
        data = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{raw['board']}/jobs/{raw.get('id')}")
        return {"description": html_to_text(data.get("content") or "")}
    if source == "lever" and raw.get("site"):
        data = http.get_json(f"https://api.lever.co/v0/postings/{raw['site']}/{raw.get('id')}")
        parts = [data.get("descriptionPlain") or ""] + [f"{block.get('text', '')}\n{html_to_text(block.get('content'))}" for block in data.get("lists") or []]
        return {"description": "\n\n".join(part for part in parts if part)}
    if source == "workday" and raw.get("path"):
        employer = posting.employer_key
        from app.services.employers import EMPLOYER_BY_KEY

        known = EMPLOYER_BY_KEY.get(employer or "")
        tenant = raw.get("tenant") or (known.board if known else None)
        site = raw.get("site") or (known.site if known else None)
        wd = known.wd if known else None
        if not wd and posting.application_url:
            match = re.search(r"\.wd(\d+)\.", posting.application_url)
            wd = int(match.group(1)) if match else None
        if tenant and site and wd:
            data = http.get_json(f"https://{tenant}.wd{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{raw['path']}")
            info = data.get("jobPostingInfo") or {}
            if info.get("posted") is False or info.get("canApply") is False:
                return {"closed": True}
            return {"description": html_to_text(info.get("jobDescription") or ""), "expires_at": _parse_dt(info.get("endDate"))}
    if posting.application_url and not restricted_platform(posting.application_url):
        page = http.get_text(posting.application_url)
        if re.search(r"(no longer available|has expired|posting (is )?closed|job (has been )?(filled|closed))", page[:20000], re.I) and not _jsonld_postings(page):
            return {"closed": True}
        return parse_posting_page(page, posting.application_url)
    return None


# ---------------------------------------------------------------------------
# Import by URL
# ---------------------------------------------------------------------------


class ImportNeedsText(Exception):
    def __init__(self, platform: str):
        self.platform = platform
        super().__init__(
            f"{platform} does not allow automated reading of its pages. Open the posting, copy the description, and paste it here. "
            "The link is kept so you can apply from the original page."
        )


def fetch_posting_from_url(url: str, client=None) -> dict:
    """Resolve a posting URL into fields. Raises ImportNeedsText for platforms that must not be fetched."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    platform = restricted_platform(url)
    if platform:
        raise ImportNeedsText(platform)
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = [part for part in parsed.path.split("/") if part]
    with Http(client) as http:
        # Applicant tracking systems: read the posting through their public API.
        if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and "jobs" in path:
            board, job_id = path[0], path[path.index("jobs") + 1] if len(path) > path.index("jobs") + 1 else None
            if job_id:
                data = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
                return {
                    "title": data.get("title"),
                    "company": data.get("company_name") or board.title(),
                    "description": html_to_text(data.get("content") or ""),
                    "location": (data.get("location") or {}).get("name"),
                    "posted_at": _parse_dt(data.get("first_published") or data.get("updated_at")),
                    "url": data.get("absolute_url") or url,
                    "source_label": "Greenhouse",
                }
        if host == "jobs.lever.co" and len(path) >= 2:
            data = http.get_json(f"https://api.lever.co/v0/postings/{path[0]}/{path[1]}")
            parts = [data.get("descriptionPlain") or ""] + [f"{block.get('text', '')}\n{html_to_text(block.get('content'))}" for block in data.get("lists") or []]
            return {
                "title": data.get("text"),
                "company": path[0].replace("-", " ").title(),
                "description": "\n\n".join(part for part in parts if part),
                "location": (data.get("categories") or {}).get("location"),
                "posted_at": _parse_dt(data.get("createdAt")),
                "url": data.get("hostedUrl") or url,
                "source_label": "Lever",
            }
        if host == "jobs.ashbyhq.com" and len(path) >= 2:
            board = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{path[0]}")
            item = next((job for job in board.get("jobs") or [] if job.get("id") == path[1]), None)
            if item:
                return {
                    "title": item.get("title"),
                    "company": path[0].replace("-", " ").title(),
                    "description": item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml") or ""),
                    "location": item.get("location"),
                    "posted_at": _parse_dt(item.get("publishedAt")),
                    "url": item.get("jobUrl") or url,
                    "source_label": "Ashby",
                }
        employer = parse_careers_url(url)
        if employer and employer.ats == "workday" and "job" in path:
            index = path.index("job")
            job_path = "/" + "/".join(path[index:])
            data = http.get_json(f"https://{employer.board}.wd{employer.wd}.myworkdayjobs.com/wday/cxs/{employer.board}/{employer.site}{job_path}")
            info = data.get("jobPostingInfo") or {}
            return {
                "title": info.get("title"),
                "company": (data.get("hiringOrganization") or {}).get("name") or employer.name,
                "description": html_to_text(info.get("jobDescription") or ""),
                "location": "; ".join([info.get("location") or ""] + list(info.get("additionalLocations") or [])).strip("; "),
                "posted_at": _parse_dt(info.get("startDate")),
                "expires_at": _parse_dt(info.get("endDate")),
                "url": info.get("externalUrl") or url,
                "source_label": "Workday",
            }
        page = http.get_text(url)
        parsed_page = parse_posting_page(page, url)
        if parsed_page and parsed_page.get("description"):
            parsed_page["source_label"] = host.replace("www.", "")
            return parsed_page
    raise ImportNeedsText(host.replace("www.", "") or "This site")


def listing_from_fields(fields: dict) -> NormalizedJob:
    return NormalizedJob(
        source="import",
        external_id=fields.get("url") or fields.get("title") or "import",
        title=fields.get("title") or "Untitled role",
        company=fields.get("company") or "Company not listed",
        description=fields.get("description") or "",
        location=fields.get("location"),
        application_url=fields.get("url"),
        posted_at=fields.get("posted_at"),
        expires_at=fields.get("expires_at"),
        source_label=fields.get("source_label"),
    )
