from jobseeker.db.core import connect
from jobseeker.db.jobs import get_user_job
from jobseeker.db.profile import get_user_prefs


def test_settings_is_fourth_tab(client_as):
    html = client_as(1).get("/settings").text
    tabbar = html.split('class="tabbar"')[1]
    assert tabbar.count("nav-item") == 4 and "/settings" in tabbar


def test_filter_change_previews_then_applies(client_as, settings, seeded):
    web = client_as(1, follow_redirects=False)
    preview = web.post("/settings/prefs/where", data={"cities": ["Hyderabad"]})
    assert preview.status_code == 200 and "This hides" in preview.text
    assert get_user_prefs(connect(settings.db_path), 1).cities != ["Hyderabad"]   # not saved yet
    done = web.post("/settings/prefs/where", data={"cities": ["Hyderabad"], "confirm": "1"})
    assert done.status_code == 303
    assert get_user_prefs(connect(settings.db_path), 1).cities == ["Hyderabad"]


def test_scoring_only_change_saves_without_preview(client_as, settings, monkeypatch):
    called = []
    monkeypatch.setattr("jobseeker.web.settings.reevaluate", lambda *a, **k: called.append(1))
    r = client_as(1, follow_redirects=False).post("/settings/prefs/experience", data={
        "experience_years": "1.3", "drop_if_min_years_at_least": "2.5",
        "experience_summary": "Changed summary", "current_ctc_lpa": "21",
        "title_deny_text": ", ".join(get_user_prefs(connect(settings.db_path), 1).title_deny or [])})
    assert r.status_code == 303 and called == []
    assert "Scores refresh over the next runs" in r.headers["location"].replace("+", " ").replace("%20", " ")


def test_roommate_settings_never_touch_owner(seeded_two, client_as, settings):
    before = get_user_job(connect(settings.db_path), 1, seeded_two["j1"])
    client_as(2, follow_redirects=False).post("/settings/prefs/where", data={"cities": ["Chennai"], "confirm": "1"})
    assert get_user_job(connect(settings.db_path), 1, seeded_two["j1"]) == before


def test_settings_resume_replace_and_facts_save(client_as, settings, monkeypatch, facts):
    from tests.test_resume import pdf_bytes
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", lambda llm, text, model: facts)
    web = client_as(1, follow_redirects=False)
    r = web.post("/settings/resume", files={"resume": ("cv.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code == 303 and r.headers["location"].startswith("/settings")
    assert "Check what we read" in web.get("/settings/resume/status").text
    bad = web.post("/settings/resume", files={"resume": ("x.pdf", b"nope", "application/pdf")})
    assert bad.status_code == 422 and "as a PDF" in bad.text
    assert web.post("/settings/facts", data={"headline": "H", "skills_text": "SQL"}).status_code == 303


def test_profile_links_must_be_https(client_as, settings):
    web = client_as(1, follow_redirects=False)
    assert "err=" in web.post("/settings/profile", data={"linkedin": "javascript:alert(1)", "github": ""}).headers["location"]
    web.post("/settings/profile", data={"linkedin": "https://www.linkedin.com/in/x/", "github": ""})
    assert get_user_prefs(connect(settings.db_path), 1).linkedin == "https://www.linkedin.com/in/x/"


def test_phone_tabbar_has_four_columns():
    from jobseeker.config import REPO_ROOT
    css = (REPO_ROOT / "src" / "jobseeker" / "web" / "static" / "ui.css").read_text()
    assert "grid-template-columns: repeat(4, 1fr)" in css.split(".tabbar { display: grid;")[1].split("}")[0]


def _owner_roles_form(up):
    return {"roles": up.roles, "custom_role": up.custom_role, "title_allow_extra_text": ", ".join(up.title_allow_extra),
            "target_roles_text": "\n".join(up.target_roles_text)}


def test_advanced_matching_shown_only_when_set(seeded_two, client_as):
    assert "Advanced (custom matching)" in client_as(1).get("/settings").text
    assert "Advanced (custom matching)" not in client_as(2).get("/settings").text


def test_unchanged_roles_save_keeps_owner_matching_identical(client_as, settings, app_config):
    from jobseeker.db.profile import load_user_context
    from jobseeker.profile.importer import golden_fields
    web = client_as(1, follow_redirects=False)  # create_app first: ensure_owner fills the owner's email
    conn = connect(settings.db_path)
    before, up = load_user_context(conn, 1, app_config)[0], get_user_prefs(conn, 1)
    r = web.post("/settings/prefs/roles", data=_owner_roles_form(up))
    assert r.status_code == 303 and "Scores refresh" in r.headers["location"].replace("%20", " ")
    after = load_user_context(connect(settings.db_path), 1, app_config)[0]
    assert get_user_prefs(connect(settings.db_path), 1) == up and golden_fields(after) == golden_fields(before)
    assert after == before


def test_editing_title_must_contain_previews_and_target_roles_saves_directly(client_as, settings):
    web, up = client_as(1, follow_redirects=False), get_user_prefs(connect(settings.db_path), 1)
    form = _owner_roles_form(up) | {"title_allow_extra_text": "product"}
    assert "This hides" in web.post("/settings/prefs/roles", data=form).text      # a filter change: preview first
    web.post("/settings/prefs/roles", data=form | {"confirm": "1"})
    assert get_user_prefs(connect(settings.db_path), 1).title_allow_extra == ["product"]
    form2 = _owner_roles_form(get_user_prefs(connect(settings.db_path), 1)) | {"target_roles_text": "Product roles"}
    assert web.post("/settings/prefs/roles", data=form2).status_code == 303     # scorer text only: no preview
    assert get_user_prefs(connect(settings.db_path), 1).target_roles_text == ["Product roles"]


def test_use_the_role_chips_instead_clears_both(client_as, settings):
    web, up = client_as(1, follow_redirects=False), get_user_prefs(connect(settings.db_path), 1)
    form = _owner_roles_form(up) | {"use_chips": "1", "confirm": "1"}
    web.post("/settings/prefs/roles", data=form)
    after = get_user_prefs(connect(settings.db_path), 1)
    assert after.title_allow_extra == [] and after.target_roles_text == [] and after.roles == up.roles
