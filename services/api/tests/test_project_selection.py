"""Choosing projects per job and keeping non-technical roles brief. No network or AI."""

import json
from types import SimpleNamespace

import pytest

from app.services import resume_render
from app.services.tailoring import select_projects, structural_problems


def _entry(entry_id, name, tech, bullets):
    return {
        "id": entry_id,
        "headers": [{"text": name, "right": "", "bold": True, "italic": False}],
        "bullets": [{"id": f"{entry_id}b{i + 1}", "text": text} for i, text in enumerate(bullets)],
        "tech": tech,
        "tech_italic": True,
    }


def _document():
    return {
        "header": {"name": "Sam Lee", "contact_items": []},
        "sections": [
            {"id": "s1", "key": "summary", "kind": "paragraphs", "title": "SUMMARY", "paragraphs": [{"id": "s1p1", "text": "Software engineering student."}]},
            {
                "id": "s3", "key": "projects", "kind": "entries", "title": "PROJECTS",
                "entries": [
                    _entry("s3e1", "Client Booking Platform", "TypeScript, React, Node.js, Firebase", ["Built a booking platform with **React**.", "Used **Firebase** for bookings."]),
                    _entry("s3e2", "QR-Based Store Wayfinding System", "Python, Flask, PostgreSQL", ["Built a **Flask** REST API on **PostgreSQL**.", "Implemented A* search for routes."]),
                    _entry("s3e3", "Football Match Prediction & Data Pipeline", "Python, Airflow, Spark, pandas, XGBoost", ["Built an ETL pipeline with **Airflow**.", "Trained **XGBoost** models."]),
                ],
            },
            {
                "id": "s5", "key": "experience", "kind": "entries", "title": "EXPERIENCE",
                "entries": [
                    _entry("s5e1", "Maple Market — Sales Associate", None, [
                        "Reconcile cash registers during open/close procedures with **100% accuracy**.",
                        "Own pricing accuracy for assigned sections.",
                        "Process incoming freight across **hundreds of SKUs**.",
                        "Resolve daily product-location inquiries — the problem that inspired the wayfinding project above.",
                    ]),
                    _entry("s5e2", "Northfield Parts — Assembly Associate", None, ["Collaborated with **10+ team members** on the line.", "Conducted daily quality checks, resolving defects."]),
                ],
            },
        ],
    }


def _project(project_id, name, technologies, bullets):
    return SimpleNamespace(id=project_id, name=name, technologies=json.dumps(technologies), responsibilities="\n".join(bullets), description="", needs_review=False)


PROFILE = SimpleNamespace(
    projects=[
        _project("11111111-aaaa", "Smart Budget App", ["Python", "FastAPI", "React", "PostgreSQL", "pytest"], ["Built a budgeting app with a FastAPI backend and React frontend.", "Wrote pytest tests for the sync logic."]),
        _project("22222222-bbbb", "ApplyPilot", ["Python", "FastAPI", "Next.js", "Claude API"], ["Built a job assistant with FastAPI and Next.js.", "Integrated the Claude API to tailor resumes."]),
    ]
)


def _posting(title, skills):
    requirements = [SimpleNamespace(category="skill", priority="mandatory", normalized_name=key, name=key) for key in skills]
    return SimpleNamespace(title=title, description="", role_families=None, requirements=requirements)


@pytest.fixture
def page_fits(monkeypatch):
    """Pretend the page fits with up to `limit` projects; beyond that the text would have to shrink."""
    state = {"limit": 3}

    def fake_render(document, style=None, **_kwargs):
        projects = next(s for s in document["sections"] if s["key"] == "projects")["entries"]
        clean = len(projects) <= state["limit"]
        return b"%PDF", {"pages": 1, "target_pages": 1, "scale": 1.0 if clean else 0.85, "font_delta": 0.0 if clean else -0.25, "fits": True}

    monkeypatch.setattr(resume_render, "render_document_pdf", fake_render)
    return state


def _projects(document):
    return [e["headers"][0]["text"] for e in next(s for s in document["sections"] if s["key"] == "projects")["entries"]]


def _visible(document, entry_id):
    entry = next(e for s in document["sections"] for e in s.get("entries") or [] if e["id"] == entry_id)
    return [b["text"] for b in entry["bullets"] if not b.get("hidden")]


def test_picks_the_three_most_relevant_projects_and_adds_profile_projects(page_fits):
    document, changes, optional = select_projects(_document(), None, PROFILE, _posting("Backend Developer Intern", ["fastapi", "python", "llm", "pytest"]))
    names = _projects(document)
    assert set(names[:2]) == {"ApplyPilot", "Smart Budget App"} and len(names) == 3 and optional is None
    added = next(e for s in document["sections"] for e in s.get("entries") or [] if e["headers"][0]["text"] == "ApplyPilot")
    # Same format as the resume's own projects: tech line, and tools bolded like the original.
    assert added["tech"] == "Python, FastAPI, Next.js, Claude API" and added["tech_italic"] is True
    assert "**FastAPI**" in added["bullets"][0]["text"]
    summary = changes[0]
    assert summary["kind"] == "select_projects" and set(summary["added"]) == {"ApplyPilot", "Smart Budget App"} and len(summary["omitted"]) == 2


def test_data_engineering_job_keeps_the_pipeline_project_first(page_fits):
    document, _changes, _optional = select_projects(_document(), None, PROFILE, _posting("Data Engineering Co-op", ["airflow", "spark", "etl", "postgresql", "python"]))
    assert _projects(document)[0] == "Football Match Prediction & Data Pipeline"
    assert len(_projects(document)) == 3


def test_non_technical_roles_stay_brief_and_drop_references_to_hidden_projects(page_fits):
    document, changes, _optional = select_projects(_document(), None, PROFILE, _posting("Machine Learning Intern", ["fastapi", "llm", "pytest", "xgboost"]))
    assert "QR-Based Store Wayfinding System" not in _projects(document)
    retail = _visible(document, "s5e1")
    assert len(retail) == 2 and not any("wayfinding" in text for text in retail)
    # The two kept bullets show different strengths rather than two of the same kind.
    assert any("Reconcile" in text for text in retail)
    assert _visible(document, "s5e2") == ["Collaborated with **10+ team members** on the line.", "Conducted daily quality checks, resolving defects."]
    assert any(c["kind"] == "hide_bullet" and "wayfinding" in c["before"] for c in changes)


def test_reference_bullet_stays_when_its_project_is_shown(page_fits):
    document, _changes, _optional = select_projects(_document(), None, PROFILE, _posting("Backend Developer", ["flask", "postgresql", "rest-apis", "python"]))
    assert "QR-Based Store Wayfinding System" in _projects(document)
    assert any("wayfinding" in text for text in _visible(document, "s5e1"))


def test_fourth_project_only_when_it_fits_without_shrinking(page_fits):
    posting = _posting("Software Engineer Intern", ["fastapi", "python", "llm", "airflow", "react", "flask"])
    document, _changes, optional = select_projects(_document(), None, PROFILE, posting)
    assert len(_projects(document)) == 3 and optional is None
    page_fits["limit"] = 4
    document, changes, optional = select_projects(_document(), None, PROFILE, posting)
    assert len(_projects(document)) == 4 and optional is not None
    assert "fourth" in changes[0]["reason"]


def test_edits_may_keep_projects_added_from_the_profile(page_fits):
    original = _document()
    document, _changes, _optional = select_projects(original, None, PROFILE, _posting("Backend Developer Intern", ["fastapi", "llm"]))
    added = [e for s in document["sections"] for e in s.get("entries") or [] if e.get("from_profile")]
    assert structural_problems(document, original, added) == []
    assert structural_problems(document, original, []) != []


# ---------------------------------------------------------------------------
# Non-technical roles show the soft skills the job asks for
# ---------------------------------------------------------------------------


def test_soft_skills_from_the_posting_choose_and_check_non_technical_bullets(page_fits):
    from app.services.tailoring import check_edit, job_soft_skills

    posting = SimpleNamespace(title="Business Technology Co-op", description="We need a team player with strong communication skills who works well with customers and stakeholders.",
                              role_families=None, requirements=[SimpleNamespace(category="skill", priority="mandatory", normalized_name="sql", name="SQL")])
    assert job_soft_skills(posting)[:2] == ["communication", "customer focus"] or set(job_soft_skills(posting)) >= {"communication", "teamwork", "customer focus"}
    document, _changes, _optional = select_projects(_document(), None, PROFILE, posting)
    # With communication and customer focus wanted, the customer-inquiry bullet beats the freight bullet.
    shown = _visible(document, "s5e1")
    assert any("inquiries" in text for text in shown) or any("Reconcile" in text for text in shown)
    assert not any("freight" in text for text in shown)
    original = "Collaborated with **10+ team members** on the assembly line to maintain smooth, efficient workflows."
    assert check_edit(original, "Showed teamwork by collaborating with **10+ team members** to keep assembly workflows smooth and efficient.", allowed_skills=set(), corpus=original) == []
    assert "leadership" in " ".join(check_edit(original, "Showed leadership by directing **10+ team members** to keep assembly workflows smooth.", allowed_skills=set(), corpus=original))
