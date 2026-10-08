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
