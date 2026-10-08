from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.db.applications import (
    BlockedContact, blocked_companies, ensure_application, get_application, get_drafts,
    get_events, get_status, mark_not_interested, record_followup, save_contact, save_draft,
    set_notes, snooze, transition, wake_snoozed,
)
from jobseeker.db.core import connect
from jobseeker.db.jobs import upsert_job
from jobseeker.status import InvalidTransition
from tests.factories import make_job

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)


@pytest.fixture
def app_id():
    conn = connect(":memory:")
    job_id, _ = upsert_job(conn, make_job())
    return conn, ensure_application(conn, 1, job_id, NOW)


def test_ensure_application_idempotent(app_id):
    conn, a = app_id
    job_id = get_application(conn, a)["job_id"]
    assert ensure_application(conn, 1, job_id) == a


def test_transition_logs_event_and_rejects_invalid(app_id):
    conn, a = app_id
    transition(conn, a, "shortlisted", now=NOW)
    assert get_status(conn, a) == "shortlisted"
    ev = get_events(conn, a)[-1]
    assert ev["type"] == "status" and '"to": "shortlisted"' in ev["payload"]
    with pytest.raises(InvalidTransition):
        transition(conn, a, "sent")


def test_snooze_and_wake(app_id):
    conn, a = app_id
    transition(conn, a, "shortlisted", now=NOW)
    snooze(conn, a, NOW + timedelta(days=3), now=NOW)
    assert get_status(conn, a) == "snoozed"
    assert wake_snoozed(conn, NOW + timedelta(days=1)) == 0
    assert wake_snoozed(conn, NOW + timedelta(days=3)) == 1
    assert get_status(conn, a) == "shortlisted"


def test_followups_capped_at_two(app_id):
    conn, a = app_id
    for s in ["shortlisted", "drafted", "approved", "sent"]:
        transition(conn, a, s, now=NOW)
    record_followup(conn, a, NOW)
    record_followup(conn, a, NOW)
    with pytest.raises(ValueError, match="2 follow-ups"):
        record_followup(conn, a, NOW)
    assert get_application(conn, a)["followups_sent"] == 2


def test_drafts_upsert(app_id):
    conn, a = app_id
    save_draft(conn, a, "email", "Hi", "body one")
    save_draft(conn, a, "email", "Hi again", "body two", edited=True)
    drafts = get_drafts(conn, a)
    assert drafts["email"]["body"] == "body two" and drafts["email"]["edited"] == 1


def test_contact_reuse_and_blocklist(app_id):
    conn, a = app_id
    cid = save_contact(conn, a, name="Asha", role="PM", linkedin_url="https://linkedin.com/in/asha",
                       email="asha@cred.club", email_status="unverified")
    assert get_application(conn, a)["contact_id"] == cid
    mark_not_interested(conn, a, block_company=True, now=NOW)
    assert get_status(conn, a) == "not_interested"
    assert "cred" in blocked_companies(conn, 1)
    job2, _ = upsert_job(conn, make_job(source_job_id="other", fingerprint="fp-other"))
    a2 = ensure_application(conn, 1, job2)
    with pytest.raises(BlockedContact):
        save_contact(conn, a2, name="Asha", role="PM", linkedin_url="",
                     email="asha@cred.club", email_status="verified")


def test_notes(app_id):
    conn, a = app_id
    set_notes(conn, a, "Referral via Rohan")
    assert get_application(conn, a)["notes"] == "Referral via Rohan"
