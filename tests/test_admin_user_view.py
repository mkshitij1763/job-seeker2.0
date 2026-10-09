import html
import re
from urllib.parse import unquote

from jobseeker.db.applications import save_contact, save_draft
from jobseeker.db.core import connect


def _seed_roommate_view(settings, seeded_two):
    """User 2: J1 shown and scored (91, shortlisted app), the owner's 2nd job hidden, plus private things the
    admin must never see: facts, a resume, a Gmail grant, a contact's email and a draft."""
    conn = connect(settings.db_path)
    j2 = conn.execute("SELECT job_id FROM applications WHERE id = ?", (seeded_two["owner_apps"][1],)).fetchone()[0]
    conn.execute("INSERT INTO user_jobs (user_id, job_id, filter_reason, jd_hash, evaluated_at) VALUES (2, ?, NULL, 'h', 't')",
                 (seeded_two["j1"],))
    conn.execute("INSERT INTO user_jobs (user_id, job_id, filter_reason, jd_hash, evaluated_at) "
                 "VALUES (2, ?, 'title: excluded', 'h', 't')", (j2,))
    conn.execute("INSERT INTO user_facts (user_id, facts, updated_at) VALUES (2, ?, 't')",
                 ('{"headline": "FACTSECRET headline"}',))
    conn.execute("INSERT INTO gmail_tokens (user_id, account_email, token_enc, connected_at) "
                 "VALUES (2, 'roomie.gmail@example.com', X'00', 't')")
    conn.execute("UPDATE users SET last_login_at = '2026-10-09T08:00:00+00:00' WHERE id = 2")
    app2 = seeded_two["roommate_app"]
    save_contact(conn, app2, name="Hidden Person", role="PM", linkedin_url="", email="hidden.person@acme.com",
                 email_status="verified")
    save_draft(conn, app2, "email", "DRAFTSUBJECT", "DRAFTSECRET body")
    conn.commit()
    resume = settings.jobseeker_home / "data" / "users" / "2" / "resume.pdf"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_bytes(b"%PDF-1.4 RESUMESECRET")
    conn.close()


def _text(page: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))


def test_non_admin_gets_404_on_user_view(seeded_two, client_as):
    c = client_as(2, follow_redirects=False)
    assert c.get("/admin/users/2").status_code == 404
    assert c.get("/admin/users/1").status_code == 404


def test_unknown_user_is_404(seeded_two, client_as):
    assert client_as(1).get("/admin/users/999").status_code == 404


def test_users_card_links_each_email(seeded_two, client_as):
    page = client_as(1).get("/admin").text
    assert 'href="/admin/users/2"' in page and 'href="/admin/users/1"' in page


def test_admin_sees_roommate_account_prefs_counts_jobs_apps_and_usage(seeded_two, client_as, settings):
    _seed_roommate_view(settings, seeded_two)
    r = client_as(1).get("/admin/users/2")
    assert r.status_code == 200
    t = _text(r.text)
    # (a) account
    assert "roomie@example.com" in t and "Roomie" in t and "2026-10-09" in t
    assert "Onboarded: yes" in t and "Outreach: off" in t
    # (b) preferences, readable
    assert "Growth Analyst" in t and "Pune" in t and "Drop jobs asking 5+ years" in t
    # (c) matching counts and the top shown jobs
    assert "Shown 1" in t and "Hidden 1" in t and "Scored 1" in t
    assert "Senior Product Analyst 0" in t and "91" in t
    # (d) applications per status and the recent list
    assert "shortlisted 1" in t
    # (e) usage this month
    assert "tavily" in t and "7" in t


def test_user_view_never_shows_private_data(seeded_two, client_as, settings):
    _seed_roommate_view(settings, seeded_two)
    page = client_as(1).get("/admin/users/2").text
    for secret in ("FACTSECRET", "RESUMESECRET", "resume.pdf", "roomie.gmail@example.com", "hidden.person@acme.com",
                   "Hidden Person", "DRAFTSECRET", "DRAFTSUBJECT", "token"):
        assert secret not in page, secret


def test_owner_page_works_too(seeded_two, client_as):
    r = client_as(1).get("/admin/users/1")
    assert r.status_code == 200
    assert "Outreach: on" in _text(r.text) or "Outreach: off" in _text(r.text)


def test_user_view_is_get_only(seeded_two, client_as):
    assert client_as(1, follow_redirects=False).post("/admin/users/2").status_code == 405


def test_invite_flash_shows_the_app_link_copy_and_test_user_note(seeded_two, client_as, settings):
    c = client_as(1, follow_redirects=False)
    r = c.post("/admin/invites", data={"email": "New@Example.com"})
    assert r.status_code == 303
    page = c.get(r.headers["location"]).text
    t = _text(page)
    assert "Invited new@example.com" in t
    assert settings.base_url in page and "data-copy" in page
    assert ("Also add them as a test user in Google Cloud → OAuth consent screen → Test users, "
            "or Google will block their sign-in.") in t


def test_privacy_disclosure_on_landing_and_first_onboarding_step(seeded_two, anon_client, client_as, settings):
    line = "The admin (the person who invited you) can see your job preferences and application statuses."
    assert line in _text(anon_client().get("/").text)
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (3, 'new@example.com', 'New', 't')")
    conn.commit()
    conn.close()
    first = client_as(3).get("/onboarding/roles")
    assert first.status_code == 200 and line in _text(first.text)
    assert line not in _text(client_as(3).get("/onboarding/where").text)
