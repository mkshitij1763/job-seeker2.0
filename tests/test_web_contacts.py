from fastapi.testclient import TestClient

from jobseeker.config import Settings
from jobseeker.contacts.finder import Deps
from jobseeker.db.contacts_repo import people
from jobseeker.db.core import connect
from jobseeker.web.app import create_app
from jobseeker.web.filters import personal_note
from tests.fakes import FakeLLM
from tests.test_contacts_finder import PICKS, FakeSMTP, FakeTavily


def make_client(settings, smtp=None):
    server = smtp or FakeSMTP({"asha.rao@zeptonow.com": 250})

    def deps():
        return Deps(tavily=FakeTavily(), llm=FakeLLM([PICKS]), resolver=lambda d: f"mx.{d}",
                    smtp_factory=lambda host: server, sleep=lambda s: None)
    return TestClient(create_app(settings, contacts_deps_factory=deps), follow_redirects=False)


def zepto(settings, app_id):
    conn = connect(settings.db_path)
    conn.execute("UPDATE jobs SET company = 'Zepto' WHERE id = (SELECT job_id FROM applications WHERE id = ?)", (app_id,))
    conn.commit()


def test_find_contacts_runs_and_card_shows_people(settings, seeded):
    a = seeded[0]
    zepto(settings, a)
    client = make_client(settings)
    r = client.post(f"/applications/{a}/contacts/find")
    assert r.status_code == 303  # background task runs after the response in TestClient
    page = client.get(f"/applications/{a}").text
    assert 'class="card block people"' in page and "Asha Rao" in page and "verified" in page
    assert "Leads product" in page and "https://www.linkedin.com/in/asharao" in page
    assert "Tavily" in page and "/950" in page  # usage line
    assert len(people(connect(settings.db_path), a)) == 3


def test_card_polls_while_running(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET find_status = 'running', find_started_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now') WHERE id = ?", (a,))
    conn.commit()
    html = make_client(settings).get(f"/applications/{a}/contacts/card").text
    assert 'hx-trigger="every 3s"' in html and "Finding contacts" in html


def test_find_without_tavily_key(home, seeded):
    s = Settings(jobseeker_home=home, groq_api_key="test", tavily_api_key="")
    client = TestClient(create_app(s), follow_redirects=False)
    r = client.post(f"/applications/{seeded[0]}/contacts/find")
    assert "TAVILY_API_KEY" in r.headers["location"]


def test_remove_promotes_next_candidate(settings, seeded):
    a = seeded[0]
    zepto(settings, a)
    client = make_client(settings, FakeSMTP(default=250))
    client.post(f"/applications/{a}/contacts/find")
    conn = connect(settings.db_path)
    conn.execute("""INSERT INTO contact_candidates (application_id, position, name, headline, linkedin_url, label, reason, used)
                    VALUES (?, 4, 'Neha Gupta', 'PM @ Zepto', 'https://www.linkedin.com/in/neha', 'peer', 'Spare', 0)""", (a,))
    conn.commit()
    client.post(f"/applications/{a}/contacts/2/remove")
    ps = people(connect(settings.db_path), a)
    assert [p["name"] for p in ps] == ["Asha Rao", "Neha Gupta", "Rahul Kumar Sharma"]
    assert ps[1]["email"] == "neha.gupta@zeptonow.com" and ps[1]["email_source"] == "pattern"


def test_edit_person(settings, seeded):
    a = seeded[0]
    zepto(settings, a)
    client = make_client(settings)
    client.post(f"/applications/{a}/contacts/find")
    client.post(f"/applications/{a}/contacts/1/edit",
                data={"name": "Asha R.", "email": "asha@zeptonow.com", "email_status": "verified"})
    p = people(connect(settings.db_path), a)[0]
    assert (p["name"], p["email"], p["email_status"], p["email_source"]) == ("Asha R.", "asha@zeptonow.com", "verified", "manual")


def test_personal_note():
    assert personal_note("Loved your work on X.", "Asha Rao, PMP") == "Hi Asha, Loved your work on X."
    long = personal_note("x" * 400, "Asha Rao")
    assert len(long) == 300 and long.startswith("Hi Asha, ") and long.endswith("…")
