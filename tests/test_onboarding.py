import pytest

from jobseeker.db.core import connect
from jobseeker.db.profile import get_onboarding, get_user_prefs


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
