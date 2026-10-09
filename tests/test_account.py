import io
import json
import zipfile

import pytest

from jobseeker.db.account import delete_account, export_zip, user_scoped_tables
from jobseeker.db.core import connect
from jobseeker.db.users import LastAdmin


def test_export_contains_only_own_data(seeded_two, settings):
    z = zipfile.ZipFile(io.BytesIO(export_zip(connect(settings.db_path), settings.jobseeker_home, 1)))
    assert {"profile.json", "applications.json", "job_verdicts.csv"} <= set(z.namelist())
    apps = json.loads(z.read("applications.json"))
    assert seeded_two["roommate_app"] not in [a["id"] for a in apps]
    assert "growth_analyst" not in z.read("applications.json").decode()


def test_delete_removes_every_user_row_and_keeps_others(seeded_two, settings):
    conn = connect(settings.db_path)
    owner_before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t, _ in user_scoped_tables(conn)}
    (settings.jobseeker_home / "data" / "users" / "2").mkdir(parents=True, exist_ok=True)
    roommate_counts = _counts(conn, 2)
    delete_account(conn, settings.jobseeker_home, 2)
    assert all(n == 0 for n in _counts(conn, 2).values())
    for t, _ in user_scoped_tables(conn):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == owner_before[t] - roommate_counts[t], t
    assert not (settings.jobseeker_home / "data" / "users" / "2").exists()
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = 2").fetchone()[0] == 0


def _counts(conn, uid):
    out = {}
    for t, how in user_scoped_tables(conn):
        if how == "application_id":
            sql = f"SELECT COUNT(*) FROM {t} WHERE application_id IN (SELECT id FROM applications WHERE user_id = ?)"
        else:
            sql = f"SELECT COUNT(*) FROM {t} WHERE {how} = ?"
        out[t] = conn.execute(sql, (uid,)).fetchone()[0]
    return out


def test_last_admin_cannot_delete(settings):
    with pytest.raises(LastAdmin):
        delete_account(connect(settings.db_path), settings.jobseeker_home, 1)


def test_delete_route_needs_typed_email(seeded_two, client_as, settings):
    web = client_as(2, follow_redirects=False)
    assert "4 weeks" in web.get("/settings/delete").text
    assert web.post("/settings/delete", data={"email": "wrong@example.com"}).status_code == 422
    r = web.post("/settings/delete", data={"email": "roomie@example.com"})
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_delete_an_admin_who_invited_people_keeps_fks_clean(seeded_two, settings):
    from datetime import UTC, datetime

    from jobseeker.db.users import add_invite
    conn = connect(settings.db_path)
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = 2")
    add_invite(conn, "friend@example.com", 2, datetime.now(UTC))
    delete_account(conn, settings.jobseeker_home, 2)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT invited_by FROM invites WHERE email = 'friend@example.com'").fetchone()[0] is None


def test_export_route_is_an_attachment(seeded, client_as):
    r = client_as(1).get("/settings/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'attachment; filename="jobseeker-owner@example.com-' in r.headers["content-disposition"]


def test_unonboarded_user_can_still_export_and_delete(client_as, settings):
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (3, 'new@example.com', 'N', 't')")
    conn.execute("INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (3, '{}', 1, 'roles', 't')")
    conn.commit()
    web = client_as(3, follow_redirects=False)
    assert web.get("/settings/export").status_code == 200
    assert web.post("/settings/delete", data={"email": "new@example.com"}).headers["location"] == "/login"


def test_last_admin_delete_route_is_403_and_button_disabled(client_as):
    web = client_as(1, follow_redirects=False)
    assert "You're the only admin" in web.get("/settings/delete").text
    assert web.post("/settings/delete", data={"email": "owner@example.com"}).status_code == 403


def test_delete_covers_gmail_tokens_and_private_contacts(seeded_two, settings):
    from datetime import UTC, datetime

    from jobseeker.crypto import load_token_key
    from jobseeker.db.applications import save_contact
    from jobseeker.db.gmail_tokens import save_token
    from tests.conftest import AUTH_TEST
    conn = connect(settings.db_path)
    key = load_token_key(AUTH_TEST["token_key"])
    save_token(conn, key, 2, "r@gmail.com", "{}", datetime.now(UTC))
    private = save_contact(conn, seeded_two["roommate_app"], name="P", role="", linkedin_url="", email="p@x.com",
                           email_status="unverified")
    shared_before = conn.execute("SELECT COUNT(*) FROM contacts WHERE owner_user_id IS NULL").fetchone()[0]
    delete_account(conn, settings.jobseeker_home, 2)
    assert conn.execute("SELECT COUNT(*) FROM gmail_tokens WHERE user_id = 2").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE id = ?", (private,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE owner_user_id IS NULL").fetchone()[0] == shared_before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_export_has_gmail_json_without_the_token(seeded, settings):
    from datetime import UTC, datetime

    from jobseeker.crypto import load_token_key
    from jobseeker.db.gmail_tokens import save_token
    from tests.conftest import AUTH_TEST
    conn = connect(settings.db_path)
    save_token(conn, load_token_key(AUTH_TEST["token_key"]), 1, "o@gmail.com", '{"refresh_token": "rt-SECRET-42"}',
               datetime.now(UTC))
    z = zipfile.ZipFile(io.BytesIO(export_zip(conn, settings.jobseeker_home, 1)))
    gmail = json.loads(z.read("gmail.json"))
    assert gmail == {"account_email": "o@gmail.com", "connected_at": gmail["connected_at"]}
    assert all(b"rt-SECRET-42" not in z.read(n) and b"token_enc" not in z.read(n) for n in z.namelist() if n != "resume.pdf")
