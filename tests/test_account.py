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
        moved = roommate_counts[t] if t == "usage" else 0  # this month's spend moves to a tombstone (review #3)
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == owner_before[t] - roommate_counts[t] + moved, t
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


def test_review_2_delete_with_a_blocked_private_contact_keeps_fks_clean(seeded_two, settings):
    """Final review #2: a hand-added contact plus an edited (private) copy, then Not interested, then delete."""
    from jobseeker.db.applications import mark_not_interested, save_contact
    from jobseeker.db.contacts_repo import edit_contact, link_contact, upsert_contact
    conn = connect(settings.db_path)
    app = seeded_two["roommate_app"]
    company = conn.execute("SELECT j.company FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = ?",
                           (app,)).fetchone()[0]
    link_contact(conn, app, 2, upsert_contact(conn, 2, company, "Shared P", "PM", "https://li/sp", "sp@x.com",
                                              "verified"), "peer", "r", "smtp")
    edit_contact(conn, 2, app, 2, "Shared P", "sp2@x.com", "unverified")   # private copy, linked at rank 2
    save_contact(conn, app, name="Mine", role="", linkedin_url="", email="mine@x.com", email_status="unverified")
    mark_not_interested(conn, app, block_company=False)
    assert conn.execute("SELECT COUNT(*) FROM blocklist WHERE user_id = 2 AND contact_id IS NOT NULL").fetchone()[0] >= 2
    delete_account(conn, settings.jobseeker_home, 2)
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE owner_user_id = 2").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_review_3_delete_keeps_this_periods_usage_so_global_caps_dont_reset(seeded_two, settings):
    from jobseeker.clock import app_now
    from jobseeker.config import ContactsConfig
    from jobseeker.db.usage import Budget, outreach_limits
    from jobseeker.pipeline.eligible import eligible_count
    conn = connect(settings.db_path)
    now = app_now()
    limits = outreach_limits(conn, ContactsConfig(), 30)
    Budget(conn, 2, limits, now).spend("draft", 4)
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (2, '2020-01', 'tavily', 99)")
    conn.commit()
    owner = Budget(conn, 1, limits, now)
    before = {s: owner.used_all(s) for s in ("tavily", "draft")}
    eligible_before = eligible_count(conn, "draft")
    delete_account(conn, settings.jobseeker_home, 2)
    assert {s: owner.used_all(s) for s in ("tavily", "draft")} == before    # nobody gets the spent headroom back
    assert conn.execute("SELECT COUNT(*) FROM usage WHERE user_id = 2").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM usage WHERE period = '2020-01'").fetchone()[0] == 0  # old periods go
    tomb = conn.execute("SELECT * FROM users WHERE email = 'deleted-2@invalid'").fetchone()
    assert tomb is not None and tomb["disabled_at"] and not tomb["is_admin"] and not tomb["outreach_enabled"]
    assert eligible_count(conn, "draft") == eligible_before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_review_10_export_has_hand_added_contacts_and_the_blocklist(seeded_two, settings):
    from jobseeker.db.applications import mark_not_interested, save_contact
    conn = connect(settings.db_path)
    app = seeded_two["roommate_app"]
    save_contact(conn, app, name="Mine", role="VP", linkedin_url="", email="mine@x.com", email_status="unverified")
    z = zipfile.ZipFile(io.BytesIO(export_zip(conn, settings.jobseeker_home, 2)))
    mine = next(a for a in json.loads(z.read("applications.json")) if a["id"] == app)
    assert mine["contact"] == {"name": "Mine", "role": "VP", "linkedin_url": "", "email": "mine@x.com",
                               "email_status": "unverified"}
    mark_not_interested(conn, app, block_company=True)
    z = zipfile.ZipFile(io.BytesIO(export_zip(conn, settings.jobseeker_home, 2)))
    blocked = json.loads(z.read("blocklist.json"))
    assert {"company": "cred", "person": None, "reason": "not interested"} in [
        {k: b[k] for k in ("company", "person", "reason")} for b in blocked]
    assert any(b["person"] and b["person"]["email"] == "mine@x.com" for b in blocked)
