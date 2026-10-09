from datetime import UTC, datetime

import pytest

from jobseeker.db.applications import get_application, get_drafts, get_status
from jobseeker.db.core import connect
from jobseeker.db.profile import save_facts
from jobseeker.gmail.client import GmailUnavailable
from jobseeker.outreach.drafter import DraftBundle
from tests.conftest import owner_resume, signed_in_client
from tests.fakes import FakeLLM


class FakeGmail:
    def __init__(self, fail=False):
        self.fail, self.raws = fail, []

    def users(self):
        outer = self

        class Drafts:
            def create(self, userId, body):
                if outer.fail:
                    raise GmailUnavailable("expired")
                outer.raws.append(body["message"]["raw"])

                class R:
                    def execute(self):
                        return {"id": "draft-1"}
                return R()

        class U:
            def drafts(self):
                return Drafts()
        return U()


@pytest.fixture
def ctx(settings, seeded, facts):
    owner_resume(settings).write_bytes(b"%PDF-1.5 fake")
    save_facts(connect(settings.db_path), 1, "x", facts, edited=True, now=datetime.now(UTC))
    gmail = FakeGmail()
    llm = FakeLLM(handler=lambda schema, prompt: DraftBundle(
        contact_role="Founder", contact_reason="r", email_subject="New subject",
        email_body="Fresh body citing 67%.", li_note="n", li_dm="d"))
    client = signed_in_client(settings, llm_factory=lambda: llm, gmail_factory=lambda: gmail,
                        follow_redirects=False)
    return client, settings, seeded, gmail


def db(settings):
    return connect(settings.db_path)


def test_detail_renders(ctx):
    client, _, (a, _), _ = ctx
    r = client.get(f"/applications/{a}")
    assert r.status_code == 200
    assert "Email body citing 67%." in r.text and "<mark>SQL</mark>" in r.text
    assert "Analytics Lead" in r.text


def test_detail_404(ctx):
    client, *_ = ctx
    assert client.get("/applications/999").status_code == 404


def test_approve_requires_contact_email(ctx):
    client, settings, (a, _), _ = ctx
    r = client.post(f"/applications/{a}/approve")
    assert r.status_code == 303 and "err=" in r.headers["location"]
    assert get_status(db(settings), a) == "drafted"


def test_approve_unverified_needs_confirmation_then_creates_draft(ctx):
    client, settings, (a, _), gmail = ctx
    client.post(f"/applications/{a}/contact", data={"name": "Asha", "role": "PM", "linkedin_url": "",
                                                    "email": "asha@cred.club", "email_status": "unverified"})
    r = client.post(f"/applications/{a}/approve")
    assert "err=" in r.headers["location"] and gmail.raws == []
    r = client.post(f"/applications/{a}/approve", data={"confirm_unverified": "true"})
    assert "msg=" in r.headers["location"]
    conn = db(settings)
    assert get_status(conn, a) == "approved"
    assert get_drafts(conn, a)["email"]["gmail_draft_id"] == "draft-1"
    assert len(gmail.raws) == 1


def test_approve_gmail_unavailable_keeps_state(settings, seeded, facts):
    owner_resume(settings).write_bytes(b"%PDF fake")
    a = seeded[0]
    client = signed_in_client(settings, gmail_factory=lambda: FakeGmail(fail=True), follow_redirects=False)
    client.post(f"/applications/{a}/contact", data={"name": "A", "role": "PM", "linkedin_url": "",
                                                    "email": "a@x.com", "email_status": "verified"})
    r = client.post(f"/applications/{a}/approve")
    assert "draft%20not%20created" in r.headers["location"] or "auth-gmail" in r.headers["location"]
    conn = db(settings)
    assert get_status(conn, a) == "drafted"
    assert get_drafts(conn, a)["email"]["body"] == "Email body citing 67%."


def test_edit_draft_marks_edited_and_reopens_approved(ctx):
    client, settings, (a, _), _ = ctx
    client.post(f"/applications/{a}/contact", data={"name": "A", "role": "PM", "linkedin_url": "",
                                                    "email": "a@x.com", "email_status": "verified"})
    client.post(f"/applications/{a}/approve")
    client.post(f"/applications/{a}/drafts/email", data={"subject": "S2", "body": "Edited"})
    conn = db(settings)
    assert get_drafts(conn, a)["email"]["edited"] == 1 and get_status(conn, a) == "drafted"


def test_regenerate_and_draft_now(ctx):
    client, settings, (a, review_app), _ = ctx
    client.post(f"/applications/{review_app}/draft")
    conn = db(settings)
    assert get_status(conn, review_app) == "drafted"
    assert get_drafts(conn, review_app)["email"]["subject"] == "New subject"


def test_status_snooze_notes_followup_not_interested(ctx):
    client, settings, (a, review_app), _ = ctx
    client.post(f"/applications/{a}/notes", data={"notes": "Ping Rohan for referral"})
    client.post(f"/applications/{review_app}/snooze", data={"next": "/"})
    conn = db(settings)
    assert get_application(conn, a)["notes"] == "Ping Rohan for referral"
    assert get_status(conn, review_app) == "snoozed"
    r = client.post(f"/applications/{a}/status", data={"status": "interview"})
    assert "err=" in r.headers["location"]
    client.post(f"/applications/{a}/not-interested", data={"block_company": "true"})
    assert get_status(db(settings), a) == "not_interested"


def _approve(client, a):
    client.post(f"/applications/{a}/contact", data={"name": "A", "role": "PM", "linkedin_url": "",
                                                    "email": "a@x.com", "email_status": "verified"})
    return client.post(f"/applications/{a}/approve")


def test_reapprove_warns_about_older_gmail_draft(ctx):
    client, settings, (a, _), gmail = ctx
    _approve(client, a)
    r = client.post(f"/applications/{a}/drafts/email", data={"subject": "S2", "body": "Edited"})
    assert "update" not in r.headers["location"].lower()
    r = client.post(f"/applications/{a}/approve")
    assert len(gmail.raws) == 2 and "delete" in r.headers["location"].lower()


def test_regenerate_after_approve_reopens_draft(ctx):
    client, settings, (a, _), _ = ctx
    _approve(client, a)
    client.post(f"/applications/{a}/draft")
    assert get_status(db(settings), a) == "drafted"


def test_regenerate_refused_after_sent(ctx):
    client, settings, (a, _), _ = ctx
    _approve(client, a)
    client.post(f"/applications/{a}/status", data={"status": "sent"})
    r = client.post(f"/applications/{a}/draft")
    assert "err=" in r.headers["location"]
    assert get_drafts(db(settings), a)["email"]["body"] == "Email body citing 67%."


def test_approve_adds_greeting_and_signature(ctx):
    import base64
    import email as email_lib

    client, settings, (a, _), gmail = ctx
    client.post(f"/applications/{a}/contact", data={"name": "Asha Rao", "role": "PM", "linkedin_url": "",
                                                    "email": "a@x.com", "email_status": "verified"})
    client.post(f"/applications/{a}/approve")
    msg = email_lib.message_from_bytes(base64.urlsafe_b64decode(gmail.raws[0]))
    body = next(p for p in msg.walk() if p.get_content_type() == "text/plain").get_payload(decode=True).decode()
    assert body.startswith("Hi Asha,\n\nEmail body citing 67%.")
    assert "Asha Owner" in body



def test_draft_now_spends_a_draft_unit_and_stops_at_the_share(ctx):
    from jobseeker.clock import app_now
    from jobseeker.db.profile import load_user_context
    from jobseeker.db.usage import Budget, outreach_limits
    client, settings, (a, review_app), _ = ctx
    conn = db(settings)
    cfg = client.app.state.app_config

    def budget():
        contacts = load_user_context(conn, 1, cfg)[0].contacts
        return Budget(conn, 1, outreach_limits(conn, contacts, cfg.budgets.global_drafts_per_day), app_now())
    client.post(f"/applications/{review_app}/draft")
    assert budget().used("draft") == 1
    b = budget()
    b.spend("draft", b.limits["draft"].share_cap)
    r = client.post(f"/applications/{review_app}/draft", follow_redirects=False)
    assert "drafting%20share%20is%20used" in r.headers["location"]
