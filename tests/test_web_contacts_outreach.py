import base64
import email as email_lib
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from jobseeker.db import queries
from jobseeker.db.applications import get_status, transition
from jobseeker.db.contacts_repo import link_contact, people, upsert_contact
from jobseeker.db.core import connect
from jobseeker.gmail.client import GmailUnavailable
from jobseeker.web.app import create_app


class FakeGmail:
    def __init__(self, fail_after=None):
        self.raws, self.fail_after = [], fail_after

    def users(self):
        outer = self

        class Drafts:
            def create(self, userId, body):
                if outer.fail_after is not None and len(outer.raws) >= outer.fail_after:
                    raise GmailUnavailable("expired")
                outer.raws.append(body["message"]["raw"])

                class R:
                    def execute(self):
                        return {"id": f"d{len(outer.raws)}"}
                return R()

        class U:
            def drafts(self):
                return Drafts()
        return U()


def to_and_body(raw):
    msg = email_lib.message_from_bytes(base64.urlsafe_b64decode(raw))
    body = next(p for p in msg.walk() if p.get_content_type() == "text/plain").get_payload(decode=True).decode()
    return msg["To"], body


def link_three(settings, a, statuses=("verified", "verified", "verified")):
    conn = connect(settings.db_path)
    for rank, (name, email, st) in enumerate([("Asha Rao", "asha@cred.club", statuses[0]),
                                               ("Vikram Singh", "vikram@cred.club", statuses[1]),
                                               ("Rahul Sharma", "rahul@cred.club", statuses[2])], start=1):
        cid = upsert_contact(conn, "CRED", name, "PM", f"https://www.linkedin.com/in/{name.split()[0].lower()}",
                             email, st)
        link_contact(conn, a, rank, cid, "peer", "r", "smtp")
    return conn


def client(settings, gmail):
    settings.resume_path.write_bytes(b"%PDF fake")
    return TestClient(create_app(settings, gmail_factory=lambda: gmail), follow_redirects=False)


def test_approve_drafts_top_two_with_own_greetings(settings, seeded):
    a = seeded[0]
    link_three(settings, a)
    gmail = FakeGmail()
    r = client(settings, gmail).post(f"/applications/{a}/approve")
    assert "msg=" in r.headers["location"]
    sent = [to_and_body(raw) for raw in gmail.raws]
    assert [t for t, _ in sent] == ["asha@cred.club", "vikram@cred.club"]
    assert sent[0][1].startswith("Hi Asha,") and sent[1][1].startswith("Hi Vikram,")
    ps = people(connect(settings.db_path), a)
    assert [p["gmail_draft_id"] for p in ps] == ["d1", "d2", None] and ps[2]["emailed_at"] is None
    assert get_status(connect(settings.db_path), a) == "approved"


def test_approve_needs_per_person_confirmation_for_likely(settings, seeded):
    a = seeded[0]
    link_three(settings, a, ("verified", "unverified", "verified"))
    gmail = FakeGmail()
    c = client(settings, gmail)
    r = c.post(f"/applications/{a}/approve")
    assert "err=" in r.headers["location"] and "Vikram" in r.headers["location"] and gmail.raws == []
    r = c.post(f"/applications/{a}/approve", data={"confirm_2": "true"})
    assert len(gmail.raws) == 2


def test_approve_skips_bounced_person(settings, seeded):
    a = seeded[0]
    link_three(settings, a, ("verified", "bounced", "verified"))
    gmail = FakeGmail()
    r = client(settings, gmail).post(f"/applications/{a}/approve")
    assert len(gmail.raws) == 1 and "Vikram" in r.headers["location"]


def test_approve_gmail_fails_midway_keeps_first_draft(settings, seeded):
    a = seeded[0]
    link_three(settings, a)
    gmail = FakeGmail(fail_after=1)
    r = client(settings, gmail).post(f"/applications/{a}/approve")
    assert "Asha" in r.headers["location"] and "Reconnect" in r.headers["location"]
    conn = connect(settings.db_path)
    assert people(conn, a)[0]["gmail_draft_id"] == "d1" and get_status(conn, a) == "approved"


def test_third_person_offered_after_five_days_and_drafted(settings, seeded):
    a = seeded[0]
    conn = link_three(settings, a)
    gmail = FakeGmail()
    c = client(settings, gmail)
    c.post(f"/applications/{a}/approve")
    then = datetime.now(UTC) - timedelta(days=6)
    transition(conn, a, "sent", now=then)
    conn.execute("UPDATE events SET at = ? WHERE application_id = ?", (then.isoformat(timespec="seconds"), a))
    conn.commit()
    [card] = queries.pipeline(conn, datetime.now(UTC))["sent"]
    assert card["third"] == {"name": "Rahul Sharma", "label": "peer"}
    assert "Email #3: Rahul" in c.get("/pipeline").text
    assert "Draft email to #3" in c.get(f"/applications/{a}").text
    r = c.post(f"/applications/{a}/contacts/3/email")
    assert "msg=" in r.headers["location"]
    to, body = to_and_body(gmail.raws[-1])
    assert to == "rahul@cred.club" and body.startswith("Hi Rahul,") and "I also reached out to your colleague earlier." in body
    assert people(connect(settings.db_path), a)[2]["emailed_at"] is not None
    assert queries.pipeline(connect(settings.db_path), datetime.now(UTC))["sent"][0]["third"] is None


def test_reply_suppresses_third(settings, seeded):
    a = seeded[0]
    conn = link_three(settings, a)
    client(settings, FakeGmail()).post(f"/applications/{a}/approve")
    transition(conn, a, "sent")
    transition(conn, a, "replied")
    assert all(card.get("third") is None for cards in queries.pipeline(conn, datetime.now(UTC)).values()
               for card in cards)


def test_not_interested_blocks_all_linked_people(settings, seeded):
    from jobseeker.db.applications import mark_not_interested
    from jobseeker.db.contacts_repo import blocked_profile_urls

    a = seeded[0]
    conn = link_three(settings, a)
    mark_not_interested(conn, a, block_company=False)
    assert len(blocked_profile_urls(conn, "CRED")) == 3
