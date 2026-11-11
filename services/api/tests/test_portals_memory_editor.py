"""Experience York and LinkedIn capture, sign-in handling, reused answers, and the resume chat editor.

Browser tests run a real headless Chrome against local copies in tests/fixtures; nothing
leaves the machine and no model is called (Claude is replaced by small stand-ins).
"""

import copy
import functools
import http.server
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.autoapply.driver import IDENTITY_HOSTS, Driver
from app.services.autoapply.fields import Field, label_key

FIXTURES = Path(__file__).parent / "fixtures"

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


class FakeRunner:
    def __init__(self, context):
        self.context = context

    def _browser(self):
        return self.context

    def _owned_pages(self, run_id=None):
        return []


def _user_id():
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.email == "jordan@example.com"))


def _pump(manager, user_id, until, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        manager.watch()
        status = manager.status(user_id)
        if until(status):
            return status
        time.sleep(0.2)
    raise AssertionError(f"Timed out: {manager.status(user_id)}")


# ---------------------------------------------------------------------------
# Experience York
# ---------------------------------------------------------------------------


def test_york_posting_parser_reads_labels_and_ignores_lists():
    from app.services.capture import fields_from_labels, posting_from_page, relevant

    data = {
        "url": "https://experience.yorku.ca/myAccount/co-op/postings.htm",
        "headings": ["123456 - Junior Data Scientist"],
        "pairs": [
            {"label": "Organization", "value": "Acme Insights", "links": []},
            {"label": "Job Description", "value": "Build models " * 30, "links": []},
            {"label": "Application Method", "value": "Employer Website", "links": []},
            {"label": "If by Website, go to", "value": "https://acme.example/jobs/9", "links": ["https://acme.example/jobs/9"]},
        ],
        "text": "",
        "ld": "",
    }
    fields = fields_from_labels(data)
    assert fields["title"] == "Junior Data Scientist" and fields["posting_id"] == "123456" and fields["employer_url"] == "https://acme.example/jobs/9"
    assert posting_from_page({**data, "headings": ["Postings"], "pairs": []}, "york") is None
    assert relevant("AI/ML Research Co-op", set()) and relevant("Business Intelligence Analyst", set()) and not relevant("Retail Sales Associate", set())


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------


def test_linkedin_saves_the_job_you_open_and_learns_the_employer_link_from_your_apply_click(site, browser, client, auth_header):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import JobPosting, PortalPosting
    from app.services import capture

    context = browser.new_context()
    manager = capture.CaptureManager(FakeRunner(context))
    user_id = _user_id()
    manager.start(user_id, "linkedin", url=f"{site}/portals/jobs/view/4012345678/")
    status = _pump(manager, user_id, lambda s: s["saved_count"] >= 1)
    assert status["saved"][0]["title"] == "Software Engineering Intern (Winter 2027)" and status["saved"][0]["company"] == "Aurora Robotics"

    page = manager.sessions[user_id].page
    page.click(".jobs-apply-button")  # the user clicks Apply; LinkedIn opens the employer's site
    _pump(manager, user_id, lambda s: "employer's application link" in s["message"])
    page.goto(f"{site}/portals/jobs/view/4099999999/")  # then opens an Easy Apply job
    _pump(manager, user_id, lambda s: s["saved_count"] >= 2)
    manager.stop(user_id)
    context.close()

    with SessionLocal() as db:
        rows = {row.external_id: row for row in db.scalars(select(PortalPosting).where(PortalPosting.portal == "linkedin")).all()}
        external, easy = rows["4012345678"], rows["4099999999"]
        assert external.url == "https://www.linkedin.com/jobs/view/4012345678/"  # the original link is kept
        assert db.get(JobPosting, external.job_posting_id).application_url == f"{site}/portals/employer-apply.html"
        assert capture.channels(external) == ["employer"] and easy.easy_apply is True and capture.channels(easy) == ["linkedin"]
        assert db.get(JobPosting, external.job_posting_id).location.startswith("Toronto")


# ---------------------------------------------------------------------------
# Signing in and following the application
# ---------------------------------------------------------------------------


class FakeAccounts:
    allow_create = False

    def __init__(self):
        self.recorded = []

    def credentials(self):
        return ("sam@example.com", "Secret#2027")

    def record(self, host, *, created):
        self.recorded.append((host, created))


def _applicant(tmp_path, **saved):
    from app.services.autoapply.applicant import Applicant

    resume = tmp_path / "Sam_Lee_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test resume")
    return Applicant(
        values={"first_name": "Sam", "last_name": "Lee", "full_name": "Sam Lee", "email": "sam@example.com", "phone": "647-555-0100", "address_line1": "", "postal_code": ""},
        saved=dict(saved), answers=[], company="Example Co", employers=set(), resume_path=resume, job_country="canada",
    )


def test_email_first_sign_in_waits_for_the_spinner_and_continues(site, browser, tmp_path):
    page = browser.new_context().new_page()
    page.goto(f"{site}/portals/sso.html")
    accounts = FakeAccounts()
    outcome = Driver(page, "generic", _applicant(tmp_path), accounts=accounts, submit_mode="auto").advance()
    assert outcome.status == "submitted", outcome.message
    state = page.evaluate("window.sso")
    assert state["email"] == "sam@example.com" and state["password"] == "Secret#2027" and state["data"] == {"first": "Sam", "last": "Lee"}
    assert len(accounts.recorded) == 1
    page.context.close()


def test_google_or_microsoft_sign_in_is_left_to_you(site, browser, tmp_path):
    page = browser.new_context().new_page()
    page.goto(f"{site}/portals/google-only.html")
    driver = Driver(page, "generic", _applicant(tmp_path), accounts=FakeAccounts())
    outcome = driver.advance()
    assert outcome.attention == "login" and "Google" in outcome.message
    assert driver.sign_in_state() == "sso_choice"
    for host in ("accounts.google.com", "login.microsoftonline.com", "appleid.apple.com", "acme.okta.com", "passportyork.yorku.ca"):
        assert IDENTITY_HOSTS.search(host), host
    assert not IDENTITY_HOSTS.search("careers.google.com.evil.example") and not IDENTITY_HOSTS.search("boards.greenhouse.io")
    page.context.close()


def test_follows_the_application_into_a_new_tab_but_not_into_sign_in_pop_ups(site, browser, tmp_path):
    page = browser.new_context().new_page()
    page.goto(f"{site}/portals/opener.html")
    driver = Driver(page, "generic", _applicant(tmp_path))
    page.click("#go")  # you click a link that opens the form in a new tab
    page.wait_for_timeout(800)
    assert driver.adopt_new_tab() is True and driver.page.url.endswith("/portals/sso.html")
    page.context.close()


# ---------------------------------------------------------------------------
# Answers you gave before, asked in other words
# ---------------------------------------------------------------------------


def test_saved_answers_are_reused_for_differently_worded_questions(site, browser, tmp_path):
    from app.services.autoapply.memory import local_match

    saved = {label_key("Street address"): "1 Main St, Guelph, ON", label_key("Do you have a valid driver's licence?"): "Yes"}
    assert local_match("Home address*", saved)[1] == "1 Main St, Guelph, ON"
    assert local_match("Zip code", {label_key("Postal code"): "L3Z 1A1"})[1] == "L3Z 1A1"
    assert local_match("Are you a Canadian citizen?", {label_key("Are you legally eligible to work in Canada?"): "Yes"}) is None

    calls = []

    def recaller(fields, store):
        calls.append([item.label for item in fields])
        return {label_key(item.label): label_key("Street address") for item in fields if "address" in item.label.lower()}

    page = browser.new_context().new_page()
    page.goto(f"{site}/ats/realistic.html")
    applicant = _applicant(tmp_path, **saved)
    applicant.values.update({"school": "York University", "location": "Guelph, ON, Canada", "city": "Guelph", "country": "Canada"})
    applicant.saved.update({"voluntary_disclosures": "decline"})
    driver = Driver(page, "greenhouse", applicant, submit_mode="review", recaller=recaller)
    driver.advance()
    filled = {entry["label"]: entry for entry in driver.summary()}
    assert filled["Home address"]["value"] == "1 Main St, Guelph, ON" and filled["Home address"]["source"] == "saved"
    assert "Street address" in filled["Home address"]["basis"].replace("street address", "Street address")
    # The address was matched locally; only questions with no local match went to the model.
    assert calls and not any("address" in label.lower() for batch in calls for label in batch)
    page.context.close()


def test_model_matching_is_used_only_for_questions_you_would_otherwise_be_asked(tmp_path):
    from app.services.autoapply import memory

    class Model:
        def __init__(self):
            self.prompts = []

        def structured(self, *, system, user, schema, max_tokens, effort, cache=False):
            self.prompts.append(user)
            return {"matches": [{"key": label_key("Mailing address for offer letters"), "saved": "S1"}, {"key": "q:unknown", "saved": "S9"}]}

    model = Model()
    import app.services.ai as ai

    original = ai.get_provider
    ai.get_provider = lambda settings, tier="quality": model
    try:
        recall = memory.ai_recaller(None)
        fields = [Field(id="a", kind="text", label="Mailing address for offer letters")]
        result = recall(fields, {label_key("Home address"): "1 Main St", "location": "Guelph"})
    finally:
        ai.get_provider = original
    assert result == {label_key("Mailing address for offer letters"): label_key("Home address")}
    assert "S1: home address" in model.prompts[0] and "Guelph" not in model.prompts[0]  # only saved questions, not your answers


# ---------------------------------------------------------------------------
# Resume chat editor
# ---------------------------------------------------------------------------


def _chat_document():
    from test_project_selection import _document

    document = _document()
    document["sections"].insert(1, {"id": "s2", "key": "skills", "kind": "skills", "title": "SKILLS", "groups": [{"id": "s2g1", "label": "Languages", "items": ["Python", "TypeScript", "SQL"]}]})
    return document


def _chat_profile():
    from test_project_selection import PROFILE

    return SimpleNamespace(projects=PROFILE.projects, profile_skills=[], experiences=[], education=[], summary="", headline="", user_id="u")


def test_chat_edits_are_checked_before_they_are_applied():
    from app.services.resume_chat import apply_edits, project_pool

    document = _chat_document()
    content = {"document": document, "original_document": copy.deepcopy(document), "added_entries": []}
    profile = _chat_profile()
    smart_budget = next(entry["id"] for entry in project_pool(content, profile) if "Smart Budget" in entry["headers"][0]["text"])
    edits = [
        {"op": "rewrite", "target": "s3e2b1", "text": "Built a **Flask** REST API on **PostgreSQL** serving 10,000 users.", "items": [], "position": 0, "reason": ""},
        {"op": "rewrite", "target": "s3e2b2", "text": "Implemented A* search to compute the shortest in-store routes.", "items": [], "position": 0, "reason": "clearer"},
        {"op": "rewrite", "target": "s3e1b1", "text": "Built a booking platform with **React**, deployed on **Kubernetes**.", "items": [], "position": 0, "reason": ""},
        {"op": "hide", "target": "s5e1b3", "text": "", "items": [], "position": 0, "reason": "less relevant"},
        {"op": "add_project", "target": smart_budget, "text": "", "items": [], "position": 1, "reason": "FastAPI and React"},
        {"op": "remove_project", "target": "s3e1", "text": "", "items": [], "position": 0, "reason": "least related"},
        {"op": "set_skills", "target": "s2g1", "text": "", "items": ["Python", "SQL", "TypeScript"], "position": 0, "reason": "data first"},
        {"op": "set_skills", "target": "s2g1", "text": "", "items": ["Python", "Rust"], "position": 0, "reason": ""},
    ]
    new_document, applied, blocked = apply_edits(content, edits, profile, user_facts="Make it fit a data role.")
    assert [item["op"] for item in applied] == ["rewrite", "hide", "add_project", "remove_project", "set_skills"]
    assert {item["target"] for item in blocked} == {"s3e2b1", "s3e1b1", "s2g1"}
    assert any("10,000" in problem for item in blocked for problem in item["problems"])
    projects = next(s for s in new_document["sections"] if s["key"] == "projects")["entries"]
    assert projects[0]["headers"][0]["text"] == "Smart Budget App" and "s3e1" not in {e["id"] for e in projects}
    assert content["added_entries"] and content["added_entries"][0]["id"] == smart_budget
    assert document == content["document"]  # the stored document is untouched until the result is accepted

    # A tool the candidate says they used can be named.
    _doc, applied, blocked = apply_edits(content, edits[2:3], profile, user_facts="I deployed the booking platform on Kubernetes.")
    assert applied and not blocked


class ChatModel:
    """Stands in for Claude: rewrites the first bullet it was asked about, or answers a question."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def structured(self, *, system, user, schema, max_tokens, effort=None, cache=False):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        return reply(user) if callable(reply) else reply


def test_chat_that_would_overflow_the_page_gets_one_retry_then_changes_nothing(monkeypatch):
    from app.services import resume_chat

    document = _chat_document()
    content = {"document": document, "original_document": copy.deepcopy(document), "added_entries": [], "fit": {"pages": 1, "target_pages": 1, "scale": 1.0, "font_delta": 0.0, "fits": True}}
    monkeypatch.setattr(resume_chat, "_fit", lambda doc, content: {"pages": 2, "target_pages": 1, "scale": 0.75, "font_delta": -0.75, "fits": False})
    show = {"reply": "Added it back.", "edits": [{"op": "show", "target": "s5e1b3", "text": "", "items": [], "position": 0, "reason": ""}]}
    model = ChatModel([show, show])
    document["sections"][3]["entries"][0]["bullets"][2]["hidden"] = True
    new_content, turn = resume_chat.chat(content, _chat_profile(), None, "Show the freight bullet again", model)
    assert len(model.prompts) == 2 and "must stay at 1" in model.prompts[1]
    assert turn["applied"] == [] and "one page" in turn["text"] and new_content["document"] == content["document"]
    assert [item["role"] for item in new_content["chat"]] == ["user", "assistant"] and not new_content.get("history")


def test_resume_chat_endpoint_applies_changes_clears_approval_and_can_undo(client, auth_header, monkeypatch):
    from app.core.database import SessionLocal
    from app.services.job_sources import NormalizedJob
    from app.services.job_sync import upsert_posting

    client.post("/api/v1/resumes/sample", headers=auth_header)
    resume_id = client.get("/api/v1/resumes", headers=auth_header).json()[0]["id"]
    client.post(f"/api/v1/resumes/{resume_id}/approve", headers=auth_header)
    with SessionLocal() as db:
        _, posting = upsert_posting(db, NormalizedJob(source="greenhouse", external_id="chat-1", title="Data Engineering Intern", company="Example Co",
                                                      description="Requirements\n- Python\n- SQL\n- Airflow", location="Toronto, ON", application_url="https://boards.greenhouse.io/example/jobs/1"))
        db.commit()
        job_id = posting.id
    application_id = client.post("/api/v1/applications", headers=auth_header, json={"job_id": job_id}).json()["id"]
    assert client.post(f"/api/v1/applications/{application_id}/approve", headers=auth_header, json={"acknowledge_unverified": True, "acknowledge_gaps": True}).status_code == 200
    version_id = client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()["resume_version_id"]
    version = client.get(f"/api/v1/resume-versions/{version_id}", headers=auth_header).json()
    assert version["approved_by_user"] is True  # approving the application approved this resume
    bullet = next(b for s in version["content"]["document"]["sections"] if s["key"] in {"projects", "experience"} for e in s.get("entries") or [] for b in e["bullets"] if not b.get("hidden"))
    new_text = bullet["text"].rstrip(".") + ", end to end."

    model = ChatModel([
        {"reply": "Your projects match the Python and SQL requirements; I would lead with the pipeline work.", "edits": []},
        {"reply": "Tightened that bullet.", "edits": [{"op": "rewrite", "target": bullet["id"], "text": new_text, "items": [], "position": 0, "reason": "clearer"}]},
    ])
    monkeypatch.setattr("app.services.ai.get_provider", lambda settings, tier="quality": model)

    asked = client.post(f"/api/v1/resume-versions/{version_id}/chat", headers=auth_header, json={"message": "What would you improve for this job?"}).json()
    assert asked["turn"]["applied"] == [] and asked["approved_by_user"] is True and "Data Engineering Intern" in model.prompts[0]
    assert client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()["status"] == "approved"

    changed = client.post(f"/api/v1/resume-versions/{version_id}/chat", headers=auth_header, json={"message": "Rewrite my first bullet"}).json()
    assert changed["turn"]["applied"][0]["after"] == new_text and changed["can_undo"] is True and changed["approved_by_user"] is False
    assert [item["role"] for item in changed["content"]["chat"]] == ["user", "assistant", "user", "assistant"]
    assert client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()["status"] == "awaiting_review"  # approve again before it is used
    pdf = client.get(f"/api/v1/resume-versions/{version_id}/download?format=pdf&inline=true", headers=auth_header)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    undone = client.post(f"/api/v1/resume-versions/{version_id}/undo", headers=auth_header).json()
    texts = [b["text"] for s in undone["content"]["document"]["sections"] for e in s.get("entries") or [] for b in e["bullets"]]
    assert bullet["text"] in texts and new_text not in texts and undone["can_undo"] is False
    assert client.post(f"/api/v1/resume-versions/{version_id}/approve", headers=auth_header).json()["approved_by_user"] is True
