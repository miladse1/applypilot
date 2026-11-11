"""Relevance taxonomy for job discovery.

Classifies a posting's role family, career level, and location tier so search
results can be filtered and ranked for a student or early-career candidate.
Everything here is deterministic and explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Role families
# ---------------------------------------------------------------------------

ROLE_FAMILIES: dict[str, dict] = {
    "software": {
        "label": "Software Engineering & Development",
        "search_terms": ["software engineer", "software developer"],
        "patterns": [
            r"\bsoftware\b.*\b(engineer|engineering|developer|development|dev|programmer)\b",
            r"\b(swe|sde|sdet)\b",
            r"\bsoftware development engineer\b",
            r"\bapplication(s)? (developer|engineer)\b",
            r"\bweb (developer|engineer)\b",
            r"\b(java|python|c\+\+|c#|\.net|golang|go|ruby|rust|scala|kotlin|php|typescript|javascript)\s+(developer|engineer|programmer)\b",
            r"\bprogrammer( analyst)?\b",
            r"\bdeveloper\b",
            r"\bcomputer programmer\b",
            r"\bsystems? developer\b",
            r"\bd[ée]veloppeu(r|se)\b",
            r"\bing[ée]nieur(e)? (logiciel|en logiciel)",
        ],
    },
    "backend": {
        "label": "Backend Development",
        "search_terms": ["backend developer"],
        "patterns": [r"\bback[- ]?end\b", r"\bapi (developer|engineer)\b", r"\bserver[- ]side\b"],
    },
    "full_stack": {
        "label": "Full-Stack Development",
        "search_terms": ["full stack developer"],
        "patterns": [r"\bfull[- ]?stack\b"],
    },
    "frontend": {
        "label": "Frontend Development",
        "search_terms": ["frontend developer"],
        "patterns": [r"\bfront[- ]?end\b", r"\bui (developer|engineer)\b", r"\breact (developer|engineer)\b"],
    },
    "data_engineering": {
        "label": "Data Engineering",
        "search_terms": ["data engineer"],
        "patterns": [
            r"\bdata engineer",
            r"\bdata (platform|infrastructure|pipeline|integration|warehouse|warehousing) (engineer|developer)",
            r"\b(etl|elt) (developer|engineer)\b",
            r"\bbig data\b",
            r"\banalytics engineer",
            r"\bdatabase (developer|engineer|administrator)\b",
            r"\bdata ?ops\b",
        ],
    },
    "data_science": {
        "label": "Data Science",
        "search_terms": ["data scientist"],
        "patterns": [r"\bdata scien", r"\bapplied scien", r"\bresearch scientist\b", r"\bquantitative (analyst|developer|researcher)\b", r"\bstatistician\b"],
    },
    "data_analytics": {
        "label": "Data & Business Analytics",
        "search_terms": ["data analyst"],
        "patterns": [
            r"\bdata analy",
            r"\bbusiness intelligence\b",
            r"\bbi (analyst|developer|engineer)\b",
            r"\banalytics\b",
            r"\breporting analyst\b",
            r"\binsights? analyst\b",
            r"\bdata (specialist|associate|management)\b",
            r"\banalyste (de|des) donn[ée]es\b",
        ],
    },
    "ml_ai": {
        "label": "AI & Machine Learning",
        "search_terms": ["machine learning", "AI engineer"],
        "patterns": [
            r"\bmachine learning\b",
            r"\bml\b",
            r"\bmlops\b",
            r"\b(ai|a\.i\.)\b",
            r"\bartificial intelligence\b",
            r"\bdeep learning\b",
            r"\bcomputer vision\b",
            r"\bnlp\b",
            r"\bnatural language\b",
            r"\bllm",
            r"\bgen ?ai\b",
            r"\bgenerative\b",
        ],
    },
    "cloud_devops": {
        "label": "Cloud, DevOps & Infrastructure",
        "search_terms": ["cloud engineer", "devops"],
        "patterns": [
            r"\bcloud\b.*\b(engineer|developer|specialist|analyst|associate|operations)\b",
            r"\bdev ?ops\b",
            r"\bdevsecops\b",
            r"\bsite reliability\b",
            r"\bsre\b",
            r"\bplatform engineer",
            r"\binfrastructure (engineer|developer|analyst)\b",
            r"\bproduction engineer",
            r"\bkubernetes\b",
            r"\bsystems? (engineer|administrator)\b",
        ],
    },
    "mobile": {
        "label": "Mobile Development",
        "search_terms": ["mobile developer"],
        "patterns": [r"\b(ios|android|mobile)\b.*\b(developer|engineer)\b", r"\bflutter\b", r"\breact native\b"],
    },
    "qa_automation": {
        "label": "QA & Test Automation",
        "search_terms": ["QA automation"],
        "patterns": [r"\b(qa|quality assurance|test|testing)\b.*\b(engineer|developer|analyst|automation)\b", r"\bautomation (engineer|developer|tester)\b"],
    },
    "security": {
        "label": "Cybersecurity",
        "search_terms": ["security analyst"],
        "patterns": [r"\b(cyber ?security|information security|security)\b.*\b(engineer|analyst|developer|specialist)\b", r"\bsoc analyst\b", r"\bpenetration\b"],
    },
    "it_support": {
        "label": "IT & Technical Support",
        "search_terms": ["IT support"],
        "patterns": [r"\b(it|technical|desktop|help ?desk|service desk)\b.*\b(support|analyst|technician|specialist)\b"],
    },
    "technology_general": {
        "label": "General technology co-op / intern",
        "search_terms": [],
        "patterns": [
            r"\b(technology|tech|it|digital|engineering|computer|computing|cyber|systems|automation|innovation|developer|programming|stem)\b",
        ],
    },
}

DEFAULT_FAMILIES = [
    "software",
    "backend",
    "full_stack",
    "data_engineering",
    "data_science",
    "data_analytics",
    "ml_ai",
    "cloud_devops",
]

# Titles that look technical but are not software or data work.
_NON_SOFTWARE_ENGINEERING = re.compile(
    r"\b(mechanical|civil|electrical|chemical|structural|mining|geotechnical|environmental|manufacturing|"
    r"process|industrial|hardware|rf|analog|asic|fpga|silicon|electronics|nuclear|petroleum|aerospace|"
    r"biomedical|automotive technician|field service|construction|hvac|plumbing|millwright|welding|"
    r"layout|physical design|verification engineer|validation engineer|packaging|thermal|optical|photonics)\b",
    re.I,
)
_NON_TECH = re.compile(
    r"\b(sales|account (manager|executive|specialist)|business development|marketing (manager|specialist|coordinator)|"
    r"recruit(er|ing|ment)|talent acquisition|customer (service|success|care|experience) (representative|associate|specialist|advisor|agent)|"
    r"nurse|teller|branch|financial (advisor|planner)|mortgage|insurance (agent|advisor|broker)|cashier|warehouse|driver|"
    r"underwriter|actuar|accountant|accounting|auditor|tax|legal|lawyer|counsel|paralegal|human resources|payroll|retail|"
    r"store|merchandis|copywriter|writer|designer|interior|real estate|property|leasing|wealth|investment advisor|"
    r"client (service|associate)|call cent|administrative|receptionist|office assistant|bookkeep|chef|cook|"
    r"physician|pharmac|therap|dental|veterinar|teacher|tutor|coach|trainer|translator|interpreter|data entry|"
    r"solutions consultant|presales|pre-sales|sales engineer|business developer|property developer|real estate developer|"
    r"curriculum developer|content developer|instructional|learning experience|course developer)\b",
    re.I,
)
_STRONG_TECH = re.compile(
    r"\b(software|developer|programmer|data|machine learning|ml|ai|cloud|devops|backend|back-end|full[- ]?stack|"
    r"frontend|front-end|engineer(ing)? (intern|co-?op|student)|analytics|sre|platform)\b",
    re.I,
)


def classify_role(title: str, description: str = "") -> dict:
    """Return the matched role families for a title, strongest first."""
    lowered = _normalize_title(title)
    families: list[str] = []
    # Specific families first so "Full Stack Developer" reads as full-stack, not generic software.
    order = [key for key in ROLE_FAMILIES if key not in {"software", "technology_general"}] + ["software"]
    for key in order:
        meta = ROLE_FAMILIES[key]
        if any(re.search(pattern, lowered) for pattern in meta["patterns"]):
            families.append(key)
    # "developer" alone is weak evidence. Drop it when the title is clearly non-technical.
    non_tech = bool(_NON_TECH.search(lowered))
    non_software = bool(_NON_SOFTWARE_ENGINEERING.search(lowered))
    strong = bool(_STRONG_TECH.search(lowered))
    if non_tech and not re.search(r"\b(software|data (engineer|scien|analy)|machine learning|developer)\b", lowered):
        families = []
    if non_tech and families == ["software"] and re.search(r"\b(business|property|real estate|curriculum|content|course)\s+develop", lowered):
        families = []
    if non_software and not re.search(r"\b(software|data|machine learning|cloud|devops|developer|programmer)\b", lowered):
        families = []
    # "ai" and "analytics" alone can be marketing words. Require an occupational noun.
    if families and set(families) <= {"ml_ai", "data_analytics"} and not re.search(
        r"\b(engineer|engineering|developer|scientist|analyst|researcher|specialist|intern|co-?op|student|associate|architect|lead)\b",
        lowered,
    ):
        families = []
    if not families and is_student_title(lowered) and not non_tech and not non_software:
        if re.search(ROLE_FAMILIES["technology_general"]["patterns"][0], lowered):
            families = ["technology_general"]
        elif description and _tech_density(description) >= 4:
            # Generic titles like "Intern/Co-op Winter 2027" are judged by the description.
            families = ["technology_general"]
    return {"families": families, "primary": families[0] if families else None, "strong": strong and bool(families)}


_TECH_WORDS = re.compile(
    r"\b(python|java|javascript|typescript|sql|software|programming|developer|coding|code|api|cloud|aws|azure|gcp|"
    r"data pipeline|machine learning|computer science|computer engineering|software engineering|git|react|database|devops|"
    r"kubernetes|docker|linux|algorithms)\b",
    re.I,
)


def _tech_density(description: str) -> int:
    return len({match.group(0).lower() for match in _TECH_WORDS.finditer(description[:3000])})


def _normalize_title(title: str) -> str:
    text = (title or "").lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[\(\)\[\]|/,:]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Career level
# ---------------------------------------------------------------------------

LEVELS = {
    "intern": "Internship / Co-op / Student",
    "new_grad": "New Graduate",
    "entry": "Entry Level / Junior",
    "unspecified": "Level not stated",
    "mid": "Intermediate",
    "senior": "Senior",
    "lead": "Lead / Staff / Principal",
    "manager": "Management",
}
DEFAULT_LEVELS = ["intern", "new_grad", "entry", "unspecified"]

_INTERN_RE = re.compile(
    r"\b(intern(ship)?s?|co-?op|coop|work[- ]term|student|summer (analyst|associate|student|technology)|placement|apprentice(ship)?|trainee|pey|stagiaire|stage|étudiant(e)?|etudiant(e)?)\b",
    re.I,
)
_NEW_GRAD_RE = re.compile(
    r"\b(new[- ]?grad(uate)?s?|recent grad(uate)?s?|university grad(uate)?s?|campus|graduate (program|programme|engineer|developer|analyst|scientist|role|opportunit)|"
    r"early[- ]career|early talent|entry[- ]level program|rotational|leadership development program|(?:20)\d\d (start|grad|graduate))\b",
    re.I,
)
_ENTRY_RE = re.compile(
    r"\b(junior|jr\.?|entry[- ]level|entry|associate (software|data|developer|engineer|analyst|scientist|cloud|machine|technology|application|systems|devops|platform|backend|full)|"
    r"(engineer|developer|analyst|scientist|programmer|specialist)\s+(i|1)\b|level (i|1)\b|graduate)\b",
    re.I,
)
_MID_RE = re.compile(r"\b(intermediate|mid[- ]level|(engineer|developer|analyst|scientist|programmer|specialist)\s+(ii|2)\b|level (ii|2)\b)", re.I)
_SENIOR_RE = re.compile(r"\b(senior|sr\.?|snr|(engineer|developer|analyst|scientist|programmer)\s+(iii|3|iv|4|v|5)\b|level (iii|3|iv|4)\b|expert|experienced)\b", re.I)
_LEAD_RE = re.compile(r"\b(lead|staff|principal|principale|distinguished|fellow|architect|architecte)\b", re.I)
_MANAGER_RE = re.compile(r"\b(manager|management|director|head of|head,|vp|vice president|chief|cto|cio|avp|svp|evp|managing|supervisor|mgr|dir|gestionnaire|directeur|directrice|chef)\b", re.I)

_YEARS_RE = re.compile(
    r"(?:minimum of |at least |min\.? )?(\d{1,2})\s*(?:\+|plus)?\s*(?:-|to|–)?\s*(\d{1,2})?\s*\+?\s*(?:years|yrs|ans)\b(?:\s+of|\s+d'|\s+de)?(?:\s+[\w/-]+){0,6}?\s+(?:experience|expérience|exp\.?)",
    re.I,
)


def is_student_title(text: str) -> bool:
    return bool(_INTERN_RE.search(text) or _NEW_GRAD_RE.search(text))


def required_years(description: str) -> int | None:
    """Smallest years-of-experience requirement stated in the description."""
    found: list[int] = []
    for match in _YEARS_RE.finditer(description or ""):
        value = int(match.group(1))
        if 0 <= value <= 20:
            found.append(value)
    if not found:
        return None
    return min(found)


def classify_level(title: str, description: str = "", hints: list[str] | None = None) -> dict:
    lowered = _normalize_title(title)
    hints = [item.lower() for item in hints or []]
    years = required_years(description)
    level = "unspecified"
    reason = "The posting does not state a level."
    if _INTERN_RE.search(lowered):
        level, reason = "intern", "The title names an internship, co-op, or student role."
    elif _NEW_GRAD_RE.search(lowered):
        level, reason = "new_grad", "The title targets new or recent graduates."
    elif _MANAGER_RE.search(lowered) and not re.search(r"\bproduct manager intern\b", lowered):
        level, reason = "manager", "The title is a management role."
    elif _LEAD_RE.search(lowered):
        level, reason = "lead", "The title is a lead, staff, principal, or architect role."
    elif _SENIOR_RE.search(lowered):
        level, reason = "senior", "The title is a senior role."
    elif _ENTRY_RE.search(lowered):
        level, reason = "entry", "The title is junior, entry level, or level I."
    elif _MID_RE.search(lowered):
        level, reason = "mid", "The title is an intermediate (level II) role."
    elif any(hint in {"campus", "university", "student", "early career", "graduate"} for hint in hints):
        level, reason = "new_grad", "The employer files this role under campus or early-career hiring."
    if level == "unspecified" and description:
        head = description[:4000].lower()
        if re.search(r"\b(new grad|recent graduate|graduating in|entry[- ]level|0-2 years|0 to 2 years|no experience required)\b", head):
            level, reason = "entry", "The description says the role is open to new graduates or entry-level candidates."
        elif years is not None:
            if years >= 5:
                level, reason = "senior", f"The description asks for {years}+ years of experience."
            elif years >= 3:
                level, reason = "mid", f"The description asks for {years}+ years of experience."
            else:
                level, reason = "entry", f"The description asks for {years} year(s) of experience or less."
    elif level == "entry" and years is not None and years >= 4:
        level, reason = "mid", f"The title reads junior, but the description asks for {years}+ years."
    return {"level": level, "reason": reason, "years": years}


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

GTA_CITIES = {
    "toronto", "north york", "scarborough", "etobicoke", "east york", "york", "downtown toronto", "mississauga",
    "brampton", "caledon", "bolton", "markham", "unionville", "vaughan", "woodbridge", "concord", "maple", "thornhill",
    "richmond hill", "aurora", "newmarket", "king city", "king", "stouffville", "whitchurch-stouffville", "east gwillimbury",
    "georgina", "pickering", "ajax", "whitby", "oshawa", "clarington", "bowmanville", "courtice", "uxbridge", "oakville",
    "burlington", "milton", "halton hills", "georgetown", "acton", "bradford", "bradford west gwillimbury", "hamilton",
    "gta", "greater toronto area", "greater toronto", "toronto area", "tor", "yyz",
}
ONTARIO_CITIES = {
    "waterloo", "kitchener", "cambridge", "guelph", "barrie", "ottawa", "kanata", "nepean", "london", "windsor", "kingston",
    "st. catharines", "st catharines", "niagara falls", "niagara", "welland", "brantford", "peterborough", "sudbury",
    "greater sudbury", "thunder bay", "sault ste. marie", "north bay", "sarnia", "belleville", "cobourg", "orillia",
    "collingwood", "woodstock", "stratford", "chatham", "cornwall", "timmins", "orangeville", "innisfil", "alliston",
    "owen sound", "midland", "grimsby", "lindsay", "port hope", "trenton", "pembroke", "ancaster", "dundas", "stoney creek",
}
OTHER_CANADA_CITIES = {
    "vancouver", "burnaby", "surrey", "victoria", "kelowna", "coquitlam", "langley", "abbotsford", "nanaimo", "calgary",
    "edmonton", "red deer", "lethbridge", "regina", "saskatoon", "winnipeg", "montreal", "montréal", "laval", "longueuil",
    "quebec city", "québec", "quebec", "gatineau", "sherbrooke", "trois-rivières", "halifax", "dartmouth", "moncton",
    "fredericton", "saint john", "st. john's", "st john's", "charlottetown", "whitehorse", "yellowknife", "iqaluit",
    "dollard-des-ormeaux", "brossard", "terrebonne", "lévis", "saguenay",
}
_GTA_PREFIXES = ("toronto", "mississauga", "markham", "vaughan", "brampton", "oakville", "north york", "richmond hill")
_GTA_SEARCH = ("toronto", "mississauga", "markham", "vaughan", "brampton", "oakville", "north york", "scarborough", "etobicoke", "richmond hill")
PROVINCES = {
    "on": "ontario", "ontario": "ontario",
    "bc": "british columbia", "british columbia": "british columbia",
    "ab": "alberta", "alberta": "alberta",
    "sk": "saskatchewan", "saskatchewan": "saskatchewan",
    "mb": "manitoba", "manitoba": "manitoba",
    "qc": "quebec", "quebec": "quebec", "québec": "quebec",
    "nb": "new brunswick", "new brunswick": "new brunswick",
    "ns": "nova scotia", "nova scotia": "nova scotia",
    "pe": "prince edward island", "pei": "prince edward island", "prince edward island": "prince edward island",
    "nl": "newfoundland and labrador", "newfoundland": "newfoundland and labrador", "newfoundland and labrador": "newfoundland and labrador",
    "yt": "yukon", "yukon": "yukon", "nt": "northwest territories", "northwest territories": "northwest territories",
    "nu": "nunavut", "nunavut": "nunavut",
}
US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
}
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland",
    "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}
US_CITIES = {
    "new york", "san francisco", "seattle", "austin", "boston", "chicago", "los angeles", "denver", "atlanta",
    "mountain view", "sunnyvale", "san jose", "palo alto", "menlo park", "redmond", "cupertino", "santa clara", "dallas",
    "houston", "miami", "philadelphia", "pittsburgh", "detroit", "warren", "milford", "phoenix", "portland",
    "salt lake city", "las vegas", "san diego", "raleigh", "nashville", "minneapolis", "washington dc", "arlington",
}
INTERNATIONAL_MARKERS = re.compile(
    r"\b(united kingdom|uk|england|scotland|wales|ireland|dublin|belfast|germany|deutschland|berlin|munich|münchen|hamburg|"
    r"frankfurt|france|paris|spain|madrid|barcelona|italy|rome|milan|netherlands|amsterdam|belgium|switzerland|zurich|"
    r"austria|vienna|poland|warsaw|krakow|portugal|lisbon|sweden|stockholm|norway|denmark|copenhagen|finland|czech|"
    r"prague|romania|bucharest|hungary|greece|turkey|istanbul|israel|tel aviv|india|bangalore|bengaluru|hyderabad|pune|"
    r"chennai|mumbai|delhi|gurgaon|noida|singapore|malaysia|kuala lumpur|philippines|manila|makati|indonesia|jakarta|"
    r"vietnam|thailand|bangkok|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|japan|tokyo|korea|seoul|australia|"
    r"sydney|melbourne|new zealand|auckland|brazil|são paulo|sao paulo|mexico|mexico city|guadalajara|argentina|buenos aires|"
    r"colombia|bogota|bogotá|chile|santiago|peru|lima|costa rica|south africa|nigeria|kenya|egypt|uae|dubai|saudi|qatar|"
    r"pakistan|emea|apac|europe|latam|asia)\b",
    re.I,
)
_REMOTE_RE = re.compile(r"\b(remote|anywhere|work from home|wfh|telecommute|télétravail|virtual|distributed|home[- ]based)\b", re.I)
_WORLDWIDE_RE = re.compile(r"\b(worldwide|world ?wide|anywhere|global(ly)?|international)\b", re.I)
_NA_RE = re.compile(r"\b(north america|northern america|americas)\b", re.I)
_CANADA_RE = re.compile(r"\b(canada|canadian|can)\b", re.I)
_US_RE = re.compile(r"\b(united states|usa|u\.s\.a?\.?|us|america)\b", re.I)

LOCATION_SCOPES = {
    "gta": "Toronto & GTA",
    "ontario": "Elsewhere in Ontario",
    "remote_canada": "Remote (Canada)",
    "remote_north_america": "Remote (US & Canada)",
    "remote_worldwide": "Remote (worldwide)",
    "canada_other": "Elsewhere in Canada",
    "remote_us": "Remote (US only)",
    "united_states": "United States (on-site)",
    "international": "Outside North America",
    "unknown": "Location unclear",
}
DEFAULT_SCOPES = ["gta", "ontario", "remote_canada", "remote_north_america", "remote_worldwide"]
SCOPE_ORDER = {
    "gta": 0,
    "ontario": 1,
    "remote_canada": 2,
    "remote_north_america": 3,
    "remote_worldwide": 4,
    "canada_other": 5,
    "remote_us": 6,
    "united_states": 7,
    "unknown": 8,
    "international": 9,
}


@dataclass
class LocationInfo:
    scope: str
    is_remote: bool
    city: str | None = None
    province: str | None = None
    country: str | None = None
    label: str = ""
    notes: list[str] = field(default_factory=list)


def _split_locations(text: str) -> list[str]:
    parts = re.split(r"\s*(?:;|\||/| or | and |\n)\s*", text)
    return [part.strip() for part in parts if part and part.strip()]


def _single_place(part: str) -> dict:
    """Classify one location string such as 'Toronto, ON' or 'Remote - Canada'."""
    lowered = part.lower().replace("–", "-").replace("—", "-")
    lowered = re.sub(r"\s+", " ", lowered).strip()
    tokens = [token.strip(" .") for token in re.split(r"[,\-():]", lowered) if token.strip(" .")]
    result = {"country": None, "province": None, "city": None}
    for token in tokens:
        bare = token.strip()
        prefix = next((city for city in _GTA_PREFIXES if bare.startswith(city + " ")), None)
        if bare in GTA_CITIES or prefix:
            result["city"] = result["city"] or (bare if bare in GTA_CITIES else prefix)
            result["province"] = result["province"] or "ontario"
            result["country"] = "canada"
        elif bare in ONTARIO_CITIES and bare != "london":
            result["city"] = result["city"] or bare
            result["province"] = result["province"] or "ontario"
            result["country"] = "canada"
        elif bare in OTHER_CANADA_CITIES:
            result["city"] = result["city"] or bare
            result["country"] = "canada"
    # Province codes and names
    for token in tokens:
        bare = token.strip()
        if bare in PROVINCES and not (bare == "ca"):
            if bare in {"in", "me", "pe"} and result["country"] != "canada":
                continue
            result["province"] = PROVINCES[bare]
            result["country"] = "canada"
    if re.search(r"\bcanada\b|\bcan\b", lowered):
        result["country"] = "canada"
    if result["country"] is None:
        state_hit = any(token in US_STATES for token in tokens[1:]) or any(name in lowered for name in US_STATE_NAMES)
        city_hit = any(city in lowered for city in US_CITIES)
        if state_hit or city_hit or re.search(r"\b(united states|usa|u\.s\.)\b", lowered) or re.search(r"(^|[\s,])us($|[\s,])", lowered):
            # "Markham, CA" means Canada when the city is Canadian; it was caught above.
            result["country"] = "united_states"
    if result["country"] is None and "london" in tokens and re.search(r"\b(on|ontario)\b", lowered):
        result.update(city="london", province="ontario", country="canada")
    if result["country"] is None:
        # Addresses such as "RBC CENTRE, 155 WELLINGTON ST W:TORONTO".
        city = next((name for name in _GTA_SEARCH if re.search(rf"\b{re.escape(name)}\b", lowered)), None)
        if city:
            result.update(city=city, province="ontario", country="canada")
    if result["country"] is None and INTERNATIONAL_MARKERS.search(lowered):
        result["country"] = "international"
    if result["country"] is None and "london" in tokens:
        result["country"] = "international"
    return result


def classify_location(location: str | None, description: str = "", *, remote_flag: bool | None = None, company_country: str | None = None) -> LocationInfo:
    raw = (location or "").strip()
    text = raw.lower()
    head = (description or "")[:1500].lower()
    is_remote = bool(remote_flag) or bool(_REMOTE_RE.search(text))
    if not raw and remote_flag is None and _REMOTE_RE.search(head[:400]):
        is_remote = True
    places = [_single_place(part) for part in _split_locations(raw)] if raw else []
    countries = {place["country"] for place in places if place["country"]}
    provinces = {place["province"] for place in places if place["province"]}
    gta_city = next((place["city"] for place in places if place["city"] in GTA_CITIES), None)
    ontario_city = next((place["city"] for place in places if place["province"] == "ontario"), None)
    canada_city = next((place["city"] for place in places if place["country"] == "canada" and place["city"]), None)

    if is_remote:
        scope_text = f"{text} {head}" if not countries else text
        if "canada" in countries or _CANADA_RE.search(text) or provinces:
            scope = "remote_canada"
        elif _NA_RE.search(text):
            scope = "remote_north_america"
        elif _WORLDWIDE_RE.search(text):
            scope = "remote_worldwide"
        elif "united_states" in countries or _US_RE.search(text):
            scope = "remote_north_america" if re.search(r"\b(canada|canadian)\b", head) else "remote_us"
        elif "international" in countries:
            scope = "international"
        elif re.search(r"\b(canada|canadian)\b", head):
            scope = "remote_canada"
        elif company_country == "canada":
            scope = "remote_canada"
        else:
            scope = "unknown"
        del scope_text
        label = raw or "Remote"
        return LocationInfo(scope=scope, is_remote=True, city=None, province=None, country="canada" if scope == "remote_canada" else None, label=label)

    if gta_city:
        return LocationInfo(scope="gta", is_remote=False, city=gta_city, province="ontario", country="canada", label=raw)
    if ontario_city or "ontario" in provinces:
        return LocationInfo(scope="ontario", is_remote=False, city=ontario_city, province="ontario", country="canada", label=raw)
    if "canada" in countries:
        return LocationInfo(scope="canada_other", is_remote=False, city=canada_city, province=next(iter(provinces), None), country="canada", label=raw)
    if "united_states" in countries:
        return LocationInfo(scope="united_states", is_remote=False, country="united_states", label=raw)
    if "international" in countries:
        return LocationInfo(scope="international", is_remote=False, country="international", label=raw)
    # Nothing parseable. Look in the description for a city.
    if head:
        if re.search(r"\btoronto\b|\bgta\b|\bmississauga\b|\bmarkham\b|\bvaughan\b", head):
            return LocationInfo(scope="gta", is_remote=False, city="toronto", province="ontario", country="canada", label=raw or "Toronto (from description)", notes=["Location taken from the description."])
        if re.search(r"\bontario\b", head):
            return LocationInfo(scope="ontario", is_remote=False, province="ontario", country="canada", label=raw or "Ontario (from description)", notes=["Location taken from the description."])
    if company_country == "canada" and not raw:
        return LocationInfo(scope="canada_other", is_remote=False, country="canada", label="Canada", notes=["The employer is Canadian. The posting does not name a city."])
    return LocationInfo(scope="unknown", is_remote=False, label=raw or "Location not listed")


# ---------------------------------------------------------------------------
# Freshness and ranking
# ---------------------------------------------------------------------------


def age_days(posted_at: datetime | None) -> int | None:
    if posted_at is None:
        return None
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - posted_at).days)


def relevance_score(
    *,
    families: list[str],
    wanted_families: list[str],
    level: str,
    wanted_levels: list[str],
    scope: str,
    posted_at: datetime | None,
    skill_overlap: float = 0.0,
) -> tuple[int, list[str]]:
    """Score 0-100 with the reasons that produced it."""
    reasons: list[str] = []
    score = 0.0
    wanted = set(wanted_families or DEFAULT_FAMILIES)
    if families and families[0] in wanted:
        score += 30
        reasons.append(f"{ROLE_FAMILIES[families[0]]['label']} role")
    elif set(families) & wanted:
        score += 24
        hit = next(item for item in families if item in wanted)
        reasons.append(f"Related to {ROLE_FAMILIES[hit]['label']}")
    elif "technology_general" in families:
        score += 18
        reasons.append("Technology co-op or internship")
    elif families:
        score += 8
    level_points = {"intern": 25, "new_grad": 25, "entry": 22, "unspecified": 12, "mid": 5, "senior": 0, "lead": 0, "manager": 0}
    points = level_points.get(level, 0)
    if wanted_levels and level not in wanted_levels:
        points = min(points, 5)
    score += points
    if level in {"intern", "new_grad", "entry"}:
        reasons.append(LEVELS[level])
    scope_points = {"gta": 25, "ontario": 18, "remote_canada": 21, "remote_north_america": 15, "remote_worldwide": 11, "canada_other": 8, "remote_us": 3, "united_states": 1, "unknown": 2, "international": 0}
    score += scope_points.get(scope, 0)
    if scope in {"gta", "ontario", "remote_canada"}:
        reasons.append(LOCATION_SCOPES[scope])
    age = age_days(posted_at)
    if age is None:
        score += 3
    elif age <= 3:
        score += 10
        reasons.append("Posted in the last 3 days")
    elif age <= 7:
        score += 8
        reasons.append("Posted this week")
    elif age <= 14:
        score += 6
    elif age <= 30:
        score += 4
    elif age <= 60:
        score += 1
    score += max(0.0, min(1.0, skill_overlap)) * 10
    if skill_overlap >= 0.5:
        reasons.append("Strong overlap with your skills")
    return int(round(min(100, score))), reasons


def search_terms(families: list[str], levels: list[str], *, budget: int = 8) -> list[str]:
    """Keyword queries for sources that require search text, most specific first."""
    families = [item for item in (families or DEFAULT_FAMILIES) if item in ROLE_FAMILIES and ROLE_FAMILIES[item]["search_terms"]]
    level_words: list[str] = []
    if "intern" in levels:
        level_words.extend(["intern", "co-op"])
    if "new_grad" in levels:
        level_words.append("new grad")
    if "entry" in levels:
        level_words.append("junior")
    terms: list[str] = []
    base = [term for family in families for term in ROLE_FAMILIES[family]["search_terms"][:1]]
    for word in level_words[:2]:
        for term in base:
            terms.append(f"{term} {word}")
    terms.extend(base)
    seen: set[str] = set()
    ordered = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    # Interleave so a small budget still covers several families.
    return ordered[:budget]
