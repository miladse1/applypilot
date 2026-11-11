"""Experience York postings: imported from the user's own browser, kept private, ranked locally.

A real headless Chrome renders local copies of York pages (tests/fixtures/portals) and runs the
same bookmark code the app gives the user. No request goes to York and no model is called.
"""

import functools
import http.server
import json
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Same code as yorkBookmarklet() in apps/web/src/components/bookmarklet.tsx, with window.open recorded.
BOOKMARK = (
    "(()=>{const c=document.documentElement.cloneNode(true);"
    "c.querySelectorAll('script:not([type=\"application/ld+json\"]),style,svg,noscript,iframe,img,video,link,meta,canvas').forEach(e=>e.remove());"
    "const h=c.outerHTML.replace(/\\s{2,}/g,' ');"
    "if(h.length>900000){return null;}"
    "return '/york/import#'+encodeURIComponent(JSON.stringify({url:location.href,html:h}));})()"
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed")
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(channel="chrome", headless=True)
        except Exception:  # noqa: BLE001
            try:
                instance = playwright.chromium.launch(headless=True)
            except Exception:  # noqa: BLE001
                pytest.skip("No Chrome or Chromium available for browser tests")
        yield instance
        instance.close()


@pytest.fixture(scope="module", autouse=True)
def stop_runner_afterwards():
    yield
    from app.services.autoapply.runner import RUNNER

    RUNNER.stop()


class Recorder:
    """Stands in for Claude and records every prompt it receives."""

    def __init__(self):
        self.prompts = []

    def structured(self, *, system, user, schema=None, max_tokens=0, effort=None, cache=False, schema_hint=""):
        self.prompts.append(system + "\n" + user)
        if "reply" in json.dumps(schema or {}):
            return {"reply": "Tell me what the job needs and I will adjust.", "edits": []}
        if "bullets" in json.dumps(schema or {}):
            return {"summary": {"text": "", "reason": ""}, "bullets": [], "notes": []}
        return {}


def _bookmark(page, url):
    page.goto(url)
    page.wait_for_timeout(200)
    fragment = page.evaluate(BOOKMARK)
    from urllib.parse import unquote

    return json.loads(unquote(fragment.split("#", 1)[1]))


def _sign_in_to_fixture(page, site):
    page.goto(f"{site}/portals/york-dashboard.html")
    page.evaluate("localStorage.setItem('york', 'in')")


def test_york_is_never_opened_in_the_automated_window_and_block_pages_stop_capture(site, browser, client, auth_header):
    from app.services import capture

    from test_portals_memory_editor import FakeRunner, _user_id

    response = client.post("/api/v1/jobs/capture/start", headers=auth_header, json={"portal": "york"})
    assert response.status_code == 400 and "blocks browsers that are controlled by software" in response.json()["detail"]["message"]
    assert client.post("/api/v1/jobs/capture/start", headers=auth_header, json={"portal": "web", "url": "https://experience.yorku.ca/myAccount/x.htm"}).status_code == 400

    context = browser.new_context()
    manager = capture.CaptureManager(FakeRunner(context))
    user_id = _user_id()
    manager.start(user_id, "york")
    assert context.pages == [] and "usual browser" in manager.status(user_id)["message"]
    # Any site that shows a block page: ApplyPilot stops and does not retry.
    manager.start(user_id, "linkedin", url=f"{site}/portals/blocked.html")
    status = manager.status(user_id)
    assert status["active"] is False and "blocked the ApplyPilot window" in status["message"]
    context.close()


def test_bookmark_imports_lists_and_postings_privately_and_ranks_them(site, browser, client, auth_header, monkeypatch):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import JobPosting, PortalPosting
    from app.services.job_sources import NormalizedJob
    from app.services.job_sync import upsert_posting

    model = Recorder()
    monkeypatch.setattr("app.services.ai.get_provider", lambda settings, tier="quality": model)
    client.post("/api/v1/resumes/sample", headers=auth_header)
    resume_id = client.get("/api/v1/resumes", headers=auth_header).json()[0]["id"]
    client.post(f"/api/v1/resumes/{resume_id}/approve", headers=auth_header)
    # The same job is also public on the employer's site: the York copy must stay separate.
    with SessionLocal() as db:
        _, public = upsert_posting(db, NormalizedJob(source="greenhouse", external_id="maple-1", title="Software Developer Co-op", company="Maple Analytics",
                                                     description="Public posting. Python and SQL.", location="Toronto, ON", application_url="https://boards.greenhouse.io/maple/jobs/1"))
        db.commit()
        public_id = public.id

    page = browser.new_context().new_page()
    _sign_in_to_fixture(page, site)
    imported = []
    for name in ("york-list.html?page=1", "york-list.html?page=2"):
        payload = _bookmark(page, f"{site}/portals/{name}")
        result = client.post("/api/v1/jobs/york/import", headers=auth_header, json=payload).json()
        assert result["kind"] == "list", result
        imported += result["saved"]
    assert len(imported) == 5 and all(item["state"] == "created" for item in imported)
    ranked = client.get("/api/v1/jobs/york", headers=auth_header).json()
    assert ranked["total"] == 5 and ranked["ai_permission"] is False
    tiers = {item["title"]: item["tier"] for item in ranked["postings"]}
    assert tiers["Marketing Assistant"] == "other" and tiers["Civil Engineering Co-op - Site Inspection"] == "other"
    assert tiers["Software Developer Co-op"] == "needs_details"

    for posting_id in ("101", "103", "104"):
        payload = _bookmark(page, f"{site}/portals/york-detail.html?p={posting_id}")
        result = client.post("/api/v1/jobs/york/import", headers=auth_header, json=payload).json()
        assert result["kind"] == "posting" and result["saved"][0]["state"] == "updated", result

    # Saved pages work too: an HTML file and a PDF ("Print > Save as PDF"), several at once.
    page.goto(f"{site}/portals/york-detail.html?p=104")
    html = page.content().encode()
    pdf = page.pdf()
    files = [("files", ("posting-104.html", html, "text/html")), ("files", ("posting-104.pdf", pdf, "application/pdf")), ("files", ("notes.txt", b"hello", "text/plain"))]
    uploaded = client.post("/api/v1/jobs/york/files", headers=auth_header, files=files).json()
    kinds = [item["kind"] for item in uploaded["results"]]
    assert kinds == ["posting", "posting", "unknown"], uploaded
    page.context.close()

    ranked = client.get("/api/v1/jobs/york", headers=auth_header).json()
    by_title = {item["title"]: item for item in ranked["postings"]}
    assert ranked["total"] == 5  # no duplicates from the list, the pages, or the files
    software = by_title["Software Developer Co-op"]
    assert software["has_details"] and software["tier"] in {"apply_first", "worth_applying", "stretch"} and software["submit_on"] == ["york", "employer"]
    assert any(reason.startswith("Due in") or reason == "Due today." for reason in software["reasons"]) or software["days_left"] is None or software["days_left"] < 0
    order = [item["tier"] for item in ranked["postings"]]
    assert order.index("other") > max(index for index, tier in enumerate(order) if tier in {"apply_first", "worth_applying", "stretch"})

    with SessionLocal() as db:
        rows = db.scalars(select(PortalPosting).where(PortalPosting.portal == "york")).all()
        assert len(rows) == 5
        york_ids = {row.job_posting_id for row in rows}
        assert public_id not in york_ids  # never merged with the public posting
        for row in rows:
            posting = db.get(JobPosting, row.job_posting_id)
            assert posting.restricted is True and posting.user_id is not None and posting.fingerprint.startswith("private-")
        assert db.get(JobPosting, public_id).description == "Public posting. Python and SQL."

    # Tailored resume and cover letter for selected jobs, made without sending the posting to Claude.
    software_id = software["id"]
    batch = client.post("/api/v1/applications/batch", headers=auth_header, json={"job_ids": [software_id], "include_cover_letter": True}).json()
    assert batch["results"][0]["ok"], batch
    application = client.get(f"/api/v1/applications/{batch['results'][0]['application']['id']}", headers=auth_header).json()
    assert application["cover_letter"] and [item["key"] for item in application["submit_on"]] == ["york", "employer"]
    version = client.get(f"/api/v1/resume-versions/{application['resume_version_id']}", headers=auth_header).json()
    assert version["content"]["generation"]["private"] is True and version["private_job"] is True
    assert model.prompts == []  # nothing from York reached the model

    # The resume chat still works, but the model sees only the resume and the message.
    client.post(f"/api/v1/resume-versions/{version['id']}/chat", headers=auth_header, json={"message": "What would you improve?"})
    assert len(model.prompts) == 1
    for secret in ("Maple Analytics", "Software Developer Co-op", "four-month co-op term", "careers.maple.example"):
        assert secret not in model.prompts[0], secret
    assert "private and is not shown to you" in model.prompts[0]

    # The assistant cannot see York postings either.
    from app.models import User
    from app.services.assistant import Tools

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "jordan@example.com"))
        tools = Tools(db, user)
        assert "error" in tools.t_get_job(software_id)
        assert all(item["title"] != "Software Developer Co-op" or item["company"] != "Maple Analytics" for item in tools.t_search_jobs(query="Maple", limit=20)["jobs"] if item["id"] in york_ids)
        assert not any(item["id"] in york_ids for item in tools.t_search_jobs(limit=20)["jobs"])
        assert all(item["title"] == "Private Experience York posting" for item in tools.t_applications_status()["applications"] if item["application_id"] == application["id"])

    # Only with York's permission (the user's switch) may Claude be used for these postings.
    assert client.put("/api/v1/jobs/york/settings", headers=auth_header, json={"ai_permission": True}).json()["ai_permission"] is True
    regenerated = client.post(f"/api/v1/resume-versions/{version['id']}/regenerate", headers=auth_header).json()
    assert regenerated["content"]["generation"].get("private") is not True
    assert any("Maple Analytics" in prompt for prompt in model.prompts[1:])


def test_list_rows_and_text_pages_parse_without_a_browser():
    from app.services.york import list_rows_from_html, page_data_from_text
    from app.services.capture import fields_from_labels

    html = """<table><thead><tr><th>ID</th><th>Job Title</th><th>Organization</th><th>Location</th><th>App Deadline</th></tr></thead>
    <tbody><tr><td>555</td><td><a href="#">Junior Data Scientist</a></td><td>Acme</td><td>Toronto</td><td>Jan 30, 2027</td></tr></tbody></table>"""
    assert list_rows_from_html(html) == [{"id": "555", "title": "Junior Data Scientist", "company": "Acme", "location": "Toronto", "deadline": "Jan 30, 2027"}]
    text = "Junior Data Scientist\nJob ID:\n555\nOrganization:\nAcme Insights\nJob Description:\nBuild models in Python " + "and ship them " * 10 + "\nApplication Method:\nThrough Experience York\n"
    fields = fields_from_labels(page_data_from_text(text))
    assert fields["company"] == "Acme Insights" and fields["posting_id"] == "555" and fields["method"] == "Through Experience York"
