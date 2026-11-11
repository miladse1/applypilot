"""Employers monitored directly through their public career-site feeds.

Each entry was checked against the live public endpoint. Users can switch any of
these off and add their own by pasting a careers URL (see parse_careers_url).
Large employers without a public feed are offered as saved-search links instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class Employer:
    key: str
    name: str
    ats: str  # greenhouse | lever | ashby | workday | successfactors | amazon | ibm | jibe
    board: str = ""  # board slug, Workday tenant, or host
    site: str = ""  # Workday site name
    wd: int = 0  # Workday data center number (wd1, wd3, wd5...)
    country: str | None = None  # "canada" when the employer hires mainly in Canada
    tags: tuple[str, ...] = field(default_factory=tuple)
    careers_url: str = ""

    @property
    def source_key(self) -> str:
        return f"{self.ats}:{self.key}"


EMPLOYERS: list[Employer] = [
    # Canadian banks and insurers (Workday and SuccessFactors career sites)
    Employer("td", "TD Bank", "workday", "td", "TD_Bank_Careers", 3, "canada", ("bank",), "https://td.wd3.myworkdayjobs.com/TD_Bank_Careers"),
    Employer("rbc", "RBC", "workday", "rbc", "RBCGLOBAL1", 3, "canada", ("bank",), "https://jobs.rbc.com"),
    Employer("bmo", "BMO", "workday", "bmo", "External", 3, "canada", ("bank",), "https://bmo.wd3.myworkdayjobs.com/External"),
    Employer("cibc", "CIBC", "workday", "cibc", "search", 3, "canada", ("bank",), "https://cibc.wd3.myworkdayjobs.com/search"),
    Employer("scotiabank", "Scotiabank", "successfactors", "jobs.scotiabank.com", country="canada", tags=("bank",), careers_url="https://jobs.scotiabank.com"),
    Employer("manulife", "Manulife", "workday", "manulife", "MFCJH_Jobs", 3, "canada", ("insurance",), "https://manulife.wd3.myworkdayjobs.com/MFCJH_Jobs"),
    Employer("sunlife", "Sun Life", "workday", "sunlife", "Experienced-Jobs", 3, "canada", ("insurance",), "https://sunlife.wd3.myworkdayjobs.com/Experienced-Jobs"),
    Employer("wealthsimple", "Wealthsimple", "ashby", "wealthsimple", country="canada", tags=("fintech",), careers_url="https://jobs.ashbyhq.com/wealthsimple"),
    Employer("neofinancial", "Neo Financial", "ashby", "neofinancial", country="canada", tags=("fintech",), careers_url="https://jobs.ashbyhq.com/neofinancial"),
    Employer("clearco", "Clearco", "ashby", "clearco", country="canada", tags=("fintech",), careers_url="https://jobs.ashbyhq.com/clearco"),
    # Telecom
    Employer("rogers", "Rogers", "successfactors", "jobs.rogers.com", country="canada", tags=("telecom",), careers_url="https://jobs.rogers.com"),
    Employer("bell", "Bell", "successfactors", "jobs.bce.ca", country="canada", tags=("telecom",), careers_url="https://jobs.bce.ca"),
    # Large technology employers with Toronto-area offices
    Employer("amazon", "Amazon", "amazon", country=None, tags=("big_tech",), careers_url="https://www.amazon.jobs"),
    Employer("ibm", "IBM", "ibm", country=None, tags=("big_tech",), careers_url="https://www.ibm.com/careers"),
    Employer("amd", "AMD", "jibe", "careers.amd.com", country=None, tags=("big_tech", "hardware"), careers_url="https://careers.amd.com"),
    Employer("thomsonreuters", "Thomson Reuters", "workday", "thomsonreuters", "External_Career_Site", 5, None, ("big_tech",), "https://thomsonreuters.wd5.myworkdayjobs.com/External_Career_Site"),
    Employer("gm", "General Motors", "workday", "generalmotors", "Careers_GM", 5, None, ("automotive",), "https://generalmotors.wd5.myworkdayjobs.com/Careers_GM"),
    Employer("nvidia", "NVIDIA", "workday", "nvidia", "NVIDIAExternalCareerSite", 5, None, ("big_tech",), "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"),
    Employer("salesforce", "Salesforce", "workday", "salesforce", "External_Career_Site", 12, None, ("big_tech",), "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site"),
    Employer("autodesk", "Autodesk", "workday", "autodesk", "Ext", 1, None, ("big_tech",), "https://autodesk.wd1.myworkdayjobs.com/Ext"),
    Employer("cisco", "Cisco", "workday", "cisco", "Cisco_Careers", 5, None, ("big_tech",), "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers"),
    Employer("adobe", "Adobe", "workday", "adobe", "external_experienced", 5, None, ("big_tech",), "https://adobe.wd5.myworkdayjobs.com/external_experienced"),
    Employer("pwc", "PwC Canada", "workday", "pwc", "Global_Experienced_Careers", 3, None, ("consulting",), "https://pwc.wd3.myworkdayjobs.com/Global_Experienced_Careers"),
    # Canadian and Toronto-area technology companies
    Employer("cohere", "Cohere", "ashby", "cohere", country="canada", tags=("ai",), careers_url="https://jobs.ashbyhq.com/cohere"),
    Employer("1password", "1Password", "ashby", "1password", country="canada", tags=("security",), careers_url="https://jobs.ashbyhq.com/1password"),
    Employer("lightspeed", "Lightspeed Commerce", "ashby", "lightspeedhq", country="canada", tags=("commerce",), careers_url="https://jobs.ashbyhq.com/lightspeedhq"),
    Employer("maple", "Maple", "ashby", "maple", country="canada", tags=("health",), careers_url="https://jobs.ashbyhq.com/maple"),
    Employer("geotab", "Geotab", "greenhouse", "geotab", country="canada", tags=("iot",), careers_url="https://www.geotab.com/careers/"),
    Employer("faire", "Faire", "greenhouse", "faire", country=None, tags=("commerce",), careers_url="https://www.faire.com/careers"),
    Employer("hootsuite", "Hootsuite", "greenhouse", "hootsuite", country="canada", tags=("saas",), careers_url="https://careers.hootsuite.com"),
    Employer("dialpad", "Dialpad", "greenhouse", "dialpad", country=None, tags=("saas",), careers_url="https://www.dialpad.com/careers/"),
    Employer("ritual", "Ritual", "greenhouse", "ritual", country="canada", tags=("saas",), careers_url="https://ritual.co/careers"),
    Employer("pointclickcare", "PointClickCare", "lever", "pointclickcare", country="canada", tags=("health",), careers_url="https://jobs.lever.co/pointclickcare"),
    Employer("achievers", "Achievers", "lever", "achievers", country="canada", tags=("saas",), careers_url="https://jobs.lever.co/achievers"),
    Employer("wattpad", "Wattpad", "lever", "wattpad", country="canada", tags=("media",), careers_url="https://jobs.lever.co/wattpad"),
    Employer("fullscript", "Fullscript", "lever", "fullscript", country="canada", tags=("health",), careers_url="https://jobs.lever.co/fullscript"),
    Employer("paytm", "Paytm Labs", "lever", "paytm", country="canada", tags=("fintech",), careers_url="https://jobs.lever.co/paytm"),
    # US technology companies with Toronto offices or remote roles open in Canada
    Employer("instacart", "Instacart", "greenhouse", "instacart", tags=("big_tech",), careers_url="https://instacart.careers"),
    Employer("databricks", "Databricks", "greenhouse", "databricks", tags=("data",), careers_url="https://www.databricks.com/company/careers"),
    Employer("stripe", "Stripe", "greenhouse", "stripe", tags=("fintech",), careers_url="https://stripe.com/jobs"),
    Employer("lyft", "Lyft", "greenhouse", "lyft", tags=("big_tech",), careers_url="https://www.lyft.com/careers"),
    Employer("pinterest", "Pinterest", "greenhouse", "pinterest", tags=("big_tech",), careers_url="https://www.pinterestcareers.com"),
    Employer("airbnb", "Airbnb", "greenhouse", "airbnb", tags=("big_tech",), careers_url="https://careers.airbnb.com"),
    Employer("okta", "Okta", "greenhouse", "okta", tags=("security",), careers_url="https://www.okta.com/company/careers/"),
    Employer("mongodb", "MongoDB", "greenhouse", "mongodb", tags=("data",), careers_url="https://www.mongodb.com/careers"),
    Employer("cloudflare", "Cloudflare", "greenhouse", "cloudflare", tags=("infrastructure",), careers_url="https://www.cloudflare.com/careers/"),
    Employer("datadog", "Datadog", "greenhouse", "datadog", tags=("infrastructure",), careers_url="https://careers.datadoghq.com"),
    Employer("twilio", "Twilio", "greenhouse", "twilio", tags=("saas",), careers_url="https://www.twilio.com/company/jobs"),
    Employer("elastic", "Elastic", "greenhouse", "elastic", tags=("data",), careers_url="https://www.elastic.co/careers"),
    Employer("coinbase", "Coinbase", "greenhouse", "coinbase", tags=("fintech",), careers_url="https://www.coinbase.com/careers"),
    Employer("gitlab", "GitLab", "greenhouse", "gitlab", tags=("devtools",), careers_url="https://about.gitlab.com/jobs/"),
]

EMPLOYER_BY_KEY = {item.key: item for item in EMPLOYERS}


def employer_from_dict(data: dict) -> Employer:
    return Employer(
        key=data["key"],
        name=data.get("name") or data["key"],
        ats=data["ats"],
        board=data.get("board", ""),
        site=data.get("site", ""),
        wd=int(data.get("wd") or 0),
        country=data.get("country"),
        tags=tuple(data.get("tags") or ()),
        careers_url=data.get("careers_url", ""),
    )


def employer_to_dict(item: Employer) -> dict:
    return {
        "key": item.key,
        "name": item.name,
        "ats": item.ats,
        "board": item.board,
        "site": item.site,
        "wd": item.wd,
        "country": item.country,
        "tags": list(item.tags),
        "careers_url": item.careers_url,
    }


def parse_careers_url(url: str, name: str | None = None) -> Employer | None:
    """Turn a pasted career-site URL into a monitored employer when the platform has a public feed."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = [part for part in parsed.path.split("/") if part]
    workday = re.match(r"^([a-z0-9-]+)\.wd(\d+)\.myworkdayjobs\.com$", host)
    if workday:
        tenant, number = workday.group(1), int(workday.group(2))
        site = next((part for part in path if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", part)), "")
        if not site:
            return None
        return Employer(tenant, name or tenant.title(), "workday", tenant, site, number, careers_url=url)
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and path:
        return Employer(path[0], name or path[0].title(), "greenhouse", path[0], careers_url=url)
    if host == "jobs.lever.co" and path:
        return Employer(path[0], name or path[0].title(), "lever", path[0], careers_url=url)
    if host == "jobs.ashbyhq.com" and path:
        return Employer(path[0], name or path[0].title(), "ashby", path[0], careers_url=url)
    return None


def parse_board_token(token: str) -> Employer | None:
    """Legacy `greenhouse:slug` tokens from settings and JOB_BOARD_TOKENS."""
    if ":" not in token:
        return None
    kind, board = [part.strip() for part in token.split(":", 1)]
    kind = kind.lower()
    if not board or kind not in {"greenhouse", "lever", "ashby"}:
        return None
    known = next((item for item in EMPLOYERS if item.ats == kind and item.board == board), None)
    return known or Employer(board, board.replace("-", " ").title(), kind, board)
