"""Browser-assisted applications against local copies of Greenhouse, Lever, Ashby, and Workday forms.

These run a real headless Chrome against files in tests/fixtures/ats; nothing leaves the machine.
"""

import functools
import re
import http.server
import threading
from pathlib import Path

import pytest

from app.services.autoapply.applicant import Applicant
from app.services.autoapply.driver import Driver
from app.services.autoapply.fields import Field, label_key
from app.services.autoapply.draft import Draft, check_draft, needs_user
from app.services.autoapply.resolve import resolve

FIXTURES = Path(__file__).parent / "fixtures" / "ats"

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


def _applicant(tmp_path, **saved_extra) -> Applicant:
    resume = tmp_path / "Sam_Lee_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test resume")
    saved = {"work_authorization": "Yes", "sponsorship": "No", "relocation": "Yes", "start_date": "Anytime", "location": "Guelph, ON, Canada", **saved_extra}
    return Applicant(
        values={"first_name": "Sam", "last_name": "Lee", "full_name": "Sam Lee", "preferred_name": "Sam", "email": "sam@example.com", "phone": "647-555-0100",
                "location": "Guelph, ON, Canada", "city": "Guelph", "province": "Ontario", "country": "Canada", "linkedin": "", "github": "https://github.com/samlee",
                "website": "https://github.com/samlee", "school": "York University"},
        saved=saved,
        answers=[{"key": "why_interested", "prompt": "Why are you interested in this role?", "answer": "I build data tools and want to work on yours.", "sensitive": False}],
        company="Example Co",
        employers={"maple market"},
        resume_path=resume,
        job_country="canada",
        resume_text="Software engineering student. Built data tools in Python and SQL.",
        skills=["Python", "SQL"],
    )


# ---------------------------------------------------------------------------
# Answer rules (no browser)
# ---------------------------------------------------------------------------


def test_sensitive_questions_are_never_guessed(tmp_path):
    applicant = _applicant(tmp_path)
    us_question = Field(id="f1", kind="select", label="Are you legally authorized to work in the United States?*", required=True, options=["Yes", "No"])
    assert resolve(us_question, applicant) is None
    canada = Field(id="f2", kind="select", label="Are you legally eligible to work in Canada?", required=True, options=["Yes", "No"])
    assert resolve(canada, applicant).value == "Yes"
    gender = Field(id="f3", kind="select", label="Gender", required=True, options=["Male", "Female", "I don't wish to answer"])
    assert resolve(gender, applicant) is None
    assert resolve(gender, _applicant(tmp_path, voluntary_disclosures="decline")).value == "I don't wish to answer"
    consent = Field(id="f4", kind="checkbox", label="Yes, I have read and consent to the terms and conditions", required=True, options=["x"])
    assert resolve(consent, applicant) is None
    assert resolve(consent, _applicant(tmp_path, consent_privacy="yes")).value is True


def test_answers_come_only_from_verified_sources(tmp_path):
    applicant = _applicant(tmp_path)
    assert resolve(Field(id="a", kind="select", label="Have you previously worked for Example Co?", required=True, options=["Yes", "No"]), applicant).value == "No"
    # Long answers are drafted for each job (with the approved answer as material), not pasted as is.
    assert resolve(Field(id="b", kind="textarea", label="Why are you interested in this role?", required=True), applicant) is None
    unknown = Field(id="c", kind="select", label="Do you have a valid driver's licence?*", required=True, options=["Yes", "No"])
    assert resolve(unknown, applicant) is None
    applicant.run_answers[label_key(unknown.label)] = "Yes"
    assert resolve(unknown, applicant).source == "your_answer"
    # A saved answer also covers a near-identical wording of the same question.
    applicant.saved[label_key("Do you have a valid drivers licence?")] = "No"
    assert resolve(Field(id="e", kind="select", label="Do you have a valid drivers licence", options=["Yes", "No"]), _applicant(tmp_path, **{label_key("Do you have a valid drivers licence?"): "No"})).value == "No"
    honeypot = Field(id="d", kind="text", label="Enter website. This input is for robots only, do not enter if you're human.", name="website")
    assert resolve(honeypot, applicant) is None


# ---------------------------------------------------------------------------
# End to end in a real browser
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def stop_runner_afterwards():
    """The background runner polls the database; stop it so later tests get a quiet database."""
    yield
    from app.services.autoapply.runner import RUNNER

    RUNNER.stop()


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


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


def test_greenhouse_form_pauses_for_an_unknown_question_then_submits(site, page, tmp_path):
    applicant = _applicant(tmp_path)
    page.goto(f"{site}/greenhouse.html")
    driver = Driver(page, "greenhouse", applicant)
    outcome = driver.advance()
    assert outcome.status == "needs_you" and outcome.attention == "questions"
    assert [q["label"] for q in outcome.questions] == ["Are you subject to any employment agreements or post-employment restrictions?"]
    assert page.evaluate("window.submitted") is None
    applicant.run_answers[outcome.questions[0]["key"]] = "No"
    outcome = driver.advance()
    assert outcome.status == "submitted", outcome.message
    assert "Thank you for applying" in outcome.confirmation_text
    sent = page.evaluate("window.submitted")
    assert sent == {"first": "Sam", "last": "Lee", "email": "sam@example.com", "phone": "647-555-0100", "resume": "Sam_Lee_Resume.pdf", "sponsor": "No", "prev": "No", "agreements": "No", "gender": "", "honeypot": ""}


def test_lever_form_with_radios_location_and_declined_voluntary_questions(site, page, tmp_path):
    page.goto(f"{site}/lever.html")
    outcome = Driver(page, "lever", _applicant(tmp_path, voluntary_disclosures="decline")).advance()
    assert outcome.status == "submitted", outcome.message
    sent = page.evaluate("window.submitted")
    assert sent["name"] == "Sam Lee" and sent["location"].startswith("Guelph") and sent["auth"] == "yes" and sent["vet"] == "d"
    assert sent["urls[GitHub]"] == "https://github.com/samlee" and sent["resume"] == "Sam_Lee_Resume.pdf"


def _stub_drafter(answers: dict[str, str], seen: list | None = None):
    """Stands in for Claude: answers questions by label, asks the user about anything else."""
    def draft(fields, applicant):
        out = {}
        for item in fields:
            if seen is not None:
                seen.append(item.label)
            key = label_key(item.label)
            text = next((value for label, value in answers.items() if label.lower() in item.label.lower()), None)
            out[key] = Draft(key, "answer", *check_draft(item, text, applicant)[:1], basis="test", problems=check_draft(item, text, applicant)[1]) if text else Draft(key, "ask_user")
        return out
    return draft


def test_ashby_answers_every_question_and_stops_only_for_the_final_review(site, page, tmp_path):
    page.goto(f"{site}/ashby.html")
    seen = []
    drafter = _stub_drafter({"located in Canada": "Yes", "Why are you interested": "I build data tools in Python and want to work on yours."}, seen)
    driver = Driver(page, "ashby", _applicant(tmp_path), drafter=drafter, submit_mode="review")
    outcome = driver.advance()
    assert outcome.attention == "review" and page.evaluate("window.submitted") is None  # no stop per page
    assert {entry["source"] for entry in driver.summary()} >= {"claude", "profile"}
    assert driver.submit_now().status == "submitted"
    sent = page.evaluate("window.submitted")
    assert sent["located"] == "Yes" and sent["why"].startswith("I build data tools") and sent["resume"] == "Sam_Lee_Resume.pdf"
    assert sorted(seen) == ["Are you currently located in Canada?*", "Why are you interested in this role? Please reference one specific thing about our product.*"]


def test_workday_flow_waits_for_sign_in_and_never_fills_the_honeypot(site, page, tmp_path):
    applicant = _applicant(tmp_path)
    page.goto(f"{site}/workday.html")
    driver = Driver(page, "workday", applicant)
    outcome = driver.advance()
    assert outcome.attention == "login"
    assert page.locator('[data-automation-id="beecatcher"]').input_value() == ""
    page.evaluate("state.signedIn = true; state.step = 'info'; render()")  # the user signs in themselves
    outcome = driver.advance()
    assert outcome.attention == "questions"
    assert [q["label"] for q in outcome.questions] == ["Do you have a valid driver's licence?"]
    applicant.run_answers[outcome.questions[0]["key"]] = "Yes"
    outcome = driver.advance()
    assert outcome.status == "submitted", outcome.message
    data = page.evaluate("window.wd.data")
    assert data["country"] == "Canada" and data["first"] == "Sam" and data["prev"] == "No" and data["resume"] == "Sam_Lee_Resume.pdf" and data["q1"] == "Yes"


def test_review_mode_stops_before_submit_until_asked(site, page, tmp_path):
    page.goto(f"{site}/lever.html")
    driver = Driver(page, "lever", _applicant(tmp_path), submit_mode="review")
    outcome = driver.advance()
    assert outcome.attention == "review" and page.evaluate("window.submitted") is None
    assert driver.submit_now().status == "submitted"


def test_no_confirmation_means_not_submitted(site, page, tmp_path):
    applicant = _applicant(tmp_path)
    applicant.saved[label_key("Are you subject to any employment agreements or post-employment restrictions?")] = "No"
    page.goto(f"{site}/greenhouse.html")
    page.evaluate("window.submitApp = () => {}")  # the site swallows the submit
    driver = Driver(page, "greenhouse", applicant)
    driver._wait_for_result = lambda seconds=30: None
    outcome = driver.advance()
    assert outcome.status == "needs_you" and outcome.attention == "unconfirmed" and driver.submit_clicked


def test_dry_run_neither_uploads_nor_submits(site, page, tmp_path):
    applicant = _applicant(tmp_path)
    applicant.saved[label_key("Are you subject to any employment agreements or post-employment restrictions?")] = "No"
    page.goto(f"{site}/greenhouse.html")
    outcome = Driver(page, "greenhouse", applicant, dry_run=True).advance()
    assert outcome.status == "filled"
    assert page.evaluate("document.getElementById('resume').files.length") == 0
    assert page.evaluate("window.submitted") is None


# ---------------------------------------------------------------------------
# The whole pipeline: API -> background runner -> browser -> database
# ---------------------------------------------------------------------------


def _wait_for_attention(client, headers, run_id, attention, seconds=90):
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/apply/runs/{run_id}", headers=headers).json()
        if run["status"] in {"failed", "interrupted", "submitted"} or (run["status"] == "needs_you" and run["attention"] == attention):
            return run
        time.sleep(0.5)
    return run


def _continue_and_wait(client, headers, run_id, answers, seconds=90):
    """Send answers and wait for the run to act on them and stop again (or finish)."""
    import time

    before = client.get(f"/api/v1/apply/runs/{run_id}", headers=headers).json()
    count = len(client.get(f"/api/v1/apply/runs/{run_id}", headers=headers).json()["events"])
    client.post(f"/api/v1/apply/runs/{run_id}/continue", headers=headers, json={"answers": answers})
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/apply/runs/{run_id}", headers=headers).json()
        if run["status"] in {"failed", "interrupted", "submitted"} or (run["status"] == "needs_you" and len(run["events"]) >= count + 2 and run["updated_at"] != before["updated_at"]):
            return run
        time.sleep(0.4)
    return run


def _wait_for(client, headers, run_id, statuses, seconds=90):
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/apply/runs/{run_id}", headers=headers).json()
        if run["status"] in statuses:
            return run
        time.sleep(0.5)
    raise AssertionError(f"run stayed {run['status']}: {run['message']}")


def test_batch_run_pauses_for_an_answer_then_records_a_confirmed_submission(client, auth_header, site, browser):
    from datetime import datetime, timezone

    from app.core.database import SessionLocal
    from app.services.job_sources import NormalizedJob
    from app.services.job_sync import upsert_posting

    client.post("/api/v1/resumes/sample", headers=auth_header)
    resume_id = client.get("/api/v1/resumes", headers=auth_header).json()[0]["id"]
    client.post(f"/api/v1/resumes/{resume_id}/approve", headers=auth_header)
    with SessionLocal() as db:
        _, posting = upsert_posting(db, NormalizedJob(source="lever", external_id="local-lever", title="Data Engineer Intern", company="Example Co",
                                                      description="Requirements\n- Python\n- SQL", location="Toronto, ON", application_url=f"{site}/lever.html", posted_at=datetime.now(timezone.utc)))
        db.commit()
        job_id = posting.id
    application_id = client.post("/api/v1/applications", headers=auth_header, json={"job_id": job_id}).json()["id"]
    client.put("/api/v1/apply/answers", headers=auth_header, json={"values": {"location": "Guelph, ON, Canada", "voluntary_disclosures": "decline"}})
    unapproved = client.post("/api/v1/apply/runs", headers=auth_header, json={"application_ids": [application_id]}).json()
    assert unapproved["created"] == [] and "Approve" in unapproved["skipped"][0]["reason"]
    approved = client.post(f"/api/v1/applications/{application_id}/approve", headers=auth_header, json={"acknowledge_unverified": True, "acknowledge_gaps": True})
    assert approved.status_code == 200, approved.text
    detail = client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()
    assert detail["autoapply"]["level"] == "assisted"  # a local URL is not a known platform; the generic driver handles it

    batch = client.post("/api/v1/apply/runs", headers=auth_header, json={"application_ids": [application_id], "submit_mode": "auto"}).json()
    run_id = batch["created"][0]
    run = _wait_for(client, auth_header, run_id, {"needs_you", "submitted", "failed"})
    assert run["status"] == "needs_you" and run["attention"] == "questions", run["message"]
    assert client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()["status"] == "submitting"
    question = next(q for q in run["questions"] if "legally eligible" in q["label"])
    client.post(f"/api/v1/apply/runs/{run_id}/continue", headers=auth_header, json={"answers": {question["key"]: "Yes"}})
    run = _wait_for(client, auth_header, run_id, {"submitted", "failed"})
    assert run["status"] == "submitted", run["message"]
    assert "Application submitted" in run["confirmation_text"] and run["has_screenshot"]
    application = client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()
    assert application["status"] == "submitted" and application["is_live_submission"] is True
    assert application["submission_label"] == "Submitted by ApplyPilot (employer confirmed)"
    # The answer was remembered for next time.
    saved = client.get("/api/v1/apply/answers", headers=auth_header).json()
    assert any("legally-eligible" in item["key"] and item["value"] == "Yes" for item in saved["questions"])
    assert client.get("/api/v1/nav-counts", headers=auth_header).json()["apply_needs_you"] == 0


def test_form_embedded_in_a_careers_page_is_opened_directly(site, page, tmp_path):
    page.goto(f"{site}/careers.html")
    driver = Driver(page, "generic", _applicant(tmp_path, voluntary_disclosures="decline"))
    outcome = driver.advance()
    assert outcome.status == "submitted", outcome.message
    assert driver.page.url.endswith("/thanks") and page.evaluate("window.submitted")["name"] == "Sam Lee"


# ---------------------------------------------------------------------------
# Drafted answers and documents on a realistic form
# ---------------------------------------------------------------------------


def test_personal_questions_are_never_drafted_and_drafts_are_checked(tmp_path):
    applicant = _applicant(tmp_path)
    applicant.resume_text = "Built an ETL pipeline in Python and PostgreSQL. Trained XGBoost models against a 33% baseline."
    applicant.skills = ["Python", "SQL", "PostgreSQL"]
    for label in ["Home address*", "Postal code", "Date of birth", "Gender", "Please list two professional references"]:
        assert needs_user(Field(id="x", kind="text", label=label)), label
    # Answered by Claude now (assumptions are marked at the final review).
    for label in ["What are your hourly pay expectations?", "How did you hear about this job?", "Are you available for a 4-month co-op starting in January?"]:
        assert not needs_user(Field(id="x", kind="text", label=label)), label
    assert not needs_user(Field(id="y", kind="textarea", label="Tell us about a technical project you're proud of."))
    project = Field(id="p", kind="textarea", label="Tell us about a project", maxlength=400)
    assert check_draft(project, "I built an ETL pipeline in Python that loads match data into PostgreSQL.", applicant)[1] == []
    assert any("numbers" in problem for problem in check_draft(project, "My pipeline processed 2 million rows a day.", applicant)[1])
    assert any("tools" in problem for problem in check_draft(project, "I deployed it on Kubernetes with Terraform.", applicant)[1])
    languages = Field(id="l", kind="checkbox_group", label="Languages", options=["Python", "Java", "Go"])
    assert check_draft(languages, "Python | Java", applicant) == (["Python", "Java"], [])
    assert check_draft(Field(id="s", kind="select", label="SQL?", options=["Yes", "No"]), "Somewhat", applicant)[1]


def _realistic_applicant(tmp_path):
    applicant = _applicant(tmp_path)
    letter = tmp_path / "Sam_Lee_Cover_Letter.pdf"
    letter.write_bytes(b"%PDF-1.4 cover letter")
    applicant.cover_letter_path = letter
    applicant.values["school"] = "York University"
    applicant.resume_text = "Software Engineering student at York University. Built an ETL pipeline in Python and PostgreSQL. Built a booking platform in React."
    applicant.skills = ["Python", "Java", "JavaScript", "SQL", "PostgreSQL", "React"]
    return applicant


REALISTIC_DRAFTS = {
    "enrolled in a post-secondary": "Yes",
    "experience working with SQL": "Yes",
    "programming languages": "Python | Java | JavaScript",
    "project you're proud of": "I built an ETL pipeline in Python that collects match data from public APIs and stores it in PostgreSQL.",
    "Why do you want to intern": "I want to build Python and SQL services like the ones I built in my pipeline project.",
    "How did you hear": "Company website",
    "anything else": "",
}


def test_realistic_form_answers_everything_but_the_address_and_attaches_the_right_documents(site, page, tmp_path):
    import hashlib

    applicant = _realistic_applicant(tmp_path)
    seen = []
    page.goto(f"{site}/realistic.html")
    driver = Driver(page, "greenhouse", applicant, submit_mode="review", drafter=_stub_drafter(REALISTIC_DRAFTS, seen))
    outcome = driver.advance()
    # Only a fact nobody can infer is asked; everything else was answered and typed.
    assert outcome.attention == "questions", outcome.message
    assert [item["label"] for item in outcome.questions] == ["Home address"]
    assert not any(re.search(r"address|Gender", label) for label in seen), seen
    assert "How did you hear about this job?*" in seen
    # The right document in the right slot, though both buttons say "Attach".
    uploads = page.evaluate("window.uploads")
    assert uploads["resume"]["name"] == "Sam_Lee_Resume.pdf" and uploads["cover_letter"]["name"] == "Sam_Lee_Cover_Letter.pdf"
    assert uploads["resume"]["sha256"] == hashlib.sha256(applicant.resume_path.read_bytes()).hexdigest()

    # The user answers the address and, at the final review, rewrites one of Claude's answers.
    applicant.run_answers[outcome.questions[0]["key"]] = "1 Main St, Guelph, ON"
    outcome = driver.advance()
    assert outcome.attention == "review" and page.evaluate("window.submitted") is None
    why_key = label_key("Why do you want to intern at Example Co?*")
    applicant.run_answers[why_key] = "Example Co's payments work matches the data pipelines I enjoy building."
    driver.approve([], [why_key])
    assert driver.advance().attention == "review"
    sources = {entry["label"]: entry["source"] for entry in driver.summary()}
    assert sources["Why do you want to intern at Example Co?"] == "your_answer" and sources["Tell us about a technical project you're proud of."] == "claude"
    assert sources["First Name"] == "profile" and sources["Resume"] == "approved_document" and sources["Cover letter"] == "approved_document"
    assert driver.submit_now().status == "submitted"
    sent = page.evaluate("window.submitted")
    assert sent["why"].startswith("Example Co's payments") and sent["langs"] == ["Python", "Java", "JavaScript"] and sent["sql"] == "Yes"
    assert sent["address"] == "1 Main St, Guelph, ON" and sent["heard"] == "Company website" and sent["salary"] == "" and sent["gender"] == ""


class _FakeNavigatorModel:
    """Stands in for Claude Haiku: clicks the listed element that leads on, as a sensible model would."""

    def __init__(self):
        self.listings = []

    def structured(self, *, system, user, schema, max_tokens, effort, cache=False):
        listing = user.split("Buttons and links:\n", 1)[1]
        self.listings.append(listing)
        for line in listing.splitlines():
            match = re.match(r"\[(\d+)\] \w+: (Continue to the online form|Proceed)", line)
            if match:
                return {"action": "click", "index": int(match.group(1)), "reason": "leads to the form"}
        return {"action": "need_user", "index": -1, "reason": "unclear"}


def test_unfamiliar_site_navigation_rejected_answer_retry_and_required_cover_letter(site, page, tmp_path, monkeypatch):
    from app.services.autoapply import navigate

    model = _FakeNavigatorModel()
    monkeypatch.setattr("app.services.ai.get_provider", lambda settings, tier="quality": model)
    navigator = navigate.ai_navigator(None)
    calls = {"letter": 0}

    def write_letter():
        calls["letter"] += 1
        path = tmp_path / "Sam_Lee_Cover_Letter.pdf"
        path.write_bytes(b"%PDF-1.4 letter")
        return path, "Dear hiring team, ..."

    def drafter(fields, applicant):
        out = {}
        for item in fields:
            key = label_key(item.label)
            if "years of programming" in item.label:
                # The first answer is in the wrong format; told why, the second one fits.
                out[key] = Draft(key, "answer", "2" if item.error else "two years", basis="resume dates")
        return out

    page.goto(f"{site}/multistep.html")
    driver = Driver(page, "generic", _applicant(tmp_path), drafter=drafter, navigator=navigator, letter_writer=write_letter, submit_mode="auto")
    outcome = driver.advance()
    assert outcome.status == "submitted", outcome.message
    state = page.evaluate("window.ms")
    assert state["rejected"] == 1 and state["data"]["years"] == "2"
    assert state["data"]["resume"] == "Sam_Lee_Resume.pdf" and state["data"]["cover"] == "Sam_Lee_Cover_Letter.pdf" and calls["letter"] == 1
    # The model never saw a third-party sign-in or a submit-type button.
    assert all("Google" not in listing and "Send my application" not in listing for listing in model.listings)


def test_optional_cover_letter_slot_does_not_cost_a_letter(site, page, tmp_path):
    calls = {"letter": 0}

    def write_letter():
        calls["letter"] += 1
        return None

    applicant = _applicant(tmp_path, voluntary_disclosures="decline")
    page.goto(f"{site}/realistic.html")
    Driver(page, "greenhouse", applicant, letter_writer=write_letter, submit_mode="review").advance()
    assert calls["letter"] == 0 and "cover_letter" not in page.evaluate("window.uploads")


def _seed_application(client, headers, site, page_name, external_id, title="Software Engineering Intern"):
    from datetime import datetime, timezone

    from app.core.database import SessionLocal
    from app.services.job_sources import NormalizedJob
    from app.services.job_sync import upsert_posting

    if not client.get("/api/v1/resumes", headers=headers).json():
        client.post("/api/v1/resumes/sample", headers=headers)
        resume_id = client.get("/api/v1/resumes", headers=headers).json()[0]["id"]
        client.post(f"/api/v1/resumes/{resume_id}/approve", headers=headers)
    with SessionLocal() as db:
        _, posting = upsert_posting(db, NormalizedJob(source="greenhouse", external_id=external_id, title=title, company="Example Co",
                                                      description="Requirements\n- Python\n- SQL\n- React", location="Toronto, ON", application_url=f"{site}/{page_name}", posted_at=datetime.now(timezone.utc)))
        db.commit()
        job_id = posting.id
    return client.post("/api/v1/applications", headers=headers, json={"job_id": job_id}).json()["id"]


def test_pipeline_uploads_the_approved_edited_resume_and_remembers_corrections(client, auth_header, site, browser, monkeypatch):
    import pymupdf

    from app.services.autoapply.runner import RUNNER

    monkeypatch.setattr(RUNNER, "_drafter", lambda run_id: _stub_drafter(REALISTIC_DRAFTS))
    application_id = _seed_application(client, auth_header, site, "realistic.html", "local-realistic")
    application = client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()
    version = client.get(f"/api/v1/resume-versions/{application['resume_version_id']}", headers=auth_header).json()
    bullet = next(b for s in version["content"]["document"]["sections"] if s["key"] in {"experience", "projects"} for e in s.get("entries") or [] for b in e["bullets"] if not b.get("hidden"))
    edited = "Automated weekly reporting in Python and SQL for the analytics team."
    assert client.patch(f"/api/v1/resume-versions/{version['id']}", headers=auth_header, json={"text": {bullet["id"]: edited}}).status_code == 200
    client.put("/api/v1/apply/answers", headers=auth_header, json={"values": {"location": "Guelph, ON, Canada", "work_authorization": "Yes", "sponsorship": "No"}})
    assert client.post(f"/api/v1/applications/{application_id}/approve", headers=auth_header, json={"acknowledge_unverified": True, "acknowledge_gaps": True}).status_code == 200

    run_id = client.post("/api/v1/apply/runs", headers=auth_header, json={"application_ids": [application_id], "submit_mode": "review"}).json()["created"][0]
    run = _wait_for(client, auth_header, run_id, {"needs_you", "failed", "interrupted"})
    # Only what nobody can infer (address), what the sample profile lacks (its school is not an option), and a
    # draft that failed the checks twice are asked; everything else was answered and the form filled.
    assert run["attention"] == "questions", run["message"]
    flagged = next(q for q in run["questions"] if q["label"].startswith("Tell us about"))
    assert flagged["status"] == "needs_answer" and flagged["draft"] and flagged["problems"]  # held back, shown with why
    resume_doc = next(doc for doc in run["documents"] if doc["kind"] == "resume")
    assert resume_doc["version_id"] == application["resume_version_id"]
    import hashlib

    uploaded = next(p for p in (Path(get_storage()) / "applications" / application_id).rglob("*_Resume.pdf") if hashlib.sha256(p.read_bytes()).hexdigest() == resume_doc["sha256"])
    assert edited in "".join(page.get_text() for page in pymupdf.open(uploaded)).replace("\n", " ")
    assert {doc["kind"] for doc in run["documents"]} == {"resume"}  # no cover letter: this form does not require one

    typed = {"Home address": "1 Main St, Guelph, ON", "Which school do you currently attend?": "York University",
             "Tell us about a technical project you're proud of.": "I built a reporting tool in Python and SQL for an analytics team."}
    answers = {q["key"]: typed[q["label"]] for q in run["questions"] if q["label"] in typed}
    run = _continue_and_wait(client, auth_header, run_id, answers)
    assert run["attention"] == "review", run["message"]
    filled = {entry["label"]: entry for entry in run["filled"]}
    assert filled["Do you have experience working with SQL databases?"]["source"] == "claude" and filled["How did you hear about this job?"]["source"] == "claude"

    # At the final review the user rewrites one of Claude's answers; it is retyped and remembered.
    why = filled["Why do you want to intern at Example Co?"]
    run = _continue_and_wait(client, auth_header, run_id, {why["key"]: "Your payments platform runs on the Python and SQL I use every day."})
    assert run["attention"] == "review", run["message"]
    assert {entry["label"]: entry for entry in run["filled"]}["Why do you want to intern at Example Co?"]["source"] == "your_answer"
    assert client.get(f"/api/v1/applications/{application_id}", headers=auth_header).json()["status"] == "submitting"
    client.post(f"/api/v1/apply/runs/{run_id}/submit-now", headers=auth_header)
    run = _wait_for(client, auth_header, run_id, {"submitted", "failed"})
    assert run["status"] == "submitted", run["message"]

    saved = {item["key"]: item["value"] for item in client.get("/api/v1/apply/answers", headers=auth_header).json()["questions"]}
    assert saved[label_key("Home address")] == "1 Main St, Guelph, ON"
    from app.core.database import SessionLocal
    from app.models import SavedAnswer

    with SessionLocal() as db:
        example = db.query(SavedAnswer).filter(SavedAnswer.question_key.like("ex:why-do-you-want%")).one()
        assert example.answer.startswith("Your payments platform")


def test_pipeline_refuses_a_resume_tailored_for_another_job(client, auth_header, site, browser):
    from app.core.database import SessionLocal
    from app.models import Application, ApplicationApproval

    first = _seed_application(client, auth_header, site, "lever.html", "local-a", "Data Engineering Intern")
    second = _seed_application(client, auth_header, site, "lever.html", "local-b", "Backend Developer Intern")
    assert first != second
    for application_id in (first, second):
        client.post(f"/api/v1/applications/{application_id}/approve", headers=auth_header, json={"acknowledge_unverified": True, "acknowledge_gaps": True})
    with SessionLocal() as db:
        a, b = db.get(Application, first), db.get(Application, second)
        a.resume_version_id = b.resume_version_id  # point the first application at the second job's resume
        for approval in db.query(ApplicationApproval).filter(ApplicationApproval.application_id == first):
            approval.resume_version_id = b.resume_version_id
        db.commit()
    run_id = client.post("/api/v1/apply/runs", headers=auth_header, json={"application_ids": [first]}).json()["created"][0]
    run = _wait_for(client, auth_header, run_id, {"interrupted", "needs_you", "submitted", "failed"})
    assert run["status"] == "interrupted" and "different job" in run["message"]
    assert client.get(f"/api/v1/applications/{first}", headers=auth_header).json()["status"] == "approved"


def get_storage():
    from app.core.config import get_settings

    return get_settings().storage_path



# ---------------------------------------------------------------------------
# Signing in, creating accounts, and carrying on after sign-in
# ---------------------------------------------------------------------------


class FakeAccounts:
    def __init__(self, email="sam@example.com", password="Secret#2027", allow_create=False):
        self.email, self.password, self.allow_create = email, password, allow_create
        self.recorded = []

    def credentials(self):
        return (self.email, self.password)

    def record(self, host, *, created):
        self.recorded.append((host, created))


def _workday_to_info(driver, page):
    outcome = driver.advance()
    return outcome, page.evaluate("window.wd")


def test_workday_signs_in_with_the_saved_password_and_finishes_every_page(site, page, tmp_path):
    accounts = FakeAccounts()
    page.goto(f"{site}/workday.html?account=sam@example.com:Secret%232027&slow=1")
    applicant = _applicant(tmp_path)
    driver = Driver(page, "workday", applicant, accounts=accounts)
    outcome = driver.advance()
    # It signed in, waited for the slow next page, filled it, and moved through the steps.
    assert outcome.attention == "questions", outcome.message
    assert [q["label"] for q in outcome.questions] == ["Do you have a valid driver's licence?"]
    assert accounts.recorded == [("127.0.0.1:" + site.rsplit(":", 1)[1], False)]
    state = page.evaluate("window.wd")
    assert state["attempts"] == 1 and state["data"]["ext"] == "" and state["data"]["pref"] is False
    applicant.run_answers[outcome.questions[0]["key"]] = "Yes"
    assert driver.advance().status == "submitted"


def test_workday_creates_an_account_only_when_allowed(site, page, tmp_path):
    page.goto(f"{site}/workday.html")
    outcome = Driver(page, "workday", _applicant(tmp_path), accounts=FakeAccounts(allow_create=False)).advance()
    assert outcome.attention == "login" and "did not work" in outcome.message
    assert page.evaluate("window.wd.created") is None

    page.goto(f"{site}/workday.html")
    accounts = FakeAccounts(allow_create=True)
    driver = Driver(page, "workday", _applicant(tmp_path), accounts=accounts)
    outcome = driver.advance()
    assert outcome.attention == "questions", outcome.message
    state = page.evaluate("window.wd")
    assert state["created"] == "sam@example.com" and state["consent"] is True
    assert accounts.recorded[-1][1] is True


def test_rejected_password_is_not_retried(site, page, tmp_path):
    page.goto(f"{site}/workday.html?account=sam@example.com:OtherPassword1!")
    driver = Driver(page, "workday", _applicant(tmp_path), accounts=FakeAccounts())
    first = driver.advance()
    second = driver.advance()
    assert first.attention == second.attention == "login"
    assert page.evaluate("window.wd.attempts") == 1  # one try, then it waits for you


def test_new_account_waits_for_email_verification_then_signs_in(site, page, tmp_path):
    page.goto(f"{site}/workday.html?verify=1")
    driver = Driver(page, "workday", _applicant(tmp_path), accounts=FakeAccounts(allow_create=True))
    outcome = driver.advance()
    assert outcome.attention == "verification" and "verification email" in outcome.message
    page.evaluate("verifyEmail()")  # the user clicks the link in the email
    outcome = driver.advance()
    assert outcome.attention == "questions", outcome.message


def test_waits_for_the_page_after_a_manual_sign_in(site, page, tmp_path):
    page.goto(f"{site}/workday.html?slow=1")
    driver = Driver(page, "workday", _applicant(tmp_path))
    assert driver.advance().attention == "login"
    page.evaluate("state.signedIn = true; enterSite()")  # the user signs in; the next page takes a moment
    outcome = driver.advance()
    assert outcome.attention == "questions", outcome.message


def test_careers_page_with_search_boxes_clicks_apply_first(site, page, tmp_path):
    page.goto(f"{site}/careers2.html")
    outcome = Driver(page, "generic", _applicant(tmp_path, voluntary_disclosures="decline")).advance()
    assert outcome.status == "submitted", outcome.message


def test_waiting_banner_appears_in_the_page_and_goes_away(site, page, tmp_path):
    page.goto(f"{site}/lever.html")
    driver = Driver(page, "lever", _applicant(tmp_path))
    driver.show_banner("2 questions need your answer.")
    assert "2 questions need your answer" in page.locator("#applypilot-waiting-banner").inner_text()
    driver.hide_banner()
    assert page.locator("#applypilot-waiting-banner").count() == 0


def test_job_site_password_goes_to_the_keychain_not_the_database(client, auth_header, monkeypatch):
    from app.services.autoapply import accounts as accounts_module

    vault = {}

    class FakeKeyring:
        def set_password(self, service, user, password):
            vault[(service, user)] = password

        def get_password(self, service, user):
            return vault.get((service, user))

        def delete_password(self, service, user):
            vault.pop((service, user), None)

    monkeypatch.setattr(accounts_module, "_keyring", lambda: FakeKeyring())
    saved = client.put("/api/v1/apply/account", headers=auth_header, json={"password": "Secret#2027", "sign_in": True, "create_accounts": True}).json()
    assert saved["has_password"] and saved["sign_in"] and saved["create_accounts"] and "password" not in saved
    assert list(vault.values()) == ["Secret#2027"]
    from app.core.database import engine

    with engine.connect() as connection:
        dump = "\n".join(str(row) for table in ("user_settings", "saved_answers", "site_accounts") for row in connection.exec_driver_sql(f"select * from {table}"))
    assert "Secret#2027" not in dump
    user_id = client.get("/api/v1/auth/me", headers=auth_header).json()["id"]
    assert accounts_module.Accounts(user_id).credentials() == ("jordan@example.com", "Secret#2027")
    cleared = client.put("/api/v1/apply/account", headers=auth_header, json={"password": ""}).json()
    assert not cleared["has_password"] and not cleared["sign_in"] and vault == {}
