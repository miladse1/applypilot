"""Experience York co-op postings, imported from the user's own browser and kept private.

Why not automatic: Experience York (hosted on orbissites.com) sits behind Cloudflare bot
protection, which blocks browsers that are controlled by software, such as the ApplyPilot
window. ApplyPilot does not try to get around that. York publishes no student export or API.

What works instead, all with the user's normal browser and no requests to York by ApplyPilot:
- the "Save to ApplyPilot" bookmark: on a posting list it saves every row on the page (title,
  employer, location, deadline, ID); on a posting it saves the full details. It reads only the
  page on screen, like copy and paste, and hands it to ApplyPilot on this computer;
- saved pages: File > Save Page As (HTML) or Print > Save as PDF, many at once.

Pages are parsed here, without AI. Postings are restricted (see app.services.privacy): stored
for this user only, never merged with public postings, never sent to Claude without York's
permission. Ranking, project choice, resume tailoring, and cover letters work locally.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import JobMatch, JobPosting, PortalPosting, User
from app.services.capture import _deadline, channels, fields_from_labels, relevant, wanted_families
from app.services.jsonutil import dumps, loads

SOURCE = "yorku"
LABEL = "Experience York"
YORK_URL = "https://experience.yorku.ca/myAccount/dashboard.htm"
BLOCK_TAGS = {"p", "div", "tr", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "dd", "dt", "td", "th", "ul", "ol"}


def _clean(text: str | None) -> str:
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _itertext_with_breaks(element) -> str:
    out = []

    def walk(node):
        if not isinstance(node.tag, str):
            if node.tail:
                out.append(node.tail)
            return
        block = node.tag in BLOCK_TAGS
        if block:
            out.append("\n")
        if node.text:
            out.append(node.text)
        for child in node:
            walk(child)
        if block:
            out.append("\n")
        if node.tail:
            out.append(node.tail)

    walk(element)
    return "".join(out)


def _links(element) -> list[str]:
    return [a.get("href") for a in element.xpath(".//a[@href]") if (a.get("href") or "").startswith("http")][:5]


def page_data_from_html(html: str, url: str = "") -> dict:
    """The same picture of a page that the in-browser reader builds: label/value pairs, headings, text."""
    import lxml.html

    doc = lxml.html.fromstring(html or "<html></html>")
    ld = "\n".join(_clean(node.text_content()) for node in doc.xpath('//script[@type="application/ld+json"]'))
    title = _clean(doc.findtext(".//title") or "")
    for bad in doc.xpath("//script|//style|//noscript|//svg|//template|//head"):
        bad.drop_tree()
    pairs = []
    for row in doc.xpath("//tr"):
        cells = [cell for cell in row if isinstance(cell.tag, str) and cell.tag in {"td", "th"}]
        if len(cells) != 2:
            continue
        label = _clean(cells[0].text_content())
        if label and len(label) <= 90:
            pairs.append({"label": label.rstrip(":").strip(), "value": _clean(_itertext_with_breaks(cells[1])), "links": _links(cells[1])})
    for dt in doc.xpath("//dt"):
        dd = dt.getnext()
        if dd is not None and dd.tag == "dd":
            pairs.append({"label": _clean(dt.text_content()).rstrip(":").strip(), "value": _clean(_itertext_with_breaks(dd)), "links": _links(dd)})
    for element in doc.xpath('//strong|//b|//label|//*[contains(@class, "label")]'):
        if element.xpath("ancestor::tr|ancestor::dt"):
            continue
        label = _clean(element.text_content())
        if not label.endswith(":") or len(label) > 70:
            continue
        following = element.getnext()
        value = _clean(_itertext_with_breaks(following)) if following is not None else ""
        holder = following
        if not value:
            holder = element.getparent()
            value = _clean(_itertext_with_breaks(holder)).replace(label, "", 1).strip() if holder is not None else ""
            value = (value or _clean(element.tail or ""))
        if value:
            pairs.append({"label": label.rstrip(":").strip(), "value": value[:8000], "links": _links(holder) if holder is not None else []})
    headings = [_clean(node.text_content()) for node in doc.xpath("//h1|//h2|//h3|//h4")]
    body = doc.find("body")
    text = _clean(_itertext_with_breaks(body if body is not None else doc))
    return {"url": url, "title": title, "pairs": pairs, "headings": [h for h in headings if h][:12], "text": text[:30000], "ld": ld[:60000], "linkedin": {}}


LABEL_LINE = re.compile(r"^([A-Z][A-Za-z0-9 /&(),'.#-]{1,60}):\s*(.*)$")


def page_data_from_text(text: str, url: str = "") -> dict:
    """Label/value pairs from plain text (a posting printed to PDF, or copied and pasted)."""
    lines = [line.strip() for line in _clean(text).split("\n")]
    pairs, current = [], None
    for line in lines:
        match = LABEL_LINE.match(line)
        if match and len(match.group(1).split()) <= 8:
            current = {"label": match.group(1).strip(), "value": match.group(2).strip(), "links": []}
            pairs.append(current)
        elif current is not None and line:
            current["value"] = (current["value"] + "\n" + line).strip()
    for pair in pairs:
        pair["links"] = re.findall(r"https?://[^\s)]+", pair["value"])[:3]
        pair["value"] = _clean(pair["value"])[:8000]
    headings = [line for line in lines if line][:3]
    return {"url": url, "title": headings[0] if headings else "", "pairs": pairs, "headings": headings, "text": _clean(text)[:30000], "ld": "", "linkedin": {}}


def list_rows_from_html(html: str) -> list[dict]:
    """Rows of a posting list (the table on a search results page)."""
    import lxml.html

    doc = lxml.html.fromstring(html or "<html></html>")
    best = None
    for table in doc.xpath("//table"):
        head = table.xpath(".//thead/tr") or table.xpath(".//tr")
        if not head:
            continue
        headers = [_clean(cell.text_content()).lower() for cell in head[0] if isinstance(cell.tag, str)]
        if not any(re.search(r"title|position", item) for item in headers):
            continue
        rows = [row for row in (table.xpath(".//tbody/tr") or table.xpath(".//tr")[1:]) if len(row.xpath("./td")) >= 2]
        if best is None or len(rows) > len(best[1]):
            best = (headers, rows)
    if best is None:
        return []
    headers, rows = best

    def col(pattern):
        return next((index for index, item in enumerate(headers) if re.search(pattern, item)), -1)

    title_i, org_i, loc_i, id_i, dead_i = col(r"title|position"), col(r"organi[sz]ation|employer|company"), col(r"location|city"), col(r"^id$|posting id|job id"), col(r"deadline")
    out = []
    for row in rows:
        cells = [cell for cell in row if isinstance(cell.tag, str) and cell.tag in {"td", "th"}]

        def cell(index, cells=cells):
            return _clean(cells[index].text_content()) if 0 <= index < len(cells) else ""

        link = cells[title_i].xpath(".//a") if 0 <= title_i < len(cells) else []
        code = " ".join((a.get("onclick") or "") + " " + (a.get("href") or "") for a in link)
        from_code = re.search(r"posting_?id['\"]?\s*[:=,]\s*['\"]?(\d+)", code, re.I)
        posting_id = re.sub(r"\D", "", cell(id_i)) or (from_code.group(1) if from_code else "")
        title = cell(title_i)
        if title:
            out.append({"id": posting_id, "title": title, "company": cell(org_i), "location": cell(loc_i), "deadline": cell(dead_i)})
    return out


# ---------------------------------------------------------------------------
# Saving, privately
# ---------------------------------------------------------------------------


def _external_id(fields: dict) -> str:
    if fields.get("posting_id") or fields.get("id"):
        return str(fields.get("posting_id") or fields.get("id"))
    key = f"{fields.get('title', '').lower()}|{(fields.get('company') or '').lower()}"
    return "t" + hashlib.sha256(key.encode()).hexdigest()[:16]


def save(db, user: User, fields: dict, *, detail: bool) -> tuple[str, JobPosting]:
    """Store one York posting for this user: created, updated, or unchanged. Never merged with public postings."""
    from app.services.analysis import detect_arrangement
    from app.services.job_sources import NormalizedJob
    from app.services.job_sync import _apply_classification, _replace_analysis, refresh_matches

    external = _external_id(fields)
    now = datetime.now(timezone.utc)
    row = db.scalar(select(PortalPosting).where(PortalPosting.user_id == user.id, PortalPosting.portal == "york", PortalPosting.external_id == external))
    posting = db.get(JobPosting, row.job_posting_id) if row else None
    title = (fields.get("title") or (posting.title if posting else "") or "York co-op posting").strip()[:300]
    company = (fields.get("company") or (posting.company if posting else "") or "Employer not listed").strip()[:240]
    description = (fields.get("description") or "").strip()
    if posting is not None and not detail:
        description = posting.description  # a list row never replaces details you saved
    location = fields.get("location") or (posting.location if posting else None)
    listing = NormalizedJob(source=SOURCE, external_id=f"{user.id}:york:{external}", title=title, company=company, description=description or title, location=location)
    listing.work_arrangement = detect_arrangement(title, f"{location or ''} {description[:800]}")
    listing.employment_type = "internship"
    listing.hints.append("co-op")
    listing.classify()
    method = fields.get("method") or (row.application_method if row else None)
    employer_url = fields.get("employer_url") or (row.employer_url if row else None)
    probe = PortalPosting(portal="york", application_method=method, employer_url=employer_url)
    url = fields.get("url") if (fields.get("url") or "").startswith("http") and "localhost" not in (fields.get("url") or "") else YORK_URL
    application_url = employer_url if employer_url and "employer" in channels(probe) else (row.url if row and row.url else url)
    state = "unchanged"
    if posting is None:
        posting = JobPosting(
            user_id=user.id, source=SOURCE, external_id=listing.external_id,
            # A private fingerprint: York postings are never merged into (or with) public postings.
            fingerprint="private-" + hashlib.sha256(listing.external_id.encode()).hexdigest()[:40],
            title=title, company=company, location=(location or None) and location[:240], description=listing.description,
            work_arrangement=listing.work_arrangement, employment_type=listing.employment_type, application_url=application_url[:800],
            discovered_at=now, last_verified_at=now, is_active=True, is_sample=False, raw_payload=dumps({"portal": "york"}),
            also_seen_on="[]", source_label=LABEL, restricted=True, needs_detail=False,
        )
        _apply_classification(posting, listing)
        db.add(posting)
        db.flush()
        _replace_analysis(db, posting)
        state = "created"
    else:
        changed = detail and (posting.description != listing.description or posting.title != title)
        posting.title, posting.company = title, company
        posting.location = (location or None) and location[:240]
        posting.application_url = application_url[:800]
        posting.restricted, posting.needs_detail, posting.is_active, posting.last_verified_at = True, False, True, now
        if changed:
            posting.description = listing.description
            _apply_classification(posting, listing)
            _replace_analysis(db, posting)
            state = "updated"
    expires = _deadline(fields.get("deadline"))
    if expires:
        posting.expires_at = expires
    if row is None:
        row = PortalPosting(user_id=user.id, portal="york", external_id=external, job_posting_id=posting.id, url=url[:1000], created_at=now, updated_at=now, details_json="{}")
        db.add(row)
    details = loads(row.details_json, {})
    details["has_details"] = bool(details.get("has_details") or (detail and len(description) >= 80))
    for key in ("salary", "division", "duration", "openings"):
        if fields.get(key):
            details[key] = fields[key]
    row.details_json = dumps(details)
    row.application_method = ((method or "")[:400]) or None
    row.employer_url = ((employer_url or "")[:1000]) or None
    row.deadline = (str(fields.get("deadline") or row.deadline or "")[:120]) or None
    row.documents = fields.get("documents") or row.documents
    row.term = (str(fields.get("term") or row.term or "")[:120]) or None
    db.flush()
    refresh_matches(db, user, postings=[posting])
    return state, posting


def import_page(db, user: User, *, html: str = "", text: str = "", url: str = "") -> dict:
    """Import one page: a posting (full details) or a posting list (every row). Parsed here, without AI."""
    rows = list_rows_from_html(html) if html else []
    if rows:
        results = [save(db, user, {**row, "posting_id": row.get("id")}, detail=False) for row in rows]
        return _summary("list", results)
    data = page_data_from_html(html, url) if html else page_data_from_text(text, url)
    fields = fields_from_labels(data)
    if not fields.get("title") or not (fields.get("company") or fields.get("posting_id")) or len(fields.get("description") or "") < 80:
        return {"kind": "unknown", "saved": [], "message": "This page does not look like an Experience York posting or posting list."}
    fields["url"] = url
    state, posting = save(db, user, fields, detail=True)
    return _summary("posting", [(state, posting)])


def _summary(kind: str, results: list[tuple[str, JobPosting]]) -> dict:
    saved = [{"id": posting.id, "title": posting.title, "company": posting.company, "state": state} for state, posting in results]
    created = sum(1 for item in saved if item["state"] == "created")
    updated = sum(1 for item in saved if item["state"] == "updated")
    if kind == "list":
        message = f"Saved {len(saved)} posting{'s' if len(saved) != 1 else ''} from the list ({created} new). Open the ones you like on York and save them again to add their full details."
    else:
        item = saved[0]
        message = f"Saved the full posting: {item['title']} at {item['company']}." if item["state"] != "unchanged" or created or updated else f"{item['title']} was already saved."
    return {"kind": kind, "saved": saved, "created": created, "updated": updated, "message": message}


# ---------------------------------------------------------------------------
# Ranking, locally
# ---------------------------------------------------------------------------


def _project_fit(profile, posting) -> list[str]:
    """Projects on the profile whose tools match this job's skills, best first."""
    from app.services.skills import normalize_skill
    from app.services.tailoring import _expand, _skill_keys, job_terms

    terms = job_terms(posting)
    scored = []
    for project in profile.projects:
        keys = _expand(_skill_keys(f"{project.name} {project.description or ''} {project.responsibilities or ''}") | {normalize_skill(item)[0] for item in loads(project.technologies, [])})
        score = sum(terms["weights"].get(key, 0) for key in keys)
        if score > 0:
            scored.append((score, project.name))
    return [name for _score, name in sorted(scored, reverse=True)[:2]]


def ranking(db, user: User) -> dict:
    from app.services.job_sync import load_match
    from app.services.profile_ops import get_profile

    profile = get_profile(db, user)
    families = wanted_families(db, user)
    rows = db.scalars(select(PortalPosting).where(PortalPosting.user_id == user.id, PortalPosting.portal == "york")).all()
    today = datetime.now(timezone.utc).date()
    out = []
    for row in rows:
        posting = db.get(JobPosting, row.job_posting_id)
        if posting is None:
            continue
        details = loads(row.details_json, {})
        has_details = bool(details.get("has_details"))
        match = load_match(db, user, posting) if has_details else None
        stored = db.scalar(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_posting_id == posting.id))
        qualification = match["qualification_score"] if match else None
        interest = stored.career_interest_score if stored else 0
        fits_search = relevant(posting.title, families)
        days_left = (posting.expires_at.date() - today).days if posting.expires_at else None
        closed = days_left is not None and days_left < 0
        matched = [item["name"] for item in (match or {}).get("items", []) if item.get("status") == "matched"][:6]
        missing = [item["name"] for item in (match or {}).get("items", []) if item.get("status") in {"unverified", "not_possessed"} and item.get("priority") == "mandatory"][:4]
        projects = _project_fit(profile, posting) if has_details else []
        urgency = 0 if days_left is None else (25 if days_left <= 3 else 18 if days_left <= 7 else 10 if days_left <= 14 else 4)
        score = (qualification if qualification is not None else 35) * 0.6 + interest * 0.2 + urgency + (15 if fits_search else -40) + 3 * len(projects)
        if closed:
            tier, score = "closed", -100
        elif not fits_search:
            tier = "other"
        elif not has_details:
            tier = "needs_details"
        elif (qualification or 0) >= 60 and not missing:
            tier = "apply_first"
        elif (qualification or 0) >= 40:
            tier = "worth_applying"
        else:
            tier = "stretch"
        reasons = []
        if matched:
            reasons.append("You have: " + ", ".join(matched) + ".")
        if projects:
            reasons.append("Best projects to show: " + " and ".join(projects) + ".")
        if missing:
            reasons.append("Required but not on your profile: " + ", ".join(missing) + ". Answer on the job page if you have them.")
        if not has_details:
            reasons.append("Only the list entry is saved. Open it on Experience York and click Save to ApplyPilot to compare its requirements.")
        if days_left is not None and not closed:
            reasons.append("Due today." if days_left == 0 else f"Due in {days_left} day{'s' if days_left != 1 else ''}.")
        submit = channels(row, posting)
        out.append({
            "id": posting.id, "posting_id": row.external_id, "title": posting.title, "company": posting.company, "location": posting.location,
            "deadline": row.deadline, "days_left": days_left, "tier": tier, "score": round(score, 1), "qualification": qualification,
            "has_details": has_details, "submit_on": submit, "employer_url": row.employer_url, "documents": row.documents, "reasons": reasons,
            "application_id": _application_id(db, user, posting),
        })
    order = {"apply_first": 0, "worth_applying": 1, "stretch": 2, "needs_details": 3, "other": 4, "closed": 5}
    out.sort(key=lambda item: (order[item["tier"]], -item["score"]))
    counts = {tier: sum(1 for item in out if item["tier"] == tier) for tier in order}
    return {"postings": out, "counts": counts, "total": len(out)}


def _application_id(db, user: User, posting: JobPosting) -> str | None:
    from app.models import Application

    return db.scalar(select(Application.id).where(Application.user_id == user.id, Application.job_posting_id == posting.id).order_by(Application.created_at.desc()).limit(1))
