import shutil
from pathlib import Path

import pytest

from jobseeker.config import REPO_ROOT, Settings, UserPrefs, load_app_config, load_preferences, load_rubric
from jobseeker.profile.facts import Achievement, Facts, Role
from jobseeker.db.applications import ensure_application, save_draft, set_suggestion, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import save_score, upsert_job
from jobseeker.models import ScoreResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "profile").mkdir()
    shutil.copy(ROOT / "tests" / "fixtures" / "preferences.yaml", tmp_path / "profile" / "preferences.yaml")
    shutil.copy(ROOT / "rubric.yaml", tmp_path / "rubric.yaml")
    shutil.copy(ROOT / "companies.yaml", tmp_path / "companies.yaml")
    return tmp_path


AUTH_TEST = dict(google_client_id="cid.apps.googleusercontent.com", google_client_secret="secret",
                 base_url="https://testserver", secret_key="k" * 32, owner_email="owner@example.com")


@pytest.fixture(scope="session")
def _imported_home(tmp_path_factory) -> Path:
    """A fresh database with the fixture owner imported (v2), built once per session; `settings` copies it."""
    from datetime import UTC, datetime

    from jobseeker.profile.importer import import_profile
    tpl = tmp_path_factory.mktemp("imported")
    (tpl / "profile").mkdir()
    for name in ("preferences.yaml", "facts.json"):
        shutil.copy(ROOT / "tests" / "fixtures" / name, tpl / "profile" / name)
    conn = connect(tpl / "data" / "jobseeker.db")
    import_profile(conn, 1, tpl / "profile", tpl, datetime.now(UTC))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # everything in the main file, so a plain copy is complete
    conn.close()
    return tpl


@pytest.fixture
def settings(home: Path, _imported_home: Path) -> Settings:
    s = Settings(jobseeker_home=home, groq_api_key="test", **AUTH_TEST)
    shutil.copy(ROOT / "tests" / "fixtures" / "facts.json", home / "profile" / "facts.json")
    shutil.copytree(_imported_home / "config", home / "config")
    s.data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(_imported_home / "data" / "jobseeker.db", s.db_path)
    return s


@pytest.fixture
def prefs(settings):
    return load_preferences(ROOT / "tests" / "fixtures" / "preferences.yaml")


@pytest.fixture
def rubric(settings):
    return load_rubric(REPO_ROOT / "rubric.yaml")


@pytest.fixture
def app_config(settings):
    return load_app_config(settings.app_config_path)


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


@pytest.fixture
def seeded_two(settings, seeded):
    """The owner's `seeded` data, plus user 2 with their own score and application on the owner's first job (J1),
    a blocklist row and a usage row: everything isolation tests try to leak."""
    from datetime import UTC, datetime
    conn = connect(settings.db_path)
    j1 = conn.execute("SELECT job_id FROM applications WHERE id = ?", (seeded[0],)).fetchone()[0]
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (2, 'roomie@example.com', 'Roomie', 't')")
    roomie = UserPrefs(roles=["Growth Analyst"], cities=["Pune"], drop_if_min_years_at_least=5, experience_summary="x")
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (2, ?, 1, NULL, 't', 't')""", (roomie.model_dump_json(),))
    save_score(conn, 2, j1, ScoreResult(score=91, breakdown={}, matches=["Excel"], gaps=[], recommendation="apply",
                                        role_family="growth_analyst"), "m", "v1", "h")
    app2 = ensure_application(conn, 2, j1)
    transition(conn, app2, "shortlisted")
    conn.execute("INSERT INTO blocklist (user_id, company, reason, at) VALUES (2, 'cred', 'not interested', 't')")
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (2, ?, 'tavily', 7)",
                 (datetime.now(UTC).strftime("%Y-%m"),))
    conn.commit()
    conn.close()
    return {"owner_apps": seeded, "roommate_app": app2, "j1": j1}


def owner_resume(settings) -> Path:
    """Where the owner's resume lives (data/users/1/resume.pdf), with its folder created."""
    from jobseeker.profile.resume import resume_path
    path = resume_path(settings.jobseeker_home, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def signed_in_client(settings, user_id: int = 1, *, follow_redirects: bool = True, **app_kwargs):
    """A TestClient carrying a fresh session for user_id; for helpers that only have `settings`."""
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from jobseeker.db.sessions import create_session
    from jobseeker.web.app import create_app

    conn = connect(settings.db_path)
    token = create_session(conn, user_id, datetime.now(UTC))
    conn.close()
    return TestClient(create_app(settings, **app_kwargs), base_url="https://testserver",
                      follow_redirects=follow_redirects, headers={"Origin": "https://testserver"},
                      cookies={"__Host-js_session": token})


@pytest.fixture
def client_as(settings):
    def make(user_id: int = 1, *, follow_redirects: bool = True, **app_kwargs):
        return signed_in_client(settings, user_id, follow_redirects=follow_redirects, **app_kwargs)
    return make


@pytest.fixture
def anon_client(settings):
    from fastapi.testclient import TestClient

    from jobseeker.web.app import create_app
    return lambda **kw: TestClient(create_app(settings, **kw), base_url="https://testserver", follow_redirects=False,
                                   headers={"Origin": "https://testserver"})


@pytest.fixture
def migrated_owner_db(tmp_path):
    """The live-shaped v0 DB plus the fixture profile/, migrated to latest; yields (conn, home)."""
    from jobseeker.db.migrations import migrate
    from tests.test_migrations import _ctx, live_like_v0

    db = live_like_v0(tmp_path / "db.sqlite")
    (tmp_path / "profile").mkdir()
    shutil.copy(ROOT / "tests" / "fixtures" / "preferences.yaml", tmp_path / "profile" / "preferences.yaml")
    shutil.copy(ROOT / "tests" / "fixtures" / "facts.json", tmp_path / "profile" / "facts.json")
    migrate(db, _ctx(tmp_path), tmp_path / "bk")
    conn = connect(db)
    yield conn, tmp_path
    conn.close()
