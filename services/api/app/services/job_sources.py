"""Job-source adapters.

Every adapter reads a public listing API or feed that the employer or board
publishes for this purpose. None of them log in, bypass bot checks, or scrape
sites that prohibit it (LinkedIn, Indeed, Glassdoor, university portals). Those
sources are covered by saved-search links and user-assisted import instead.

Listing access never grants permission to submit an application.
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, quote_plus

from app.core.config import Settings
from app.services.analysis import detect_arrangement, detect_employment
from app.services.employers import Employer, parse_board_token
from app.services.http_fetch import Http, ProviderError, as_http
from app.services import taxonomy

__all__ = [
    "ProviderError",
    "NormalizedJob",
    "SearchQuery",
    "SearchPlan",
    "html_to_text",
    "fingerprint",
]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip += 1
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "ul", "ol"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    raw = html.unescape(value) if "&lt;" in value else value
    parser = _TextExtractor()
    parser.feed(raw)
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n- \n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _norm(item: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (item or "").lower()).strip()


_COMPANY_SUFFIX = re.compile(r"\b(inc|incorporated|ltd|limited|llc|corp|corporation|co|company|ulc|canada|the|group|holdings)\b")


def company_key(name: str | None) -> str:
    text = _norm(name)
    text = _COMPANY_SUFFIX.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_key(title: str) -> str:
    text = _norm(title)
    text = re.sub(r"\b(20\d\d|summer|fall|winter|spring|autumn|4 months?|8 months?|12 months?|16 months?|months?)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(company: str, title: str, location: str | None) -> str:
    info = taxonomy.classify_location(location)
    place = info.city or info.scope or _norm(location)[:40]
    if info.is_remote:
        place = f"remote-{info.scope}"
    raw = "|".join([company_key(company), _title_key(title), place])
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        try:
            fixed = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
            parsed = datetime.fromisoformat(fixed)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(re.sub(r"\s+", " ", text), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        try:
            return parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return None


def _relative_posted(value: str | None) -> datetime | None:
    """Workday-style 'Posted Today', 'Posted 9 Days Ago', 'Posted 30+ Days Ago'."""
    if not value:
        return None
    text = value.lower()
    now = datetime.now(timezone.utc)
    if "today" in text:
        return now
    if "yesterday" in text:
        return now - timedelta(days=1)
    match = re.search(r"(\d+)\+?\s*day", text)
    if match:
        return now - timedelta(days=int(match.group(1)))
    return None


def _salary_from_text(text: str) -> tuple[int | None, int | None]:
    amounts = [int(item.replace(",", "")) for item in re.findall(r"\$(\d{2,3}(?:,\d{3})+)", text or "")]
    if len(amounts) >= 2:
        return amounts[0], amounts[1]
    if len(amounts) == 1:
        return amounts[0], None
    return None, None


def _money(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Normalized posting and search plan
# ---------------------------------------------------------------------------


@dataclass
class NormalizedJob:
    source: str
    external_id: str
    title: str
    company: str
    description: str
    location: str | None = None
    industry: str | None = None
    work_arrangement: str = "unknown"
    employment_type: str = "unknown"
    seniority: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    application_url: str | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    is_sample: bool = False
    remote_flag: bool | None = None
    company_country: str | None = None
    source_label: str | None = None
    employer_key: str | None = None
    hints: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    # Filled by classify()
    role_family: str | None = None
    role_families: list[str] = field(default_factory=list)
    location_scope: str | None = None
    experience_years: int | None = None
    level_reason: str = ""

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.company, self.title, self.location)

    def classify(self) -> "NormalizedJob":
        role = taxonomy.classify_role(self.title, self.description)
        self.role_families = role["families"]
        self.role_family = role["primary"]
        level = taxonomy.classify_level(self.title, self.description, self.hints)
        self.seniority = level["level"]
        self.level_reason = level["reason"]
        self.experience_years = level["years"]
        remote = self.remote_flag
        if remote is None and self.work_arrangement == "remote":
            remote = True
        info = taxonomy.classify_location(self.location, self.description, remote_flag=remote, company_country=self.company_country)
        self.location_scope = info.scope
        if info.is_remote:
            self.work_arrangement = "remote"
        if self.employment_type in {"", "unknown", None} and self.seniority == "intern":
            self.employment_type = "internship"
        return self


@dataclass
class SearchQuery:
    """Legacy single-keyword query, still accepted by every adapter."""

    keywords: str = ""
    location: str = ""
    page: int = 1


@dataclass
class SearchPlan:
    families: list[str] = field(default_factory=lambda: list(taxonomy.DEFAULT_FAMILIES))
    levels: list[str] = field(default_factory=lambda: list(taxonomy.DEFAULT_LEVELS))
    scopes: list[str] = field(default_factory=lambda: list(taxonomy.DEFAULT_SCOPES))
    terms: list[str] = field(default_factory=list)
    city: str = "Toronto"
    max_age_days: int | None = 90
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    detail_cap: int = 25
    permissive: bool = False

    @classmethod
    def from_query(cls, query: SearchQuery) -> "SearchPlan":
        terms = [query.keywords] if query.keywords else []
        return cls(
            families=list(taxonomy.ROLE_FAMILIES),
            levels=list(taxonomy.LEVELS),
            scopes=list(taxonomy.LOCATION_SCOPES),
            terms=terms,
            city=query.location or "Toronto",
            max_age_days=None,
            include_keywords=[query.keywords] if query.keywords else [],
            permissive=True,
        )

    def level_terms(self) -> list[str]:
        words = []
        if "intern" in self.levels:
            words += ["intern", "co-op"]
        if "new_grad" in self.levels:
            words += ["new grad"]
        if "entry" in self.levels:
            words += ["junior"]
        return words

    def role_words(self) -> list[str]:
        mapping = {
            "software": "software",
            "backend": "developer",
            "full_stack": "developer",
            "frontend": "developer",
            "data_engineering": "data engineer",
            "data_science": "data scientist",
            "data_analytics": "data analyst",
            "ml_ai": "machine learning",
            "cloud_devops": "cloud",
            "mobile": "mobile",
            "qa_automation": "quality assurance",
            "security": "security",
        }
        words: list[str] = []
        for family in self.families:
            word = mapping.get(family)
            if word and word not in words:
                words.append(word)
        return words

    def employer_queries(self, budget: int = 6) -> list[str]:
        """Queries for employer career sites, where results are already limited to one company."""
        if self.permissive:
            return self.terms[:budget] or [""]
        queries = self.level_terms()[:3] + self.role_words()
        seen: list[str] = []
        for item in queries:
            if item not in seen:
                seen.append(item)
        return seen[:budget]

    def board_queries(self, budget: int = 6) -> list[str]:
        if self.permissive:
            return self.terms[:budget] or [""]
        custom = [term for term in self.terms if term][: max(1, budget // 2)]
        generated = taxonomy.search_terms(self.families, self.levels, budget=budget)
        merged = list(dict.fromkeys([*custom, *generated]))
        return merged[:budget]

    # Filtering --------------------------------------------------------------

    def title_ok(self, title: str) -> bool:
        if self.permissive:
            return True
        role = taxonomy.classify_role(title)
        allowed = set(self.families) | {"technology_general"}
        if not role["families"] or not (set(role["families"]) & allowed):
            # Generic co-op titles are decided after the description is read.
            return taxonomy.is_student_title(title.lower()) and "technology_general" in allowed
        level = taxonomy.classify_level(title)["level"]
        return level in self.levels or level == "unspecified"

    def location_ok(self, location: str | None, *, remote_flag: bool | None = None, company_country: str | None = None) -> bool:
        if self.permissive:
            return True
        info = taxonomy.classify_location(location, remote_flag=remote_flag, company_country=company_country)
        return info.scope in self.scopes or info.scope in {"unknown", "canada_other"}

    def accept(self, job: NormalizedJob) -> bool:
        job.classify()
        blob = f"{job.title} {job.description}".lower()
        if self.exclude_keywords and any(word.lower() in blob for word in self.exclude_keywords if word):
            return False
        if self.permissive:
            if self.include_keywords:
                return all(_keyword_in(word, blob) for word in self.include_keywords if word)
            return True
        if not job.role_families or not (set(job.role_families) & (set(self.families) | {"technology_general"})):
            return False
        if job.seniority not in self.levels:
            return False
        if job.location_scope not in self.scopes:
            return False
        if job.expires_at and job.expires_at < datetime.now(timezone.utc):
            return False
        if self.max_age_days and job.posted_at:
            age = taxonomy.age_days(job.posted_at)
            if age is not None and age > self.max_age_days:
                return False
        if self.include_keywords and not any(_keyword_in(word, blob) for word in self.include_keywords if word):
            return False
        return True


def _keyword_in(word: str, blob: str) -> bool:
    word = word.lower().strip()
    if not word:
        return True
    if word in blob:
        return True
    parts = [part for part in re.split(r"\s+", word) if len(part) > 2]
    return bool(parts) and all(re.search(rf"\b{re.escape(part)}", blob) for part in parts)


# ---------------------------------------------------------------------------
# Adapter base
# ---------------------------------------------------------------------------


class Adapter:
    name = "base"
    kind = "board"  # employer | board | sample
    full_catalog = False
    label = "Job source"

    def __init__(self, client=None):
        self.client = client
        self.listed_ids: set[str] | None = None

    @property
    def key(self) -> str:
        return self.name

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:  # pragma: no cover - interface
        raise NotImplementedError

    def search(self, query: SearchQuery) -> list[NormalizedJob]:
        http = as_http(self.client)
        try:
            plan = SearchPlan.from_query(query)
            return [job for job in self.fetch(plan, http) if plan.accept(job)]
        finally:
            if self.client is None:
                http.close()


class EmployerAdapter(Adapter):
    kind = "employer"

    def __init__(self, employer: Employer | str, client=None):
        super().__init__(client)
        if isinstance(employer, str):
            employer = parse_board_token(f"{self.name}:{employer}") or Employer(employer, employer, self.name, employer)
        self.employer = employer
        self.label = employer.name

    @property
    def key(self) -> str:
        return f"{self.name}:{self.employer.key}"

    # Legacy attribute names used elsewhere.
    @property
    def board(self) -> str:
        return self.employer.board

    @property
    def site(self) -> str:
        return self.employer.board

    def _job(self, **kwargs) -> NormalizedJob:
        kwargs.setdefault("company", self.employer.name)
        kwargs.setdefault("company_country", self.employer.country)
        kwargs.setdefault("source_label", self.employer.name)
        kwargs.setdefault("employer_key", self.employer.key)
        return NormalizedJob(source=self.name, **kwargs)


# ---------------------------------------------------------------------------
# Applicant tracking systems
# ---------------------------------------------------------------------------


class GreenhouseAdapter(EmployerAdapter):
    name = "greenhouse"
    full_catalog = True

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        board = self.employer.board
        payload = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
        jobs: list[NormalizedJob] = []
        details = 0
        self.listed_ids = {f"{board}:{item.get('id')}" for item in payload.get("jobs") or []}
        for item in payload.get("jobs") or []:
            title = item.get("title") or "Untitled role"
            location = (item.get("location") or {}).get("name")
            if not plan.title_ok(title) or not plan.location_ok(location, company_country=self.employer.country):
                continue
            content = item.get("content")
            clear_fit = plan.permissive or taxonomy.classify_location(location, company_country=self.employer.country).scope in plan.scopes
            if content is None and details < (plan.detail_cap if clear_fit else plan.detail_cap // 3):
                details += 1
                try:
                    detail = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{item.get('id')}")
                    content = detail.get("content") or ""
                except ProviderError:
                    content = ""
            description = html_to_text(content or "")
            metadata = {str(entry.get("name", "")).lower(): entry.get("value") for entry in item.get("metadata") or [] if isinstance(entry, dict)}
            employment = str(metadata.get("employment type") or "")
            salary_min, salary_max = _salary_from_text(description)
            jobs.append(
                self._job(
                    external_id=f"{board}:{item.get('id')}",
                    title=title,
                    company=item.get("company_name") or self.employer.name,
                    description=description,
                    location=location,
                    work_arrangement=detect_arrangement(title, f"{location or ''} {description[:500]}"),
                    employment_type=detect_employment(f"{title} {employment}", description[:500]),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency="CAD" if salary_min and "CA$" in description else ("USD" if salary_min else None),
                    application_url=item.get("absolute_url"),
                    posted_at=_parse_dt(item.get("first_published") or item.get("updated_at")),
                    expires_at=_parse_dt(item.get("application_deadline")),
                    raw={"id": item.get("id"), "board": board},
                )
            )
        return jobs


class LeverAdapter(EmployerAdapter):
    name = "lever"
    full_catalog = True

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        site = self.employer.board
        payload = http.get_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
        if isinstance(payload, dict):
            payload = payload.get("postings") or []
        jobs = []
        self.listed_ids = {f"{site}:{item.get('id')}" for item in payload}
        for item in payload:
            title = item.get("text") or "Untitled role"
            categories = item.get("categories") or {}
            location = categories.get("location") or ", ".join(categories.get("allLocations") or []) or None
            workplace = (item.get("workplaceType") or "").lower()
            remote = True if workplace == "remote" else None
            if not plan.title_ok(title) or not plan.location_ok(location, remote_flag=remote, company_country=self.employer.country):
                continue
            parts = [item.get("descriptionPlain") or html_to_text(item.get("description"))]
            for block in item.get("lists") or []:
                parts.append(f"\n{block.get('text', '')}\n{html_to_text(block.get('content'))}")
            parts.append(item.get("additionalPlain") or "")
            description = "\n".join(part for part in parts if part).strip()
            commitment = (categories.get("commitment") or "").lower()
            jobs.append(
                self._job(
                    external_id=f"{site}:{item.get('id')}",
                    title=title,
                    description=description,
                    location=location,
                    work_arrangement={"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(workplace, detect_arrangement(title, description[:400])),
                    employment_type=detect_employment(f"{title} {commitment}", ""),
                    application_url=item.get("hostedUrl") or item.get("applyUrl"),
                    posted_at=_parse_dt(item.get("createdAt")),
                    remote_flag=remote,
                    raw={"id": item.get("id"), "site": site},
                )
            )
        return jobs


class AshbyAdapter(EmployerAdapter):
    name = "ashby"
    full_catalog = True

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        board = self.employer.board
        payload = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
        jobs = []
        self.listed_ids = {f"{board}:{item.get('id')}" for item in payload.get("jobs") or []}
        for item in payload.get("jobs") or []:
            if item.get("isListed") is False:
                continue
            title = item.get("title") or "Untitled role"
            locations = [item.get("location") or ""]
            locations += [entry.get("location", "") for entry in item.get("secondaryLocations") or [] if isinstance(entry, dict)]
            address = ((item.get("address") or {}).get("postalAddress") or {})
            if address.get("addressLocality") and address.get("addressLocality") not in " ".join(locations):
                locations.append(", ".join(part for part in [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")] if part))
            location = "; ".join(part for part in locations if part) or None
            remote = bool(item.get("isRemote")) or (item.get("workplaceType") or "").lower() == "remote"
            if not plan.title_ok(title) or not plan.location_ok(location, remote_flag=remote or None, company_country=self.employer.country):
                continue
            description = item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml") or "")
            employment = (item.get("employmentType") or "").lower()
            compensation = (item.get("compensation") or {}).get("compensationTierSummary")
            jobs.append(
                self._job(
                    external_id=f"{board}:{item.get('id')}",
                    title=title,
                    description=(description + (f"\n\nCompensation: {compensation}" if compensation else "")).strip(),
                    location=location,
                    work_arrangement="remote" if remote else {"hybrid": "hybrid", "onsite": "onsite"}.get((item.get("workplaceType") or "").lower(), "unknown"),
                    employment_type={"fulltime": "full_time", "parttime": "part_time", "intern": "internship", "contract": "contract", "temporary": "contract"}.get(employment, "unknown"),
                    application_url=item.get("jobUrl"),
                    posted_at=_parse_dt(item.get("publishedAt")),
                    remote_flag=remote or None,
                    raw={"id": item.get("id"), "board": board},
                )
            )
        return jobs


class WorkdayAdapter(EmployerAdapter):
    """Workday career sites publish a JSON listing used by their own search page."""

    name = "workday"
    full_catalog = False

    CANADA_ID = "a30a87ed25634629aa6c3958aa2b91ea"

    def _base(self) -> str:
        employer = self.employer
        return f"https://{employer.board}.wd{employer.wd}.myworkdayjobs.com/wday/cxs/{employer.board}/{employer.site}"

    def _site_url(self, path: str) -> str:
        employer = self.employer
        return f"https://{employer.board}.wd{employer.wd}.myworkdayjobs.com/{employer.site}{path}"

    def _country_facet(self, http: Http) -> dict:
        first = http.post_json(f"{self._base()}/jobs", {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})

        def walk(facets, parent=None):
            for facet in facets or []:
                param = facet.get("facetParameter") or parent
                for value in facet.get("values") or []:
                    if value.get("descriptor") == "Canada" and value.get("id") and param and "ountry" in param:
                        return {param: [value["id"]]}
                    nested = walk([value], param) if value.get("values") else None
                    if nested:
                        return nested
            return None

        return walk(first.get("facets")) or {}

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        base = self._base()
        try:
            facets = self._country_facet(http)
        except ProviderError:
            raise
        country_filtered = bool(facets)
        seen: dict[str, dict] = {}
        for query in plan.employer_queries(6):
            try:
                payload = http.post_json(f"{base}/jobs", {"appliedFacets": facets, "limit": 20, "offset": 0, "searchText": query})
            except ProviderError as exc:
                if exc.status == 400 and facets:
                    facets, country_filtered = {}, False
                    payload = http.post_json(f"{base}/jobs", {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": query})
                else:
                    raise
            for item in payload.get("jobPostings") or []:
                path = item.get("externalPath")
                if path and path not in seen:
                    seen[path] = item
        candidates = []
        for path, item in seen.items():
            title = item.get("title") or ""
            location = item.get("locationsText") or ""
            if re.match(r"^\d+ locations?$", location.lower()):
                location = ""
            if not plan.title_ok(title):
                continue
            if location and not country_filtered and not plan.location_ok(location, company_country=self.employer.country):
                continue
            candidates.append((path, item))
        jobs = []
        for path, item in candidates[: plan.detail_cap]:
            try:
                detail = http.get_json(f"{base}{path}")
            except ProviderError:
                continue
            info = detail.get("jobPostingInfo") or {}
            if info.get("posted") is False or info.get("canApply") is False:
                continue
            title = info.get("title") or item.get("title") or "Untitled role"
            locations = [info.get("location") or item.get("locationsText") or ""] + list(info.get("additionalLocations") or [])
            country = ((info.get("country") or {}).get("descriptor") or "")
            location = "; ".join(part for part in locations if part)
            known_country = re.search(r"\b(can|canada|usa|united states)\b", location.lower())
            if country and not known_country:
                location = f"{location}, {country}" if location else country
            remote_type = (info.get("remoteType") or item.get("remoteType") or "").lower()
            remote = True if remote_type == "remote" else None
            description = html_to_text(info.get("jobDescription") or "")
            hints = [str(entry) for entry in item.get("bulletFields") or []]
            jobs.append(
                self._job(
                    external_id=f"{self.employer.board}:{info.get('jobReqId') or path}",
                    title=title,
                    # Workday reports the legal entity ("0000050007 Royal Bank of Canada"); show the brand.
                    company=self.employer.name,
                    description=description,
                    location=location or None,
                    work_arrangement="remote" if remote else ("hybrid" if "flex" in remote_type or "hybrid" in remote_type else ("onsite" if remote_type in {"onsite", "office focused"} else "unknown")),
                    employment_type=detect_employment(f"{title} {info.get('timeType') or ''}", description[:300]),
                    application_url=info.get("externalUrl") or self._site_url(path),
                    posted_at=_parse_dt(info.get("startDate")) or _relative_posted(info.get("postedOn") or item.get("postedOn")),
                    expires_at=_parse_dt(info.get("endDate")),
                    remote_flag=remote,
                    hints=hints,
                    raw={"path": path, "tenant": self.employer.board, "site": self.employer.site},
                )
            )
        return jobs


class SuccessFactorsAdapter(EmployerAdapter):
    """SAP SuccessFactors career sites publish RSS feeds per keyword."""

    name = "successfactors"

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        host = self.employer.board
        seen: set[str] = set()
        jobs = []
        for query in plan.employer_queries(5):
            if not query:
                continue
            url = f"https://{host}/feeds/{quote(query)}/?locale=en_US"
            try:
                text = http.get_text(url)
            except ProviderError as exc:
                if exc.status == 404:
                    continue
                raise
            for item in _rss_items(text):
                link = item.get("link") or ""
                if not link or link in seen:
                    continue
                seen.add(link)
                raw_title = item.get("title") or ""
                match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", raw_title)
                title, location = (match.group(1), match.group(2)) if match else (raw_title, "")
                if not plan.title_ok(title) or not plan.location_ok(location, company_country=self.employer.country):
                    continue
                description = html_to_text(re.sub(r"<img[^>]*>", "", item.get("description") or ""))
                job_id = re.search(r"/(\d+)/?$", link)
                jobs.append(
                    self._job(
                        external_id=f"{host}:{job_id.group(1) if job_id else hashlib.sha1(link.encode(), usedforsecurity=False).hexdigest()[:16]}",
                        title=title.strip(),
                        description=description,
                        location=location or None,
                        work_arrangement=detect_arrangement(title, description[:600]),
                        employment_type=detect_employment(title, description[:600]),
                        application_url=link,
                        posted_at=_parse_dt(item.get("pubDate")),
                        raw={"link": link},
                    )
                )
        return jobs


class AmazonAdapter(EmployerAdapter):
    name = "amazon"

    def __init__(self, employer: Employer | None = None, client=None):
        super().__init__(employer or Employer("amazon", "Amazon", "amazon"), client)

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        queries = plan.employer_queries(4)
        mapping = {"software": "software development engineer", "developer": "software development engineer", "co-op": "intern"}
        seen: set[str] = set()
        jobs = []
        for query in dict.fromkeys(mapping.get(item, item) for item in queries):
            url = f"https://www.amazon.jobs/en/search.json?base_query={quote_plus(query)}&country=CAN&result_limit=50&sort=recent&offset=0"
            payload = http.get_json(url)
            for item in payload.get("jobs") or []:
                job_id = str(item.get("id_icims") or item.get("id"))
                if job_id in seen:
                    continue
                seen.add(job_id)
                title = item.get("title") or ""
                location = item.get("normalized_location") or item.get("location")
                if not plan.title_ok(title) or not plan.location_ok(location):
                    continue
                description = "\n\n".join(
                    part
                    for part in [
                        html_to_text(item.get("description")),
                        "Basic Qualifications\n" + html_to_text(item.get("basic_qualifications")) if item.get("basic_qualifications") else "",
                        "Preferred Qualifications\n" + html_to_text(item.get("preferred_qualifications")) if item.get("preferred_qualifications") else "",
                    ]
                    if part
                )
                hints = ["university"] if item.get("university_job") else []
                jobs.append(
                    self._job(
                        external_id=f"amazon:{job_id}",
                        title=title,
                        company="Amazon",
                        description=description,
                        location=location,
                        work_arrangement="onsite",
                        employment_type=detect_employment(f"{title} {item.get('job_schedule_type') or ''}", ""),
                        application_url=f"https://www.amazon.jobs{item.get('job_path')}" if item.get("job_path") else None,
                        posted_at=_parse_dt(item.get("posted_date")),
                        hints=hints,
                        raw={"id": job_id},
                    )
                )
        return jobs


class IBMAdapter(EmployerAdapter):
    name = "ibm"

    def __init__(self, employer: Employer | None = None, client=None):
        super().__init__(employer or Employer("ibm", "IBM", "ibm"), client)

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        jobs = []
        seen: set[str] = set()
        fields = ["_id", "title", "url", "description", "field_keyword_05", "field_keyword_08", "field_keyword_17", "field_keyword_18", "field_keyword_19", "dcdate"]
        for query in plan.employer_queries(4):
            body = {
                "appId": "careers",
                "scopes": ["careers2"],
                "query": {
                    "bool": {
                        "must": [{"simple_query_string": {"query": query or "*", "fields": ["title^3", "description^2", "body"]}}],
                        "filter": [{"term": {"field_keyword_05": "Canada"}}],
                    }
                },
                "size": 40,
                "from": 0,
                "_source": fields,
            }
            payload = http.post_json("https://www-api.ibm.com/search/api/v2", body)
            for hit in (payload.get("hits") or {}).get("hits") or []:
                source = hit.get("_source") or {}
                url = source.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                title = source.get("title") or ""
                location = source.get("field_keyword_19") or ""
                if location and "canada" not in location.lower() and re.search(r",\s*CA$", location):
                    location = location[:-2] + "Canada"
                if not plan.title_ok(title) or not plan.location_ok(location):
                    continue
                level_hint = source.get("field_keyword_18") or ""
                arrangement = (source.get("field_keyword_17") or "").lower()
                job_id = re.search(r"jobId=(\d+)", url)
                jobs.append(
                    self._job(
                        external_id=f"ibm:{job_id.group(1) if job_id else hit.get('_id')}",
                        title=title,
                        company="IBM",
                        description=source.get("description") or "",
                        location=location or "Canada",
                        work_arrangement={"hybrid": "hybrid", "remote": "remote", "onsite": "onsite", "on-site": "onsite"}.get(arrangement, "unknown"),
                        employment_type="internship" if "intern" in level_hint.lower() else "unknown",
                        application_url=url,
                        posted_at=_parse_dt(source.get("dcdate")),
                        hints=[level_hint.lower()] if level_hint else [],
                        raw={"url": url, "needs_detail": True},
                    )
                )
        return jobs


class JibeAdapter(EmployerAdapter):
    """iCIMS Jibe career sites (for example careers.amd.com) expose /api/jobs."""

    name = "jibe"

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        host = self.employer.board
        jobs = []
        seen: set[str] = set()
        for query in plan.employer_queries(3):
            payload = http.get_json(f"https://{host}/api/jobs?keywords={quote_plus(query)}&location=Canada&page=1&limit=50")
            for entry in payload.get("jobs") or []:
                item = entry.get("data") or {}
                slug = str(item.get("slug") or item.get("req_id") or "")
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                title = item.get("title") or ""
                location = ", ".join(part for part in [str(item.get("city") or "").title(), item.get("state"), item.get("country")] if part) or item.get("full_location")
                if not plan.title_ok(title) or not plan.location_ok(location):
                    continue
                description = "\n\n".join(html_to_text(item.get(key)) for key in ("description", "responsibilities", "qualifications") if item.get(key))
                categories = " ".join(str(cat.get("name", "")) for cat in item.get("categories") or [] if isinstance(cat, dict))
                hints = ["campus"] if any("campus" in str(tag).lower() for tag in item.get("tags4") or []) else []
                jobs.append(
                    self._job(
                        external_id=f"{host}:{slug}",
                        title=title,
                        description=description,
                        location=location,
                        employment_type="internship" if re.search(r"intern|co-?op|student", f"{title} {categories}", re.I) else detect_employment(title, ""),
                        application_url=f"https://{host}/careers-home/jobs/{slug}?lang=en-us",
                        posted_at=_parse_dt(item.get("posted_date")),
                        hints=hints,
                        raw={"slug": slug, "apply_url": item.get("apply_url")},
                    )
                )
        return jobs


# ---------------------------------------------------------------------------
# Job boards and aggregators
# ---------------------------------------------------------------------------


class JobBankAdapter(Adapter):
    """Government of Canada Job Bank search feed (Atom). Respects the 5 second crawl delay."""

    name = "jobbank"
    label = "Job Bank (Government of Canada)"

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        jobs = []
        seen: set[str] = set()
        terms = plan.board_queries(3) if plan.permissive else _jobbank_terms(plan)
        for term in terms:
            url = (
                "https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed?"
                f"searchstring={quote_plus(term)}&locationstring={quote_plus(plan.city + ', ON')}&sort=D"
            )
            text = http.get_text(url)
            for entry in _atom_entries(text):
                link = entry.get("link") or ""
                job_id = re.search(r"jobposting/(\d+)", link)
                if not job_id or job_id.group(1) in seen:
                    continue
                seen.add(job_id.group(1))
                summary = html_to_text(entry.get("summary") or "")
                location = _field(summary, "Location")
                employer = _field(summary, "Employer") or "Employer not listed"
                salary = _field(summary, "Salary")
                title = (entry.get("title") or "").strip()
                if not plan.title_ok(title) or not plan.location_ok(location):
                    continue
                pretty_title = title[:1].upper() + title[1:]
                jobs.append(
                    NormalizedJob(
                        source="jobbank",
                        external_id=job_id.group(1),
                        title=pretty_title,
                        company=employer.title() if employer.isupper() else employer,
                        description=f"{summary}\n\nOpen the posting for the full description.",
                        location=location,
                        salary_min=_money(re.sub(r"[^\d.]", "", salary.split()[0])) if salary else None,
                        salary_currency="CAD" if salary else None,
                        application_url=link,
                        posted_at=_parse_dt(entry.get("updated")),
                        company_country="canada",
                        source_label="Job Bank",
                        raw={"id": job_id.group(1), "needs_detail": True, "salary": salary},
                    )
                )
        return jobs


def _jobbank_terms(plan: SearchPlan) -> list[str]:
    mapping = {
        "software": "software developer",
        "backend": "software engineer",
        "full_stack": "web developer",
        "data_engineering": "data engineer",
        "data_science": "data scientist",
        "data_analytics": "data analyst",
        "ml_ai": "machine learning",
        "cloud_devops": "cloud engineer",
    }
    terms = []
    for family in plan.families:
        term = mapping.get(family)
        if term and term not in terms:
            terms.append(term)
    if "intern" in plan.levels:
        terms.insert(0, "co-op student")
    return terms[:4]


def _field(summary: str, name: str) -> str:
    match = re.search(rf"{name}:\s*(.+?)(?=\s+(?:Job number|Location|Employer|Salary):|$)", summary, re.S)
    return match.group(1).strip() if match else ""


class AdzunaAdapter(Adapter):
    name = "adzuna"
    label = "Adzuna Canada"

    def __init__(self, settings: Settings, client=None):
        super().__init__(client)
        self.settings = settings

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        if not self.settings.adzuna_configured:
            raise ProviderError("Adzuna credentials are not configured.")
        country = (self.settings.adzuna_country or "ca").lower()
        jobs = []
        seen: set[str] = set()
        for term in plan.board_queries(6):
            params = {
                "app_id": self.settings.adzuna_app_id,
                "app_key": self.settings.adzuna_app_key,
                "results_per_page": 50,
                "what": term,
                "where": plan.city if country == "ca" else "",
                "sort_by": "date",
                "content-type": "application/json",
            }
            if plan.max_age_days:
                params["max_days_old"] = plan.max_age_days
            query = "&".join(f"{key}={quote_plus(str(value))}" for key, value in params.items() if value != "")
            payload = http.get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?{query}")
            for item in payload.get("results") or []:
                job_id = str(item.get("id"))
                if job_id in seen:
                    continue
                seen.add(job_id)
                title = html_to_text(item.get("title") or "")
                location = (item.get("location") or {}).get("display_name")
                areas = (item.get("location") or {}).get("area") or []
                if areas and "Canada" in areas[0:1] and location and "canada" not in location.lower():
                    location = f"{location}, {', '.join(areas[1:2])}, Canada".replace(", , ", ", ")
                if not plan.title_ok(title) or not plan.location_ok(location):
                    continue
                description = html_to_text(item.get("description") or "")
                jobs.append(
                    NormalizedJob(
                        source="adzuna",
                        external_id=job_id,
                        title=title,
                        company=(item.get("company") or {}).get("display_name") or "Company not listed",
                        description=description,
                        location=location,
                        industry=(item.get("category") or {}).get("label"),
                        work_arrangement=detect_arrangement(title, description),
                        employment_type={"full_time": "full_time", "part_time": "part_time"}.get(item.get("contract_time") or "", detect_employment(title, description)),
                        salary_min=_money(item.get("salary_min")),
                        salary_max=_money(item.get("salary_max")),
                        salary_currency="CAD" if country == "ca" else "USD",
                        application_url=item.get("redirect_url"),
                        posted_at=_parse_dt(item.get("created")),
                        source_label="Adzuna",
                        raw={"id": job_id},
                    )
                )
        return jobs


class JobicyAdapter(Adapter):
    name = "jobicy"
    label = "Jobicy (remote, Canada)"

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        payload = http.get_json("https://jobicy.com/api/v2/remote-jobs?count=100&geo=canada")
        jobs = []
        for item in payload.get("jobs") or []:
            title = html.unescape(item.get("jobTitle") or "")
            geo = item.get("jobGeo") or ""
            location = f"Remote - {geo}" if geo else "Remote"
            if not plan.title_ok(title) or not plan.location_ok(location, remote_flag=True):
                continue
            level = (item.get("jobLevel") or "").lower()
            hints = {"entry": ["entry"], "midweight": [], "senior": [], "director": []}.get(level, [])
            job_type = " ".join(item.get("jobType") or []) if isinstance(item.get("jobType"), list) else str(item.get("jobType") or "")
            jobs.append(
                NormalizedJob(
                    source="jobicy",
                    external_id=str(item.get("id")),
                    title=title,
                    company=html.unescape(item.get("companyName") or "Company not listed"),
                    description=html_to_text(item.get("jobDescription") or item.get("jobExcerpt") or ""),
                    location=location,
                    work_arrangement="remote",
                    employment_type=detect_employment(f"{title} {job_type}", ""),
                    salary_min=_money(item.get("salaryMin")),
                    salary_max=_money(item.get("salaryMax")),
                    salary_currency=item.get("salaryCurrency"),
                    application_url=item.get("url"),
                    posted_at=_parse_dt(item.get("pubDate")),
                    remote_flag=True,
                    hints=hints,
                    source_label="Jobicy",
                    raw={"id": item.get("id"), "level": level},
                )
            )
            if level in {"senior", "director"} and jobs[-1].title and not re.search(r"senior|director|lead|principal|staff", title, re.I):
                jobs[-1].hints.append("senior")
        return jobs


class HimalayasAdapter(Adapter):
    name = "himalayas"
    label = "Himalayas (remote, open to Canada)"

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        jobs = []
        seen: set[str] = set()
        for term in plan.board_queries(3):
            payload = http.get_json(f"https://himalayas.app/jobs/api/search?q={quote_plus(term)}&country=Canada&limit=20")
            for item in payload.get("jobs") or []:
                guid = str(item.get("guid") or item.get("applicationLink") or item.get("title"))
                if guid in seen:
                    continue
                seen.add(guid)
                title = item.get("title") or ""
                restrictions = item.get("locationRestrictions") or []
                names = [entry.get("name") if isinstance(entry, dict) else str(entry) for entry in restrictions]
                location = "Remote - " + (", ".join(name for name in names if name) or "Worldwide")
                if not plan.title_ok(title) or not plan.location_ok(location, remote_flag=True):
                    continue
                seniority = [str(entry).lower() for entry in item.get("seniority") or []]
                expiry = _parse_dt(item.get("expiryDate"))
                jobs.append(
                    NormalizedJob(
                        source="himalayas",
                        external_id=guid[-120:],
                        title=title,
                        company=item.get("companyName") or "Company not listed",
                        description=html_to_text(item.get("description") or item.get("excerpt") or ""),
                        location=location,
                        work_arrangement="remote",
                        employment_type=detect_employment(f"{title} {item.get('employmentType') or ''}", ""),
                        salary_min=_money(item.get("minSalary")),
                        salary_max=_money(item.get("maxSalary")),
                        salary_currency=item.get("currency"),
                        application_url=item.get("applicationLink") or item.get("guid"),
                        posted_at=_parse_dt(item.get("pubDate")),
                        expires_at=expiry,
                        remote_flag=True,
                        hints=["entry"] if any(level in {"entry-level", "entry level", "junior"} for level in seniority) else [],
                        source_label="Himalayas",
                        raw={"guid": guid},
                    )
                )
        return jobs


class RemotiveAdapter(Adapter):
    """Public Remotive API. Only roles open to candidates in Canada are kept by the default plan."""

    name = "remotive"
    label = "Remotive (remote)"

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        jobs = []
        seen: set[str] = set()
        terms = plan.board_queries(2) if not plan.permissive else (plan.terms[:1] or [""])
        for term in terms:
            url = "https://remotive.com/api/remote-jobs?limit=50"
            if term:
                url += f"&search={quote(term)}"
            payload = http.get_json(url)
            for item in payload.get("jobs") or []:
                job_id = str(item.get("id"))
                if job_id in seen:
                    continue
                seen.add(job_id)
                title = item.get("title") or "Untitled role"
                location = item.get("candidate_required_location") or ""
                if not plan.title_ok(title) or not plan.location_ok(f"Remote - {location}", remote_flag=True):
                    continue
                description = html_to_text(item.get("description") or "")
                salary_min, salary_max = _salary_from_text(item.get("salary") or description)
                jobs.append(
                    NormalizedJob(
                        source="remotive",
                        external_id=job_id,
                        title=title,
                        company=item.get("company_name") or "Company not listed",
                        description=description,
                        location=f"Remote - {location}" if location else "Remote",
                        industry=item.get("category"),
                        work_arrangement="remote",
                        employment_type=(item.get("job_type") or "unknown").lower().replace(" ", "_"),
                        salary_min=salary_min,
                        salary_max=salary_max,
                        salary_currency="USD" if salary_min else None,
                        application_url=item.get("url"),
                        posted_at=_parse_dt(item.get("publication_date")),
                        remote_flag=True,
                        source_label="Remotive",
                        raw={"id": item.get("id")},
                    )
                )
        return jobs


class ArbeitnowAdapter(Adapter):
    """European job board. Off by default because it lists almost no Canadian roles."""

    name = "arbeitnow"
    label = "Arbeitnow (Europe)"

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        payload = http.get_json("https://www.arbeitnow.com/api/job-board-api")
        jobs = []
        for item in payload.get("data") or []:
            title = item.get("title") or "Untitled role"
            location = item.get("location")
            remote = bool(item.get("remote"))
            if not plan.title_ok(title) or not plan.location_ok(location, remote_flag=remote or None):
                continue
            description = html_to_text(item.get("description") or "")
            jobs.append(
                NormalizedJob(
                    source="arbeitnow",
                    external_id=str(item.get("slug") or item.get("url")),
                    title=title,
                    company=item.get("company_name") or "Company not listed",
                    description=description,
                    location=location,
                    work_arrangement="remote" if remote else detect_arrangement(title, f"{location or ''} {description[:300]}"),
                    employment_type=detect_employment(title, description[:300]),
                    application_url=item.get("url"),
                    posted_at=_parse_dt(item.get("created_at")),
                    remote_flag=remote or None,
                    source_label="Arbeitnow",
                    raw={"slug": item.get("slug")},
                )
            )
        return jobs


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------


def _rss_items(text: str) -> list[dict]:
    try:
        # Feeds are third-party data. ElementTree never fetches external entities, and the bundled
        # expat (2.4.1+) limits entity expansion, so billion-laughs payloads fail to parse.
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)  # noqa: S314
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        items.append({child.tag: (child.text or "") for child in item})
    return items


def _atom_entries(text: str) -> list[dict]:
    try:
        # Feeds are third-party data. ElementTree never fetches external entities, and the bundled
        # expat (2.4.1+) limits entity expansion, so billion-laughs payloads fail to parse.
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)  # noqa: S314
    except ET.ParseError:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = []
    for entry in root.findall("a:entry", ns):
        link = entry.find("a:link", ns)
        entries.append(
            {
                "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                "link": link.get("href") if link is not None else "",
                "updated": entry.findtext("a:updated", default="", namespaces=ns),
                "summary": entry.findtext("a:summary", default="", namespaces=ns),
            }
        )
    return entries


# ---------------------------------------------------------------------------
# Sample catalog (demo mode only)
# ---------------------------------------------------------------------------


class DemoCatalogAdapter(Adapter):
    """Explicit sample listings. They are never labeled as live employer posts."""

    name = "sample"
    kind = "sample"
    label = "Practice listings"
    full_catalog = False

    def __init__(self, client=None) -> None:
        super().__init__(client)
        self.jobs = list(SAMPLE_JOBS)

    def fetch(self, plan: SearchPlan, http: Http) -> list[NormalizedJob]:
        return [_from_sample(job) for job in self.jobs]

    def search(self, query: SearchQuery) -> list[NormalizedJob]:
        keywords = query.keywords.lower().strip()
        location = query.location.lower().strip()
        results = []
        for job in self.jobs:
            blob = f"{job['title']} {job['description']} {job['industry']}".lower()
            if keywords and keywords not in blob and not all(part in blob for part in keywords.split()):
                continue
            if location and location not in (job.get("location") or "").lower() and job.get("work_arrangement") != "remote":
                continue
            results.append(_from_sample(job))
        return results


def _from_sample(job: dict) -> NormalizedJob:
    listing = NormalizedJob(
        source="sample",
        external_id=job["id"],
        title=job["title"],
        company=job["company"],
        description=job["description"],
        location=job.get("location"),
        industry=job.get("industry"),
        work_arrangement=job.get("work_arrangement") or "unknown",
        employment_type=job.get("employment_type") or "unknown",
        seniority=job.get("seniority"),
        salary_min=job.get("salary_min"),
        salary_max=job.get("salary_max"),
        salary_currency="USD" if job.get("salary_min") else None,
        application_url=job.get("application_url"),
        is_sample=True,
        source_label="Practice listing",
        raw={"sample": True},
    )
    return listing


SAMPLE_JOBS = [
    {
        "id": "sample-software-engineer",
        "title": "Software Engineer",
        "company": "Harbor Systems",
        "industry": "Software",
        "location": "San Francisco, CA",
        "work_arrangement": "hybrid",
        "employment_type": "full_time",
        "seniority": "mid",
        "salary_min": 140000,
        "salary_max": 170000,
        "application_url": "https://example.com/jobs/harbor-software-engineer",
        "description": """Harbor Systems builds search infrastructure.

Responsibilities
- Design and maintain backend services
- Collaborate with product and design

Requirements
- Python
- SQL
- Docker
- REST APIs
- 2+ years of professional experience

Preferred
- AWS experience is a plus
- Kubernetes
""",
    },
    {
        "id": "sample-senior-backend",
        "title": "Senior Backend Engineer",
        "company": "Northline",
        "industry": "Software",
        "location": "Remote",
        "work_arrangement": "remote",
        "employment_type": "full_time",
        "seniority": "senior",
        "salary_min": 180000,
        "salary_max": 210000,
        "application_url": "https://example.com/jobs/northline-senior-backend",
        "description": """Requirements
- 7+ years of professional experience
- Python
- PostgreSQL
- AWS
- Must be authorized to work in the United States
Preferred
- Kubernetes
""",
    },
    {
        "id": "sample-transport-intern",
        "title": "Transportation Engineering Intern",
        "company": "Cedar Mobility",
        "industry": "Transportation",
        "location": "Austin, TX",
        "work_arrangement": "hybrid",
        "employment_type": "internship",
        "seniority": "intern",
        "salary_min": 28,
        "salary_max": 35,
        "application_url": "https://example.com/jobs/cedar-intern",
        "description": """Requirements
- Progress toward a bachelor's degree in civil engineering
- Interest in transportation engineering
- Excel
Preferred
- AutoCAD
- GIS
""",
    },
    {
        "id": "sample-entry-civil",
        "title": "Entry-level Civil Engineer",
        "company": "Cedar Mobility",
        "industry": "Civil Engineering",
        "location": "Austin, TX",
        "work_arrangement": "onsite",
        "employment_type": "full_time",
        "seniority": "entry",
        "salary_min": 70000,
        "salary_max": 82000,
        "application_url": "https://example.com/jobs/cedar-entry",
        "description": """Requirements
- Bachelor's degree in civil engineering
- AutoCAD
- Transportation engineering coursework or internship experience
Preferred
- Civil 3D
""",
    },
    {
        "id": "sample-senior-transport",
        "title": "Senior Transportation Engineer",
        "company": "Cedar Mobility",
        "industry": "Transportation",
        "location": "Austin, TX",
        "work_arrangement": "onsite",
        "employment_type": "full_time",
        "seniority": "senior",
        "salary_min": 130000,
        "salary_max": 155000,
        "application_url": "https://example.com/jobs/cedar-senior",
        "description": """Requirements
- Bachelor's degree in civil engineering
- 8+ years of professional experience
- Transportation engineering
- AutoCAD
- Professional engineering license
Preferred
- Civil 3D
""",
    },
    {
        "id": "sample-data-analyst",
        "title": "Data Analyst",
        "company": "Lumen Retail",
        "industry": "Retail",
        "location": "Chicago, IL",
        "work_arrangement": "hybrid",
        "employment_type": "full_time",
        "seniority": "entry",
        "salary_min": 75000,
        "salary_max": 95000,
        "application_url": "https://example.com/jobs/lumen-analyst",
        "description": """Requirements
- SQL
- Excel
- Python
Preferred
- Familiarity with other visualization tools
""",
    },
]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ATS_ADAPTERS = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workday": WorkdayAdapter,
    "successfactors": SuccessFactorsAdapter,
    "amazon": AmazonAdapter,
    "ibm": IBMAdapter,
    "jibe": JibeAdapter,
}

BOARD_SOURCES = {
    "jobbank": {"label": "Job Bank (Government of Canada)", "description": "Federal job board. Searched around your city.", "default": True},
    "adzuna": {"label": "Adzuna Canada", "description": "Large Canadian aggregator. Needs a free API key.", "default": True, "needs_key": True},
    "jobicy": {"label": "Jobicy", "description": "Remote roles open to Canada.", "default": True},
    "himalayas": {"label": "Himalayas", "description": "Remote roles that accept Canadian residents.", "default": True},
    "remotive": {"label": "Remotive", "description": "Remote roles. Only those open to Canada are kept.", "default": True},
    "arbeitnow": {"label": "Arbeitnow", "description": "European board. Off by default.", "default": False},
}


def adapter_for_employer(employer: Employer, client=None) -> Adapter | None:
    cls = ATS_ADAPTERS.get(employer.ats)
    if cls is None:
        return None
    return cls(employer, client=client)


def board_adapter(key: str, settings: Settings, client=None) -> Adapter | None:
    if key == "jobbank":
        return JobBankAdapter(client)
    if key == "adzuna":
        return AdzunaAdapter(settings, client) if settings.adzuna_configured else None
    if key == "jobicy":
        return JobicyAdapter(client)
    if key == "himalayas":
        return HimalayasAdapter(client)
    if key == "remotive":
        return RemotiveAdapter(client)
    if key == "arbeitnow":
        return ArbeitnowAdapter(client)
    return None
