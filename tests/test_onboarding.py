import pytest

from jobseeker.db.core import connect
from jobseeker.db.profile import get_onboarding, get_user_prefs
from tests.test_resume import GOOD, pdf_bytes


@pytest.fixture
def newbie(settings):
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (3, 'new@example.com', 'New Person', 't')")
    conn.execute("INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (3, '{}', 1, 'roles', 't')")
    conn.commit()
    return 3


def test_unonboarded_user_is_sent_to_their_step(newbie, client_as, seeded):
    web = client_as(newbie, follow_redirects=False)
    for path in ("/", "/today", "/pipeline", f"/applications/{seeded[0]}"):
        r = web.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/onboarding/roles", path
    hx = web.get("/today", headers={"HX-Request": "true"})
    assert hx.status_code == 401 and hx.headers["HX-Redirect"] == "/onboarding/roles"


def test_roles_step_validates_and_saves(newbie, client_as, settings):
    web = client_as(newbie, follow_redirects=False)
    bad = web.post("/onboarding/roles", data={})
    assert bad.status_code == 422 and "Pick at least one role" in bad.text
    assert web.post("/onboarding/roles", data={"roles": ["Data Analyst"], "custom_role": ""}).headers["location"] == "/onboarding/where"
    conn = connect(settings.db_path)
    assert get_user_prefs(conn, newbie).roles == ["Data Analyst"]
    assert get_onboarding(conn, newbie)[0] == "where"


def test_resume_after_quitting(newbie, client_as):
    web = client_as(newbie, follow_redirects=False)
    web.post("/onboarding/roles", data={"roles": ["Data Analyst"]})
    web.post("/onboarding/where", data={"cities": ["Pune"], "remote_india_ok": "on"})
    again = client_as(newbie, follow_redirects=False)       # a new session
    assert again.get("/").headers["location"] == "/onboarding/experience"
    page = again.get("/onboarding/where").text               # Back keeps data
    assert 'value="Pune" checked' in page


@pytest.mark.parametrize("form,msg", [
    ({"experience_years": "40", "drop_if_min_years_at_least": "41", "experience_summary": "x"}, "between 0 and 30"),
    ({"experience_years": "3", "drop_if_min_years_at_least": "2", "experience_summary": "x"}, "more than your"),
    ({"experience_years": "1", "drop_if_min_years_at_least": "2", "experience_summary": "x", "current_ctc_lpa": "900"}, "0 and 500"),
])
def test_experience_step_rules(newbie, client_as, form, msg):
    r = client_as(newbie).post("/onboarding/experience", data=form)
    assert r.status_code == 422 and msg in r.text


def test_onboarded_owner_never_sees_onboarding(client_as):
    assert client_as(1, follow_redirects=False).get("/onboarding/roles").status_code == 303


def test_where_step_records_the_choice(newbie, client_as, settings):
    web = client_as(newbie, follow_redirects=False)
    web.post("/onboarding/where", data={"remote_india_ok": "on"})  # remote only, chosen on the step
    assert get_user_prefs(connect(settings.db_path), newbie).where_confirmed is True


def _to_resume_step(web):
    web.post("/onboarding/roles", data={"roles": ["Data Analyst"]})
    web.post("/onboarding/where", data={"cities": ["Pune"]})
    web.post("/onboarding/experience", data={"experience_years": "1", "drop_if_min_years_at_least": "2.5",
                                             "experience_summary": "One year in analytics."})


def test_upload_extracts_once_per_sha(newbie, client_as, settings, monkeypatch, facts):
    calls = []
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", lambda llm, text, model: calls.append(1) or facts)
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    files = {"resume": ("cv.pdf", pdf_bytes(), "application/pdf")}
    assert web.post("/onboarding/resume", files=files).status_code == 303
    assert web.post("/onboarding/resume", files=files).status_code == 303   # same file: cached
    assert calls == [1]
    assert "Check what we read" in web.get("/onboarding/resume/status").text


def test_fourth_extraction_today_refused(newbie, client_as, settings, monkeypatch, facts):
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", lambda llm, text, model: facts)
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    for i in range(3):
        web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes(f"v{i} " + GOOD), "application/pdf")})
    web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes("v9 " + GOOD), "application/pdf")})
    assert "re-read your resume again tomorrow" in web.get("/onboarding/resume/status").text


def test_manual_skills_when_quota_gone_then_finish(newbie, client_as, settings, monkeypatch):
    from jobseeker.llm import LLMQuotaExceeded

    def gone(llm, text, model):
        raise LLMQuotaExceeded("used up")
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", gone)
    queued = []
    monkeypatch.setattr("jobseeker.web.onboarding.first_evaluation", lambda *a: queued.append(a))
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes(), "application/pdf")})
    assert "Enter my skills myself" in web.get("/onboarding/resume/status").text
    r = web.post("/onboarding/facts/manual", data={"headline": "Analyst", "skills_text": "SQL, Excel",
                                                   "achievement": ["Built a dashboard used by 40 people"]})
    assert r.status_code == 303
    assert web.post("/onboarding/finish").headers["location"] == "/onboarding/done"
    assert queued and client_as(newbie, follow_redirects=False).get("/").status_code == 200


def test_finish_with_gap_sends_back(newbie, client_as):
    web = client_as(newbie, follow_redirects=False)
    web.post("/onboarding/roles", data={"roles": ["Data Analyst"]})
    assert web.post("/onboarding/finish").headers["location"].startswith("/onboarding/where")


def test_default_title_exclusions_fit_the_experience_step(newbie, client_as, app_config):
    r = client_as(newbie, follow_redirects=False).post("/onboarding/experience", data={
        "experience_years": "1", "drop_if_min_years_at_least": "2", "experience_summary": "x",
        "title_deny_text": ", ".join(app_config.default_title_deny)})
    assert len(app_config.default_title_deny) > 10 and r.status_code == 303


def test_provider_errors_never_reach_the_page(newbie, client_as, monkeypatch):
    from jobseeker.llm import LLMError

    def bad_key(llm, text, model):
        raise LLMError("AuthenticationError: Error code: 401 - Invalid API Key")
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", bad_key)
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes(), "application/pdf")})
    html = web.get("/onboarding/resume/status").text
    assert "401" not in html and "API Key" not in html and "Enter my skills myself" in html
    assert "read your resume right now" in html


@pytest.mark.parametrize("path,data", [
    ("/onboarding/where", {"cities": ["Chennai"]}),
    ("/onboarding/roles", {"roles": ["Data Analyst"]}),
    ("/onboarding/finish", {}),
    ("/onboarding/facts", {"headline": "H", "skills_text": "SQL"}),
])
def test_onboarded_user_posting_a_step_changes_nothing(client_as, settings, path, data):
    before = get_user_prefs(connect(settings.db_path), 1)
    r = client_as(1, follow_redirects=False).post(path, data=data)
    assert r.status_code == 303 and r.headers["location"] == "/settings"
    conn = connect(settings.db_path)
    assert get_onboarding(conn, 1)[1] is not None and get_user_prefs(conn, 1) == before


def test_clearing_one_achievement_keeps_each_org_with_its_text():
    from starlette.datastructures import FormData

    from jobseeker.web.onboarding import parse_facts_form
    form = FormData([("headline", "H"), ("skills_text", "SQL"),
                     ("achievement_org", "OrgA"), ("achievement", ""),
                     ("achievement_org", "OrgB"), ("achievement", "Grew revenue 20%"),
                     ("achievement_org", "OrgC"), ("achievement", "Cut cost 10%")])
    facts, errors = parse_facts_form(form)
    assert not errors
    assert [(a.org, a.text) for a in facts.achievements] == [("OrgB", "Grew revenue 20%"), ("OrgC", "Cut cost 10%")]


def test_upload_while_reading_is_refused_and_nothing_is_stored(newbie, client_as, settings):
    from datetime import UTC, datetime

    from jobseeker.db.profile import claim_extract
    from jobseeker.profile.resume import resume_path
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    claim_extract(connect(settings.db_path), newbie, datetime.now(UTC))     # an extraction is running
    r = web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes(), "application/pdf")})
    assert "Still reading your previous upload" in web.get(r.headers["location"]).text
    assert not resume_path(settings.jobseeker_home, newbie).exists()


def test_extraction_never_saves_facts_for_a_different_file(newbie, settings, monkeypatch, facts, app_config):
    from jobseeker.db.profile import get_facts
    from jobseeker.profile.extract import run_extract
    from jobseeker.profile.resume import store_resume
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", lambda llm, text, model: facts)
    store_resume(settings.jobseeker_home, newbie, pdf_bytes("B " + GOOD))     # the file on disk is B
    run_extract(settings.db_path, settings.jobseeker_home, newbie, "sha-of-A", app_config, lambda: None)
    assert get_facts(connect(settings.db_path), newbie) is None


def test_an_extraction_that_reads_nothing_gives_its_unit_back(newbie, settings, monkeypatch, app_config):
    from jobseeker.llm import LLMQuotaExceeded
    from jobseeker.profile.extract import run_extract
    from jobseeker.profile.resume import store_resume
    conn = connect(settings.db_path)

    def spent():
        return conn.execute("SELECT COALESCE(SUM(amount), 0) FROM usage WHERE service = 'groq:facts'").fetchone()[0]
    store_resume(settings.jobseeker_home, newbie, pdf_bytes("B " + GOOD))
    run_extract(settings.db_path, settings.jobseeker_home, newbie, "sha-of-A", app_config, lambda: None)
    assert spent() == 0                                             # the file changed: nothing was read

    def quota(llm, text, model):
        raise LLMQuotaExceeded("gone")
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", quota)
    import hashlib

    from jobseeker.profile.resume import resume_path
    sha = hashlib.sha256(resume_path(settings.jobseeker_home, newbie).read_bytes()).hexdigest()
    run_extract(settings.db_path, settings.jobseeker_home, newbie, sha, app_config, lambda: None)
    assert spent() == 0
