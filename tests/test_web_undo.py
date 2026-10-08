import json
from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.db.applications import (
    can_undo, get_application, get_events, get_status, mark_not_interested, snooze, transition, undo_last_status,
    wake_snoozed,
)
from jobseeker.db.core import connect
from jobseeker.status import InvalidTransition
from tests.conftest import signed_in_client


def test_undo_skip_restores_previous_status(settings, seeded):
    a = seeded[0]  # drafted
    conn = connect(settings.db_path)
    transition(conn, a, "skipped")
    assert can_undo(conn, a)
    assert undo_last_status(conn, a) == "drafted"
    assert get_status(conn, a) == "drafted"
    ev = get_events(conn, a)[-1]
    assert ev["type"] == "undo" and json.loads(ev["payload"]) == {"from": "skipped", "to": "drafted"}
    assert not can_undo(conn, a)  # an undo is not itself undoable


def test_undo_snooze_clears_snooze_fields(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    snooze(conn, a, datetime(2030, 1, 1, tzinfo=UTC))
    assert undo_last_status(conn, a) == "drafted"
    app = get_application(conn, a)
    assert (app["status"], app["snoozed_until"], app["snoozed_from"]) == ("drafted", None, None)


def test_undo_refused_after_not_interested(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    mark_not_interested(conn, a, block_company=False)
    assert not can_undo(conn, a)
    with pytest.raises(InvalidTransition):
        undo_last_status(conn, a)
    assert get_status(conn, a) == "not_interested"


def test_undo_refused_when_status_moved_on(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    transition(conn, a, "skipped")
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id = ?", (a,))
    conn.commit()
    assert not can_undo(conn, a)
    with pytest.raises(InvalidTransition):
        undo_last_status(conn, a)


def test_undo_refused_after_wake_from_snooze(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    snooze(conn, a, now + timedelta(days=3), now=now)
    wake_snoozed(conn, now + timedelta(days=4))
    assert get_status(conn, a) == "drafted"
    assert not can_undo(conn, a)  # undoing a wake would strand the job in "snoozed" with no wake date


def test_undo_route_and_button(settings, seeded):
    a = seeded[0]
    client = signed_in_client(settings, follow_redirects=False)
    client.post(f"/applications/{a}/status", data={"status": "skipped"})
    assert "Undo last change" in client.get(f"/applications/{a}").text
    r = client.post(f"/applications/{a}/undo", data={"next": "/"})
    assert r.status_code == 303 and r.headers["location"].startswith("/?msg=")
    assert get_status(connect(settings.db_path), a) == "drafted"
    r = client.post(f"/applications/{a}/undo")
    assert "err=" in r.headers["location"]


def test_undo_refused_for_system_transition_after_approval(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    transition(conn, a, "approved", {"gmail_draft_id": "G1"})
    transition(conn, a, "drafted", {"reason": "edited after approval"})
    assert not can_undo(conn, a)  # undo would claim "approved" while Gmail holds the old text
    with pytest.raises(InvalidTransition):
        undo_last_status(conn, a)


def test_undoing_an_approval_warns_about_the_gmail_draft(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    transition(conn, a, "approved", {"gmail_draft_id": "G1"})
    client = signed_in_client(settings, follow_redirects=False)
    r = client.post(f"/applications/{a}/undo")
    assert "Gmail" in r.headers["location"] and "delete" in r.headers["location"].lower()


@pytest.mark.parametrize("bad", ["//evil.example/x", "/\\evil.example", "https://evil.example"])
def test_next_must_be_a_local_path(settings, seeded, bad):
    a = seeded[0]
    client = signed_in_client(settings, follow_redirects=False)
    r = client.post(f"/applications/{a}/status", data={"status": "skipped", "next": bad})
    assert r.headers["location"].startswith(f"/applications/{a}?")
