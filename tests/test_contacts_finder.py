from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.contacts.finder import Deps, FinderError, find_contacts
from jobseeker.contacts.people import Candidate
from jobseeker.contacts.smtp_verify import PortBlocked
from jobseeker.db.applications import ensure_application, get_application
from jobseeker.db.contacts_repo import find_state, get_domain, people, set_find_status
from jobseeker.db.core import connect
from jobseeker.db.jobs import upsert_job
from tests.factories import make_job
from tests.fakes import FakeLLM

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
TEAM = [{"title": "Asha Rao - Product Lead @ Zepto", "url": "https://in.linkedin.com/in/asharao", "content": ""},
        {"title": "Vikram Singh - Senior PM at Zepto", "url": "https://in.linkedin.com/in/vsingh", "content": ""},
        {"title": "Other Person - PM at Swiggy", "url": "https://in.linkedin.com/in/other", "content": ""}]
RECRUIT = [{"title": "Rahul Kumar Sharma - Talent Acquisition, Zepto", "url": "https://in.linkedin.com/in/rks",
            "content": ""}]
SITE = [{"url": "https://www.zeptonow.com/", "content": ""}]
PUBLIC = [{"url": "https://x", "content": "press: priya.nair@zeptonow.com"}]


class FakeTavily:
    def __init__(self):
        self.queries = []

    def search(self, query, include_domains=None, max_results=10):
        self.queries.append(query)
        if "talent acquisition" in query:
            return RECRUIT
        if "official website" in query:
            return SITE
        if query.startswith('"@'):
            return PUBLIC
        return TEAM


class FakeSMTP:
    def __init__(self, replies=None, default=550):
        self.replies, self.default, self.rcpts = replies or {}, default, []

    def ehlo(self, name=None):
        return 250, b""

    def mail(self, sender):
        return 250, b""

    def rcpt(self, addr):
        self.rcpts.append(addr)
        return self.replies.get(addr, self.default), b""

    def quit(self):
        pass


PICKS = {"picks": [{"index": 0, "label": "hiring_manager", "reason": "Leads product"},
                   {"index": 1, "label": "peer", "reason": "Senior PM on team"},
                   {"index": 2, "label": "recruiter", "reason": "Hires product roles"}]}


def setup_app():
    conn = connect(":memory:")
    job_id, _ = upsert_job(conn, make_job(company="Zepto", title="Associate Product Manager",
                                          jd_text="Own the funnel. 1-2 years of experience."))
    return conn, ensure_application(conn, job_id, NOW)


def llm_for(picks=PICKS, domain_index=0):
    from jobseeker.contacts.people import Picks
    return FakeLLM(handler=lambda schema, prompt: picks if schema is Picks else {"index": domain_index})


def deps(smtp=None, llm=None, tavily=None, **kw):
    server = smtp or FakeSMTP()
    factory = kw.pop("smtp_factory", lambda host: server)
    return Deps(tavily=tavily or FakeTavily(), llm=llm or llm_for(), resolver=lambda d: f"mx.{d}",
                smtp_factory=factory, sleep=lambda s: None, now=lambda: NOW, **kw), server


def test_finds_three_people_and_verifies_emails(prefs):
    conn, app = setup_app()
    smtp = FakeSMTP({"priya.nair@zeptonow.com": 250, "asha.rao@zeptonow.com": 250,
                     "vikram.singh@zeptonow.com": 250, "rahul.sharma@zeptonow.com": 250})
    d, server = deps(smtp)
    summary = find_contacts(conn, app, prefs, d)
    ps = people(conn, app)
    assert [(p["rank"], p["name"], p["email"], p["email_status"], p["wave"]) for p in ps] == [
        (1, "Asha Rao", "asha.rao@zeptonow.com", "verified", 1),
        (2, "Vikram Singh", "vikram.singh@zeptonow.com", "verified", 1),
        (3, "Rahul Kumar Sharma", "rahul.sharma@zeptonow.com", "verified", 2)]
    assert summary["people"] == 3 and summary["verified"] == 3
    assert get_domain(conn, "zepto")["pattern"] == "first.last"
    assert get_application(conn, app)["contact_id"] == ps[0]["contact_id"]
    assert all(p["email_source"] == "smtp" for p in ps)


def test_catch_all_domain_gives_likely_emails(prefs):
    conn, app = setup_app()
    d, _ = deps(FakeSMTP(default=250))
    summary = find_contacts(conn, app, prefs, d)
    ps = people(conn, app)
    assert summary["verified"] == 0
    assert [(p["email"], p["email_status"], p["email_source"]) for p in ps][0] == (
        "asha.rao@zeptonow.com", "unverified", "pattern")
    assert get_domain(conn, "zepto")["catch_all"] == 1


def test_port_blocked_gives_likely_and_note(prefs):
    conn, app = setup_app()

    def blocked(host):
        raise OSError("timed out")
    d, _ = deps(smtp_factory=blocked)
    summary = find_contacts(conn, app, prefs, d)
    assert any("Couldn't verify on this network" in n for n in summary["notes"])
    assert {p["email_status"] for p in people(conn, app)} == {"unverified"}


def test_blocked_people_are_excluded(prefs):
    conn, app = setup_app()
    d, _ = deps(FakeSMTP(default=250))
    find_contacts(conn, app, prefs, d)
    for p in people(conn, app):  # all three said not interested (Task 8 makes Not interested do this)
        conn.execute("INSERT INTO blocklist (contact_id, company, reason, at) VALUES (?, '', 'not interested', ?)",
                     (p["contact_id"], NOW.isoformat()))
    conn.commit()
    job2, _ = upsert_job(conn, make_job(company="Zepto", title="Product Manager", source_job_id="z2", fingerprint="z2"))
    app2 = ensure_application(conn, job2, NOW)
    d2, _ = deps(FakeSMTP(default=250), llm=llm_for({"picks": [{"index": 0, "label": "peer", "reason": "r"}]}))
    with pytest.raises(FinderError):
        find_contacts(conn, app2, prefs, d2)  # every Zepto person found is blocked -> nobody left


def test_missing_tavily_raises(prefs):
    conn, app = setup_app()
    d, _ = deps()
    d.tavily = None
    with pytest.raises(FinderError, match="TAVILY_API_KEY"):
        find_contacts(conn, app, prefs, d)


def test_budget_exhausted_skips_searches(prefs):
    conn, app = setup_app()
    prefs.contacts.tavily_monthly_limit = 0
    d, _ = deps()
    with pytest.raises(FinderError, match="Tavily budget"):
        find_contacts(conn, app, prefs, d)


def test_apify_fallback_when_too_few_people(prefs):
    class Apify:
        SEARCH_PAGE_USD, PROFILE_EMAIL_USD = 0.10, 0.01

        def __init__(self):
            self.calls = []

        def search_people(self, company, words, location):
            self.calls.append("search")
            return [Candidate("Neha Gupta", "Recruiter at Zepto", "https://www.linkedin.com/in/neha")]

        def profile_email(self, url):
            self.calls.append(url)
            return "neha@zeptonow.com" if "neha" in url else None

    class FewTavily(FakeTavily):
        def search(self, query, include_domains=None, max_results=10):
            if "talent acquisition" in query or query.startswith('"@'):
                return []
            return SITE if "official website" in query else TEAM[:1]

    conn, app = setup_app()
    apify = Apify()
    llm = llm_for({"picks": [{"index": 0, "label": "hiring_manager", "reason": "a"},
                             {"index": 1, "label": "recruiter", "reason": "b"}]})
    d, _ = deps(FakeSMTP(default=250), llm=llm, tavily=FewTavily(), apify=apify)
    find_contacts(conn, app, prefs, d)
    ps = people(conn, app)
    assert [p["name"] for p in ps] == ["Asha Rao", "Neha Gupta"]
    assert ps[1]["email"] == "neha@zeptonow.com" and ps[1]["email_status"] == "verified" and ps[1]["email_source"] == "apify"
    assert "search" in apify.calls


def test_find_state_times_out():
    conn, app = setup_app()
    set_find_status(conn, app, "running")
    conn.execute("UPDATE applications SET find_started_at = ? WHERE id = ?",
                 ((NOW - timedelta(minutes=11)).isoformat(timespec="seconds"), app))
    conn.commit()
    state = find_state(conn, app, NOW)
    assert state["status"] == "failed" and "timed out" in state["note"]


def test_mail_server_refusing_checks_gives_likely_and_note(prefs):
    conn, app = setup_app()

    class Refusing(FakeSMTP):
        def rcpt(self, addr):
            return 550, b"5.7.1 Access denied, policy"
    d, _ = deps(Refusing())
    summary = find_contacts(conn, app, prefs, d)
    assert any("refused verification" in n for n in summary["notes"])
    assert {p["email_status"] for p in people(conn, app)} == {"unverified"}


def test_unclear_company_website_leaves_emails_not_found(prefs):
    conn, app = setup_app()
    d, _ = deps(llm=llm_for(domain_index=-1))
    summary = find_contacts(conn, app, prefs, d)
    assert any("email domain" in n for n in summary["notes"])
    assert {p["email"] for p in people(conn, app)} == {""}


def test_website_search_uses_city_and_india(prefs):
    conn, app = setup_app()
    tavily = FakeTavily()
    d, _ = deps(tavily=tavily)
    find_contacts(conn, app, prefs, d)
    assert '"Zepto" bengaluru India official website' in tavily.queries


def test_domain_without_mail_server_builds_no_emails(prefs):
    conn, app = setup_app()

    class Hunter:
        calls = 0

        def domain_search(self, domain):
            Hunter.calls += 1
            return {"pattern": "first", "emails": []}
    d, _ = deps(hunter=Hunter())
    d.resolver = lambda domain: None  # nothing receives mail
    summary = find_contacts(conn, app, prefs, d)
    assert {p["email"] for p in people(conn, app)} == {""} and Hunter.calls == 0
    assert summary["people"] == 3


def test_domain_learned_from_apify_emails_is_remembered(prefs):
    class Apify:
        SEARCH_PAGE_USD, PROFILE_EMAIL_USD = 0.10, 0.01

        def search_people(self, company, words, location):
            return []

        def profile_email(self, url):
            return {"https://www.linkedin.com/in/asharao": "asha.rao@zeptobank.com"}.get(url)

    conn, app = setup_app()
    d, _ = deps(llm=llm_for(domain_index=-1), apify=Apify())
    d.resolver = lambda domain: "mx.zeptobank.com" if domain == "zeptobank.com" else None
    find_contacts(conn, app, prefs, d)
    row = get_domain(conn, "zepto")
    assert (row["domain"], row["pattern"], row["mx_host"]) == ("zeptobank.com", "first.last", "mx.zeptobank.com")
    ps = people(conn, app)
    assert ps[0]["email"] == "asha.rao@zeptobank.com" and ps[0]["email_status"] == "verified"
    assert ps[1]["email"] == "vikram.singh@zeptobank.com" and ps[1]["email_source"] == "pattern"


def test_guesses_follow_pattern_of_verified_addresses(prefs):
    class Apify:
        SEARCH_PAGE_USD, PROFILE_EMAIL_USD = 0.10, 0.01

        def search_people(self, company, words, location):
            return []

        def profile_email(self, url):
            return {"https://www.linkedin.com/in/vsingh": "vikram@zeptonow.com"}.get(url)

    conn, app = setup_app()
    d, _ = deps(FakeSMTP(default=250), apify=Apify())  # catch-all: SMTP can't verify; public hint says first.last
    find_contacts(conn, app, prefs, d)
    ps = {p["name"]: p for p in people(conn, app)}
    assert ps["Vikram Singh"]["email"] == "vikram@zeptonow.com" and ps["Vikram Singh"]["email_status"] == "verified"
    assert ps["Asha Rao"]["email"] == "asha@zeptonow.com"  # follows the verified 'first' pattern, not the hint
    assert get_domain(conn, "zepto")["pattern"] == "first"
