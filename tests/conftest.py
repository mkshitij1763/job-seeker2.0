import shutil
from pathlib import Path

import pytest

from jobseeker.config import Settings, load_preferences, load_rubric
from jobseeker.profile.facts import Achievement, Facts, Role
from jobseeker.db.applications import ensure_application, save_draft, set_suggestion, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import save_score, upsert_job
from jobseeker.models import ScoreResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "profile").mkdir()
    shutil.copy(ROOT / "profile" / "preferences.yaml", tmp_path / "profile" / "preferences.yaml")
    shutil.copy(ROOT / "rubric.yaml", tmp_path / "rubric.yaml")
    shutil.copy(ROOT / "companies.yaml", tmp_path / "companies.yaml")
    return tmp_path


@pytest.fixture
def settings(home: Path) -> Settings:
    return Settings(jobseeker_home=home, groq_api_key="test")


@pytest.fixture
def prefs(settings):
    return load_preferences(settings.preferences_path)


@pytest.fixture
def rubric(settings):
    return load_rubric(settings.rubric_path)


@pytest.fixture
def facts() -> Facts:
    return Facts(
        headline="Product Analyst at Inito; IIT Roorkee EE 2025",
        roles=[Role(title="Product Analyst", org="Inito", start="July 2025", end="Present"),
               Role(title="Technology Consultant Intern", org="PwC", start="May 2024", end="July 2024")],
        achievements=[
            Achievement(org="Inito", text="Video-led test instructions cut overdipping errors by 67% across 480K+ tests",
                        metrics=["67%", "480K+"]),
            Achievement(org="Inito", text="LightGBM churn model on 30,000+ users with 84% ROC-AUC",
                        metrics=["30,000+", "84%"]),
            Achievement(org="PwC", text="ERCOT 14-day demand forecast cut MAPE from 7.84% to 6.33%",
                        metrics=["14", "7.84%", "6.33%"]),
        ],
        skills=["SQL", "BigQuery", "Amplitude", "A/B Testing", "Python", "Product Discovery"],
        education=["B.Tech Electrical Engineering, IIT Roorkee, 2021-2025"],
    )


@pytest.fixture
def seeded(settings):
    from tests.factories import make_job

    conn = connect(settings.db_path)
    ids = []
    for i, (score, rec) in enumerate([(88, "apply"), (60, "review")]):
        job_id, _ = upsert_job(conn, make_job(source_job_id=f"s{i}", fingerprint=f"fp{i}",
                                              title=f"Senior Product Analyst {i}",
                                              jd_text="We want SQL and A/B Testing skills."))
        save_score(conn, 1, job_id, ScoreResult(score=score, breakdown={"role_fit": 30}, matches=["SQL", "A/B"],
                                             gaps=["Tableau"], recommendation=rec, role_family="senior_product_analyst"),
                   "m", "v1", "h")
        app_id = ensure_application(conn, 1, job_id)
        if rec == "apply":
            transition(conn, app_id, "shortlisted")
            save_draft(conn, app_id, "email", "Subject", "Email body citing 67%.")
            save_draft(conn, app_id, "li_note", "", "Note")
            save_draft(conn, app_id, "li_dm", "", "DM")
            set_suggestion(conn, app_id, "Analytics Lead", "Owns hire", "https://www.linkedin.com/search/x", [])
            transition(conn, app_id, "drafted")
        ids.append(app_id)
    conn.close()
    return tuple(ids)
