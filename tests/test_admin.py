from urllib.parse import unquote

from jobseeker.db.core import connect


def test_non_admin_gets_404(seeded_two, client_as):
    c = client_as(2, follow_redirects=False)
    assert c.get("/admin").status_code == 404
    assert c.post("/admin/invites", data={"email": "x@example.com"}).status_code == 404


def test_invite_add_remove(seeded_two, client_as, settings):
    c = client_as(1, follow_redirects=False)
    assert c.post("/admin/invites", data={"email": "New@Example.com"}).status_code == 303
    assert connect(settings.db_path).execute("SELECT email FROM invites").fetchone()[0] == "new@example.com"
    c.post("/admin/invites/new@example.com/remove")
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM invites").fetchone()[0] == 0


def test_disable_deletes_sessions_and_last_admin_refused(seeded_two, client_as, settings):
    roomie = client_as(2)
    owner = client_as(1, follow_redirects=False)
    assert owner.post("/admin/users/2/disable").status_code == 303
    assert roomie.get("/today", follow_redirects=False).status_code == 303  # signed out
    r = owner.post("/admin/users/1/disable")
    assert "at least one admin" in unquote(r.headers["location"])


def test_usage_table_per_user(seeded_two, client_as):
    html = client_as(1).get("/admin").text
    assert "roomie@example.com" in html and "tavily" in html.lower()


def test_admin_outreach_toggle(seeded_two, client_as, settings):
    from jobseeker.db.users import user_by_id
    owner = client_as(1, follow_redirects=False)
    r = owner.post("/admin/users/2/outreach", data={"enabled": "1"})
    assert r.status_code == 303 and "test%20user" in r.headers["location"].replace("+", "%20")
    assert user_by_id(connect(settings.db_path), 2).outreach_enabled
    assert "Outreach: on" in client_as(1).get("/admin").text
    owner.post("/admin/users/2/outreach", data={"enabled": "0"})
    assert not user_by_id(connect(settings.db_path), 2).outreach_enabled
    assert client_as(2, follow_redirects=False).post("/admin/users/2/outreach", data={"enabled": "1"}).status_code == 404


def test_pipeline_hides_outreach_columns_for_matching_only(seeded_two, client_as):
    html = client_as(2).get("/pipeline").text
    assert "No drafts waiting." not in html and "No Gmail drafts waiting to send." not in html
    assert "Drafted (30d)" not in html


def test_tombstone_users_are_not_listed_as_people(seeded_two, client_as, settings):
    from jobseeker.db.account import delete_account
    conn = connect(settings.db_path)
    delete_account(conn, settings.jobseeker_home, 2)
    tomb = conn.execute("SELECT id FROM users WHERE email = 'deleted-2@invalid'").fetchone()[0]
    html = client_as(1).get("/admin").text
    assert f"/admin/users/{tomb}/" not in html                 # no enable/disable/outreach buttons for it


def test_usage_card_labels_a_deleted_accounts_spend(seeded_two, client_as, settings):
    from datetime import UTC, datetime

    from jobseeker.clock import app_now
    from jobseeker.db.account import delete_account
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (2, ?, 'score', 17)",
                 (app_now(datetime.now(UTC)).strftime("%Y-%m-%d"),))
    conn.commit()
    delete_account(conn, settings.jobseeker_home, 2)
    usage = client_as(1).get("/admin").text.split("Usage", 1)[1]
    assert "Deleted account (2)" in usage and "17" in usage and "deleted-2@invalid" not in usage
