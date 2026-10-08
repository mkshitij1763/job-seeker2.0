from datetime import UTC, datetime, timedelta


from jobseeker.db import queries
from jobseeker.db.applications import transition
from jobseeker.db.contacts_repo import link_contact, upsert_contact
from jobseeker.db.core import connect
from tests.conftest import signed_in_client


def _person(conn, app_id, rank, name):
    cid = upsert_contact(conn, 1, "CRED", name, "PM", f"https://www.linkedin.com/in/{name.lower()}",
                         f"{name.lower()}@cred.club", "verified")
    link_contact(conn, app_id, rank, cid, "peer", "r", "smtp")


def test_today_groups_what_needs_action(settings, seeded):
    a, b = seeded
    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id IN (?, ?)", (a, b))
    conn.commit()
    _person(conn, b, 1, "Asha")
    t = queries.today(conn, 1, datetime.now(UTC))
    assert [r["app_id"] for r in t["find_contacts"]] == [a]
    assert [r["app_id"] for r in t["ready"]] == [b]
    assert t["new_since_yesterday"] == 2

    transition(conn, b, "approved")
    t = queries.today(conn, 1, datetime.now(UTC))
    assert [r["app_id"] for r in t["send"]] == [b] and t["ready"] == []

    transition(conn, b, "sent")
    conn.execute("UPDATE events SET at = ? WHERE application_id = ?",
                 ((datetime.now(UTC) - timedelta(days=6)).isoformat(timespec="seconds"), b))
    conn.execute("UPDATE application_contacts SET emailed_at = '2026-10-01T00:00:00+00:00' WHERE application_id = ?",
                 (b,))
    conn.commit()
    assert [r["app_id"] for r in queries.today(conn, 1, datetime.now(UTC))["followups"]] == [b]


def test_today_page_nav_and_mark_sent(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET status = 'approved' WHERE id = ?", (a,))
    conn.commit()
    c = signed_in_client(settings, follow_redirects=False)
    html = c.get("/today").text
    assert 'href="/today"' in html and "Send in Gmail" in html
    assert f'action="/applications/{a}/status"' in html and 'name="next" value="/today"' in html
    r = c.post(f"/applications/{a}/status", data={"status": "sent", "next": "/today"})
    assert r.headers["location"].startswith("/today?msg=")


def test_today_empty_state(settings):
    html = signed_in_client(settings).get("/today").text
    assert "All caught up" in html
