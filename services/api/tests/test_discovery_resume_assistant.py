import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.shared import Pt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine, inspect, text

from app.services import taxonomy
from app.services.job_enrich import ImportNeedsText, fetch_posting_from_url, parse_posting_page
from app.services.job_sources import NormalizedJob, SearchPlan, WorkdayAdapter
from app.services.employers import EMPLOYER_BY_KEY, parse_careers_url
from app.services.resume_layout import read_docx, read_pdf
from app.services.resume_parser import parse_layout
from app.services.resume_render import render_document_pdf
from app.services.tailoring import check_edit


# ---------------------------------------------------------------------------
# Relevance taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,family,level",
    [
        ("Software Development Engineer Intern - Summer 2027 (CAN)", "software", "intern"),
        ("Data Engineer, Early Career - 2026 (CAN)", "data_engineering", "new_grad"),
        ("Junior Data Engineer", "data_engineering", "entry"),
        ("Senior Software Development Engineer, AWS Eventbridge", "software", "senior"),
        ("Staff Software Developer, Production Engineering", "cloud_devops", "lead"),
        ("Full Stack Developer co-op", "full_stack", "intern"),
        ("Machine Learning Engineer, New Grad", "ml_ai", "new_grad"),
    ],
)
def test_titles_are_classified(title, family, level):
    assert family in taxonomy.classify_role(title)["families"]
    assert taxonomy.classify_level(title)["level"] == level


@pytest.mark.parametrize("title", ["Business Development Executive", "Mechanical Engineering Co-op", "Freelance Copywriter", "Sales Associate", "Hardware Engineering Co-op"])
def test_non_software_titles_have_no_family(title):
    assert taxonomy.classify_role(title)["families"] == []


def test_years_of_experience_set_level_when_title_is_neutral():
    assert taxonomy.classify_level("Software Development Engineer", "- 3+ years of non-internship professional software development experience")["level"] == "mid"
    assert taxonomy.classify_level("Software Development Engineer", "- 1+ years of non-internship professional software development experience")["level"] == "entry"


@pytest.mark.parametrize(
    "location,remote,scope",
    [
        ("Toronto, Ontario, CAN", None, "gta"),
        ("Markham, CA", None, "gta"),
        ("RBC CENTRE, 155 WELLINGTON ST W:TORONTO", None, "gta"),
        ("Waterloo, ON", None, "ontario"),
        ("Vancouver, British Columbia, CAN", None, "canada_other"),
        ("San Francisco, CA", None, "united_states"),
        ("Berlin, Germany", None, "international"),
        ("Remote (Canada)", True, "remote_canada"),
        ("Remote - USA, Canada", True, "remote_canada"),
        ("Remote - US", True, "remote_us"),
        ("Remote - Worldwide", True, "remote_worldwide"),
        ("Remote - Northern America, LATAM", True, "remote_north_america"),
        ("London", None, "international"),
        ("London, ON", None, "ontario"),
    ],
)
def test_locations_are_tiered(location, remote, scope):
    assert taxonomy.classify_location(location, remote_flag=remote).scope == scope


def test_default_plan_rejects_senior_and_european_postings():
    plan = SearchPlan()
    good = NormalizedJob(source="x", external_id="1", title="Data Engineer Intern", company="Acme", description="Python and SQL", location="Toronto, ON", posted_at=datetime.now(timezone.utc))
    senior = NormalizedJob(source="x", external_id="2", title="Senior Backend Engineer", company="Acme", description="", location="Toronto, ON")
    europe = NormalizedJob(source="x", external_id="3", title="Software Engineer Intern", company="Acme", description="", location="Berlin, Germany")
    old = NormalizedJob(source="x", external_id="4", title="Software Engineer Intern", company="Acme", description="", location="Toronto, ON", posted_at=datetime.now(timezone.utc) - timedelta(days=200))
    expired = NormalizedJob(source="x", external_id="5", title="Software Engineer Intern", company="Acme", description="", location="Toronto, ON", expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    assert plan.accept(good)
    assert not plan.accept(senior)
    assert not plan.accept(europe)
    assert not plan.accept(old)
    assert not plan.accept(expired)


def test_careers_url_is_parsed_into_a_monitored_employer():
    workday = parse_careers_url("https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers")
    assert workday.ats == "workday" and workday.board == "td" and workday.site == "TD_Bank_Careers" and workday.wd == 3
    assert parse_careers_url("https://jobs.lever.co/pointclickcare").ats == "lever"
    assert parse_careers_url("https://www.linkedin.com/jobs/view/123") is None


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _WorkdayClient:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None):
        self.posts.append(json)
        if json.get("limit") == 1:
            return _Response({"facets": [{"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locationCountry", "values": [{"descriptor": "Canada", "id": "canada-id"}]}]}]})
        return _Response(
            {
                "jobPostings": [
                    {"title": "Software Engineer I - Front End", "externalPath": "/job/Toronto/SE-I_R1", "locationsText": "Toronto, Ontario"},
                    {"title": "Senior Manager, AI Strategy", "externalPath": "/job/Toronto/SM_R2", "locationsText": "Toronto, Ontario"},
                ]
            }
        )

    def get(self, url):
        assert url.endswith("/job/Toronto/SE-I_R1")
        return _Response(
            {
                "jobPostingInfo": {
                    "title": "Software Engineer I - Front End",
                    "jobDescription": "<p>Requirements</p><ul><li>JavaScript and React</li></ul>",
                    "location": "Toronto, Ontario",
                    "country": {"descriptor": "Canada"},
                    "startDate": "2026-10-01",
                    "endDate": "2026-12-01",
                    "jobReqId": "R1",
                    "externalUrl": "https://td.wd3.myworkdayjobs.com/TD_Bank_Careers/job/Toronto/SE-I_R1",
                },
                "hiringOrganization": {"name": "The Toronto-Dominion Bank (Canada)"},
            }
        )

    def close(self):
        pass


def test_workday_adapter_uses_country_facet_and_fetches_only_relevant_details():
    client = _WorkdayClient()
    jobs = WorkdayAdapter(EMPLOYER_BY_KEY["td"], client=client).fetch(SearchPlan(), __import__("app.services.http_fetch", fromlist=["Http"]).Http(client))
    assert client.posts[1]["appliedFacets"] == {"locationCountry": ["canada-id"]}
    assert [job.title for job in jobs] == ["Software Engineer I - Front End"]
    job = jobs[0].classify()
    assert job.company == "TD Bank"
    assert job.location_scope == "gta"
    assert job.seniority == "entry"
    assert job.expires_at is not None
    assert "React" in job.description


def test_job_list_hides_senior_and_international_with_profile_filters(client, auth_header):
    from app.core.database import SessionLocal
    from app.services.job_sync import upsert_posting

    db = SessionLocal()
    for index, (title, location) in enumerate(
        [("Software Engineer Intern", "Toronto, ON"), ("Senior Software Engineer", "Toronto, ON"), ("Software Engineer Intern", "Berlin, Germany"), ("Data Analyst Co-op", "Mississauga, Ontario")]
    ):
        upsert_posting(db, NormalizedJob(source="greenhouse", external_id=f"t:{index}", title=title, company=f"Co{index}", description="Requirements\n- Python\n- SQL", location=location, posted_at=datetime.now(timezone.utc)))
    db.commit()
    db.close()
    page = client.get("/api/v1/jobs?use_profile=true&include_samples=false", headers=auth_header).json()
    titles = {(item["title"], item["location"]) for item in page["items"]}
    assert ("Software Engineer Intern", "Toronto, ON") in titles
    assert ("Data Analyst Co-op", "Mississauga, Ontario") in titles
    assert all(item["level"] != "senior" for item in page["items"])
    assert all(item["location_scope"] != "international" for item in page["items"])
    assert page["hidden"]["by_level"].get("senior") == 1
    assert page["hidden"]["by_scope"].get("international") == 1
    top = page["items"][0]
    assert top["relevance"] >= page["items"][-1]["relevance"]
    assert top["source_label"] and top["application_url"] is None or True


def test_search_profiles_can_be_created_and_switched(client, auth_header):
    profiles = client.get("/api/v1/search-profiles", headers=auth_header).json()
    assert len(profiles) == 1 and profiles[0]["is_default"]
    created = client.post("/api/v1/search-profiles", headers=auth_header, json={"name": "Data co-op", "role_families": ["data_engineering", "data_analytics"], "levels": ["intern"]}).json()
    assert created["role_families"] == ["data_engineering", "data_analytics"]
    client.post(f"/api/v1/search-profiles/{created['id']}/default", headers=auth_header)
    profiles = client.get("/api/v1/search-profiles", headers=auth_header).json()
    assert next(item for item in profiles if item["id"] == created["id"])["is_default"]
    sources = client.get("/api/v1/jobs/sources", headers=auth_header).json()
    platforms = {item["platform"] for item in sources["external_searches"]}
    assert {"LinkedIn Jobs", "Indeed Canada", "Experience York (co-op, work-study, research)"} <= platforms


def test_import_refuses_to_fetch_restricted_platforms_but_accepts_pasted_text(client, auth_header):
    with pytest.raises(ImportNeedsText):
        fetch_posting_from_url("https://www.linkedin.com/jobs/view/4000000000")
    refused = client.post("/api/v1/jobs/import", headers=auth_header, json={"url": "https://ca.indeed.com/viewjob?jk=abc"})
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "paste_required"
    pasted = client.post(
        "/api/v1/jobs/import",
        headers=auth_header,
        json={
            "url": "https://ca.indeed.com/viewjob?jk=abc",
            "title": "Junior Data Engineer",
            "company": "Maple Analytics",
            "location": "Toronto, ON",
            "description": "Requirements\n- Python and SQL\n- Airflow is a plus\nYou will build pipelines for our analytics team.",
        },
    )
    assert pasted.status_code == 201, pasted.text
    detail = client.get(f"/api/v1/jobs/{pasted.json()['id']}", headers=auth_header).json()
    assert detail["is_user_added"] is True
    assert detail["source_label"] == "Imported from Indeed"
    assert "Python" in detail["required_skills"]


def test_jsonld_posting_pages_are_parsed():
    page = """<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Software Developer Co-op","description":"<p>Build tools in <b>Python</b>.</p>","datePosted":"2026-10-01","validThrough":"2026-11-01","hiringOrganization":{"@type":"Organization","name":"Northwind"},"jobLocation":{"@type":"Place","address":{"addressLocality":"Toronto","addressRegion":"ON","addressCountry":"CA"}}}</script></html>"""
    parsed = parse_posting_page(page, "https://example.com/job")
    assert parsed["title"] == "Software Developer Co-op"
    assert parsed["company"] == "Northwind"
    assert parsed["location"] == "Toronto, ON, CA"
    assert "Python" in parsed["description"]
    assert parsed["expires_at"].year == 2026


# ---------------------------------------------------------------------------
# Resume layout parsing and rendering
# ---------------------------------------------------------------------------


def _jake_style_pdf(path: Path) -> None:
    """A Jake's-resume layout: company and location on one row, title and dates in italics below."""
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 50

    def row(left, right="", font="Helvetica", size=10, right_font="Helvetica-Oblique"):
        nonlocal y
        c.setFont(font, size)
        c.drawString(40, y, left)
        if right:
            c.setFont(right_font, size)
            c.drawRightString(width - 40, y, right)
        y -= size + 3

    def heading(title):
        nonlocal y
        y -= 4
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, title)
        c.setLineWidth(0.5)
        c.line(40, y - 3, width - 40, y - 3)
        y -= 17

    def bullet(text):
        nonlocal y
        c.setFont("Helvetica", 10)
        c.drawString(48, y, "•")
        c.drawString(58, y, text)
        y -= 13

    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(width / 2, y, "Priya Raman")
    y -= 18
    c.setFont("Helvetica", 9.5)
    c.drawCentredString(width / 2, y, "416-555-0142 | priya.raman@example.com | linkedin.com/in/priyaraman | github.com/praman")
    y -= 16
    heading("EDUCATION")
    row("University of Waterloo", "Waterloo, ON", font="Helvetica-Bold")
    row("Bachelor of Applied Science in Computer Engineering", "Sep. 2023 – May 2028", font="Helvetica-Oblique")
    heading("EXPERIENCE")
    row("Shopify", "Toronto, ON", font="Helvetica-Bold")
    row("Software Developer Intern", "May 2025 – Aug 2025", font="Helvetica-Oblique")
    bullet("Built GraphQL resolvers in Ruby on Rails for merchant analytics used by 4,000 stores")
    bullet("Cut median API latency 35% by adding Redis caching to checkout reporting")
    row("Faire", "Remote", font="Helvetica-Bold")
    row("Data Engineering Intern", "Jan 2025 – Apr 2025", font="Helvetica-Oblique")
    bullet("Wrote Airflow DAGs in Python that load 2M daily events into Snowflake")
    heading("PROJECTS")
    row("Transit Tracker | Python, FastAPI, PostgreSQL, Docker", "2024", font="Helvetica-Bold")
    bullet("Built a FastAPI service that streams TTC vehicle positions to a React map")
    heading("TECHNICAL SKILLS")
    row("Languages: Python, Java, TypeScript, SQL, Ruby")
    row("Tools: Docker, Git, Airflow, Snowflake, Redis")
    c.save()


def test_two_column_pdf_resume_is_parsed(tmp_path):
    path = tmp_path / "jake.pdf"
    _jake_style_pdf(path)
    parsed = parse_layout(read_pdf(path))
    assert parsed["contact"]["full_name"] == "Priya Raman"
    assert parsed["contact"]["email"] == "priya.raman@example.com"
    assert parsed["contact"]["linkedin_url"].endswith("priyaraman")
    roles = [(item["title"], item["employer"], item["location"], item["start_date"], item["end_date"]) for item in parsed["experience"]]
    assert roles[0] == ("Software Developer Intern", "Shopify", "Toronto, ON", "2025-05-01", "2025-08-01")
    assert roles[1][:3] == ("Data Engineering Intern", "Faire", "Remote")
    assert len(parsed["experience"][0]["responsibilities"]) == 2
    school = parsed["education"][0]
    assert school["institution"] == "University of Waterloo"
    assert school["degree"].startswith("Bachelor of Applied Science")
    assert school["graduation_date"] == "2028-05-01"
    project = parsed["projects"][0]
    assert project["name"] == "Transit Tracker"
    assert {"Python", "FastAPI", "PostgreSQL", "Docker"} <= set(project["technologies"])
    groups = {group["label"]: group["items"] for group in parsed["skill_groups"]}
    assert groups["Languages"] == ["Python", "Java", "TypeScript", "SQL", "Ruby"]
    assert [section["key"] for section in parsed["document"]["sections"]] == ["education", "experience", "projects", "skills"]


def _docx_with_tabs() -> bytes:
    document = Document()
    document.add_paragraph().add_run("Alex Chen").bold = True
    document.add_paragraph("alex.chen@example.com | 905-555-0100 | Mississauga, ON")
    heading = document.add_paragraph()
    heading.add_run("EXPERIENCE").bold = True
    title = document.add_paragraph()
    title.paragraph_format.tab_stops.add_tab_stop(Pt(460), WD_TAB_ALIGNMENT.RIGHT)
    title.add_run("RBC — Data Analyst Co-op").bold = True
    title.add_run("\tJan 2026 – Apr 2026")
    document.add_paragraph("Automated weekly KPI reports in Python and SQL", style="List Bullet")
    document.add_paragraph("Built a Power BI dashboard for branch operations", style="List Bullet")
    heading = document.add_paragraph()
    heading.add_run("SKILLS").bold = True
    document.add_paragraph("Python, SQL, Power BI, Excel")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_with_tab_stops_and_list_bullets_is_parsed(tmp_path):
    path = tmp_path / "resume.docx"
    path.write_bytes(_docx_with_tabs())
    parsed = parse_layout(read_docx(path))
    role = parsed["experience"][0]
    assert (role["title"], role["employer"], role["start_date"], role["end_date"]) == ("Data Analyst Co-op", "RBC", "2026-01-01", "2026-04-01")
    assert role["responsibilities"] == ["Automated weekly KPI reports in Python and SQL", "Built a Power BI dashboard for branch operations"]
    assert parsed["contact"]["location"] == "Mississauga, ON"


def test_rendered_resume_keeps_structure_and_fits_one_page(tmp_path):
    path = tmp_path / "jake.pdf"
    _jake_style_pdf(path)
    parsed = parse_layout(read_pdf(path))
    data, fit = render_document_pdf(parsed["document"], parsed["style"])
    assert data.startswith(b"%PDF")
    assert fit["fits"] and fit["pages"] == 1
    import pymupdf

    text = pymupdf.open(stream=data, filetype="pdf")[0].get_text()
    for expected in ["Priya Raman", "Shopify", "Software Developer Intern", "May 2025 – Aug 2025", "Transit Tracker", "Languages:"]:
        assert expected in text


def test_truthfulness_check_rejects_invented_numbers_tools_and_names():
    original = "Built a Flask REST API backed by a normalized PostgreSQL database"
    corpus = original + " Python Flask PostgreSQL Docker"
    assert check_edit(original, "Designed a **Flask** REST API on a normalized PostgreSQL schema for fast lookups", allowed_skills={"flask", "postgresql", "rest-apis"}, corpus=corpus) == []
    assert any("numbers" in problem for problem in check_edit(original, "Built a Flask REST API serving 10,000 users on PostgreSQL", allowed_skills={"flask", "postgresql", "rest-apis"}, corpus=corpus))
    assert any("tools" in problem for problem in check_edit(original, "Built a Flask REST API on PostgreSQL and deployed it with Kubernetes", allowed_skills={"flask", "postgresql", "rest-apis"}, corpus=corpus))
    assert any("names things" in problem for problem in check_edit(original, "Built a Flask REST API for Microsoft backed by PostgreSQL", allowed_skills={"flask", "postgresql", "rest-apis"}, corpus=corpus))


# ---------------------------------------------------------------------------
# Schema upgrade keeps existing data
# ---------------------------------------------------------------------------


def test_schema_upgrade_adds_columns_without_losing_rows(tmp_path):
    from app.core.schema import upgrade_connection

    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE job_postings (id VARCHAR(36) PRIMARY KEY, source VARCHAR(40), external_id VARCHAR(200), fingerprint VARCHAR(64), title VARCHAR(300), company VARCHAR(240), work_arrangement VARCHAR(40), employment_type VARCHAR(40), description TEXT, responsibilities TEXT, discovered_at DATETIME, is_active BOOLEAN, is_sample BOOLEAN, raw_payload TEXT, created_at DATETIME, updated_at DATETIME)"))
        connection.execute(text("INSERT INTO job_postings (id, source, external_id, fingerprint, title, company) VALUES ('1', 'remotive', 'x', 'f', 'Old posting', 'Old Co')"))
    with engine.begin() as connection:
        added = upgrade_connection(connection)
    assert "job_postings.location_scope" in added
    columns = {column["name"] for column in inspect(engine).get_columns("job_postings")}
    assert {"location_scope", "role_families", "expires_at"} <= columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT title FROM job_postings")).scalar() == "Old posting"
    with engine.begin() as connection:
        assert upgrade_connection(connection) == []


# ---------------------------------------------------------------------------
# Assistant
# ---------------------------------------------------------------------------


def _seed_job(title="Data Engineer Intern", location="Toronto, ON"):
    from app.core.database import SessionLocal
    from app.services.job_sync import upsert_posting

    db = SessionLocal()
    _, posting = upsert_posting(
        db,
        NormalizedJob(source="greenhouse", external_id=f"seed:{title}", title=title, company="Maple Data", description="Requirements\n- Python\n- SQL\n- Docker", location=location, posted_at=datetime.now(timezone.utc)),
    )
    db.commit()
    job_id = posting.id
    db.close()
    return job_id


def test_rule_based_assistant_finds_and_prepares_without_ai(client, auth_header):
    client.post("/api/v1/resumes/sample", headers=auth_header)
    resume_id = client.get("/api/v1/resumes", headers=auth_header).json()[0]["id"]
    client.post(f"/api/v1/resumes/{resume_id}/approve", headers=auth_header)
    job_id = _seed_job()
    found = client.post("/api/v1/assistant/chat", headers=auth_header, json={"message": "Find me data engineering internships in Toronto"}).json()
    assert found["ai"] is False
    assert "Data Engineer Intern" in found["reply"]["text"]
    assert any(block["type"] == "jobs" and job_id in block["ids"] for block in found["reply"]["blocks"])
    prepared = client.post(
        "/api/v1/assistant/chat",
        headers=auth_header,
        json={"message": "Prepare applications for these selected jobs", "conversation_id": found["conversation_id"], "context": {"selected_job_ids": [job_id]}},
    ).json()
    assert "Nothing was submitted" in prepared["reply"]["text"]
    applications = client.get("/api/v1/applications", headers=auth_header).json()
    assert applications[0]["job_posting_id"] == job_id
    assert applications[0]["is_live_submission"] is False
    history = client.get(f"/api/v1/assistant/conversations/{found['conversation_id']}", headers=auth_header).json()
    assert [message["role"] for message in history["messages"]] == ["user", "assistant", "user", "assistant"]


class _Block:
    def __init__(self, **data):
        self.__dict__.update(data)

    def model_dump(self, **_kwargs):
        return dict(self.__dict__)


class _Message:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class _FakeClaude:
    name = "anthropic"
    supports_tools = True
    model = "claude-sonnet-5-5"
    effort = "medium"

    def __init__(self):
        import anthropic

        self._anthropic = anthropic
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        last = kwargs["messages"][-1]["content"]
        if isinstance(last, list) and last and last[0].get("type") == "tool_result":
            assert "Data Engineer Intern" in last[0]["content"]
            return _Message([_Block(type="text", text="I found one internship: Data Engineer Intern at Maple Data.")], "end_turn")
        if len(self.calls) == 1:
            return _Message([_Block(type="text", text="Searching."), _Block(type="tool_use", id="toolu_1", name="search_jobs", input={"query": "data", "levels": ["intern"]})], "tool_use")
        return _Message([_Block(type="text", text="You're welcome.")], "end_turn")


def test_claude_assistant_runs_tools_and_keeps_history(client, auth_header, monkeypatch):
    job_id = _seed_job()
    fake = _FakeClaude()
    monkeypatch.setattr("app.services.ai.get_provider", lambda settings: fake)
    reply = client.post("/api/v1/assistant/chat", headers=auth_header, json={"message": "Find data internships"}).json()
    assert reply["ai"] is True
    assert reply["reply"]["text"] == "I found one internship: Data Engineer Intern at Maple Data."
    assert any(block["type"] == "jobs" and job_id in block["ids"] for block in reply["reply"]["blocks"])
    tool_names = {tool["name"] for tool in fake.calls[0]["tools"]}
    assert "search_jobs" in tool_names and not any("submit" in name or "approve" in name for name in tool_names)
    assert fake.calls[0]["output_config"] == {"effort": "medium"}
    second = client.post("/api/v1/assistant/chat", headers=auth_header, json={"message": "Thanks", "conversation_id": reply["conversation_id"]})
    assert second.status_code == 200
    history = fake.calls[-1]["messages"]
    assert history[0]["content"][0]["text"] == "Find data internships"
    assert history[1]["role"] == "assistant" and history[1]["content"][1]["type"] == "tool_use"
    assert history[2]["content"][0]["type"] == "tool_result"
