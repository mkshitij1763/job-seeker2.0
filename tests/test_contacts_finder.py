from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.contacts.finder import Deps, FinderError, find_contacts
from jobseeker.contacts.people import Candidate
from jobseeker.contacts.smtp_verify import PortBlocked
from jobseeker.db.applications import ensure_application, get_application
from jobseeker.db.contacts_repo import STALE_AFTER, claim_find, find_state, get_domain, people, set_find_status
from jobseeker.db.core import connect
from jobseeker.db.jobs import upsert_job
from tests.factories import make_job
from tests.fakes import FakeLLM

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _smtp_checks_on(prefs):
    """These tests cover SMTP verification itself; the server default (off) is covered in test_smtp_switch.py."""
    prefs.contacts.smtp_verify = "on"
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
    return conn, ensure_application(conn, 1, job_id, NOW)


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
    assert any("Email checks aren't available on this server" in n for n in summary["notes"])
    assert {p["email_status"] for p in people(conn, app)} == {"unverified"}


def test_blocked_people_are_excluded(prefs):
    conn, app = setup_app()
    d, _ = deps(FakeSMTP(default=250))
    find_contacts(conn, app, prefs, d)
    for p in people(conn, app):  # all three said not interested (Task 8 makes Not interested do this)
        conn.execute("INSERT INTO blocklist (user_id, contact_id, company, reason, at) VALUES (1, ?, '', 'not interested', ?)",
                     (p["contact_id"], NOW.isoformat()))
    conn.commit()
    job2, _ = upsert_job(conn, make_job(company="Zepto", title="Product Manager", source_job_id="z2", fingerprint="z2"))
    app2 = ensure_application(conn, 1, job2, NOW)
    d2, _ = deps(FakeSMTP(default=250), llm=llm_for({"picks": [{"index": 0, "label": "peer", "reason": "r"}]}))
    with pytest.raises(FinderError):
        find_contacts(conn, app2, prefs, d2)  # every Zepto person found is blocked -> nobody left


def test_blocked_contact_without_linkedin_url_is_excluded_by_name(prefs):
    conn, app = setup_app()
    cid = conn.execute("""INSERT INTO contacts (company, name, role, linkedin_url, email, email_status, source)
                          VALUES ('Zepto', 'Dr. Asha Rao', '', '', 'asha@zeptonow.com', 'unverified', 'manual')""").lastrowid
    conn.execute("INSERT INTO blocklist (user_id, contact_id, company, reason, at) VALUES (1, ?, '', 'not interested', ?)",
                 (cid, NOW.isoformat()))
    conn.commit()
    d, _ = deps(FakeSMTP(default=250))
    find_contacts(conn, app, prefs, d)
    assert "Asha Rao" not in [p["name"] for p in people(conn, app)]


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
    with pytest.raises(FinderError, match="Your Tavily share is used for October"):
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
                 ((NOW - STALE_AFTER - timedelta(minutes=1)).isoformat(timespec="seconds"), app))
    conn.commit()
    state = find_state(conn, app, NOW)
    assert state["status"] == "failed" and "timed out" in state["note"]


def test_stale_after_outlasts_worst_case_apify_run():
    # one Apify people search + three profile-email lookups, each up to the 180 s client timeout
    assert STALE_AFTER > timedelta(seconds=4 * 180)


def test_claim_find_is_exclusive_until_stale():
    conn, app = setup_app()
    assert claim_find(conn, app, NOW) is True
    assert claim_find(conn, app, NOW) is False  # a second click while running doesn't start another job
    assert claim_find(conn, app, NOW + STALE_AFTER + timedelta(minutes=1)) is True  # a dead job can be retried
    set_find_status(conn, app, "done")
    assert claim_find(conn, app, NOW) is True


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


# ---- final-review fixes ----

class _ApifyEmails:
    SEARCH_PAGE_USD, PROFILE_EMAIL_USD = 0.10, 0.01

    def __init__(self, emails=None, fail=False):
        self.emails, self.fail = emails or {}, fail

    def search_people(self, company, words, location):
        return []

    def profile_email(self, url):
        if self.fail:
            import httpx
            raise httpx.ReadTimeout("apify timed out")
        return self.emails.get(url)


def test_personal_email_from_apify_never_becomes_company_domain(prefs):
    conn, app = setup_app()
    d, _ = deps(llm=llm_for(domain_index=-1), apify=_ApifyEmails({"https://www.linkedin.com/in/asharao": "asha.rao@gmail.com"}))
    d.resolver = lambda domain: "mx.google.com"
    find_contacts(conn, app, prefs, d)
    assert get_domain(conn, "zepto") is None or get_domain(conn, "zepto")["domain"] != "gmail.com"
    assert all("gmail.com" not in p["email"] for p in people(conn, app))


def test_colliding_guesses_never_share_an_email(prefs):
    team = [{"title": "Rahul Sharma - PM @ Zepto", "url": "https://in.linkedin.com/in/rsharma", "content": ""},
            {"title": "Rahul Verma - PM @ Zepto", "url": "https://in.linkedin.com/in/rverma", "content": ""}]

    class T(FakeTavily):
        def search(self, query, include_domains=None, max_results=10):
            if query.startswith('"@'):
                return []
            if "official website" in query:
                return SITE
            return [] if "talent acquisition" in query else team
    conn, app = setup_app()
    from jobseeker.db.contacts_repo import save_domain
    save_domain(conn, "zepto", domain="zeptonow.com", pattern="first", catch_all=1, mx_host="mx")
    picks = {"picks": [{"index": 0, "label": "hiring_manager", "reason": "a"}, {"index": 1, "label": "peer", "reason": "b"}]}
    d, _ = deps(llm=llm_for(picks), tavily=T())
    find_contacts(conn, app, prefs, d)
    ps = people(conn, app)
    assert [p["name"] for p in ps] == ["Rahul Sharma", "Rahul Verma"]
    assert ps[0]["contact_id"] != ps[1]["contact_id"] and ps[0]["email"] != ps[1]["email"]


def _cached_refusal(conn, age):
    from jobseeker.db.contacts_repo import save_domain
    save_domain(conn, "zepto", domain="zeptonow.com", pattern="first.last", catch_all=2, mx_host="mx")
    conn.execute("UPDATE company_domains SET catch_all_at = ?, checked_at = ? WHERE name_norm = 'zepto'",
                 ((NOW - age).isoformat(timespec="seconds"),) * 2)
    conn.commit()


def test_remembered_refusal_skips_checks_while_fresh(prefs):
    conn, app = setup_app()
    _cached_refusal(conn, timedelta(days=5))
    d, server = deps(FakeSMTP({"asha.rao@zeptonow.com": 250}))
    find_contacts(conn, app, prefs, d)
    assert server.rcpts == [] and get_domain(conn, "zepto")["catch_all"] == 2


def test_remembered_refusal_expires_after_30_days(prefs):
    conn, app = setup_app()
    _cached_refusal(conn, timedelta(days=31))
    d, server = deps(FakeSMTP({"asha.rao@zeptonow.com": 250}))
    find_contacts(conn, app, prefs, d)
    assert server.rcpts  # checked again: refusals depend on the network we were on
    row = get_domain(conn, "zepto")
    assert row["catch_all"] == 0 and row["catch_all_at"] > (NOW - timedelta(days=1)).isoformat()
    assert people(conn, app)[0]["email_status"] == "verified"


def test_pre_migration_refusal_keeps_its_age_when_saved_again():
    from jobseeker.db.contacts_repo import save_domain
    conn, _ = setup_app()
    _cached_refusal(conn, timedelta(days=31))
    conn.execute("UPDATE company_domains SET catch_all_at = NULL")
    save_domain(conn, "zepto", pattern="first")  # e.g. a pattern learned later must not make the refusal look new
    assert get_domain(conn, "zepto")["catch_all_at"] == (NOW - timedelta(days=31)).isoformat(timespec="seconds")


def test_rerun_refused_once_people_were_emailed(prefs):
    conn, app = setup_app()
    find_contacts(conn, app, prefs, deps(FakeSMTP(default=250))[0])
    conn.execute("UPDATE application_contacts SET emailed_at = '2026-10-08T10:00:00+00:00' WHERE application_id = ? AND rank = 1", (app,))
    conn.commit()
    with pytest.raises(FinderError, match="already emailed"):
        find_contacts(conn, app, prefs, deps(FakeSMTP(default=250))[0])


def test_rerun_with_fewer_people_removes_stale_ranks(prefs):
    conn, app = setup_app()
    find_contacts(conn, app, prefs, deps(FakeSMTP(default=250))[0])
    one = {"picks": [{"index": 0, "label": "hiring_manager", "reason": "a"}]}
    find_contacts(conn, app, prefs, deps(FakeSMTP(default=250), llm=llm_for(one))[0])
    assert [p["rank"] for p in people(conn, app)] == [1]


def test_rerun_keeps_verified_and_bounced_marks(prefs):
    conn, app = setup_app()
    find_contacts(conn, app, prefs, deps(FakeSMTP(default=250))[0])  # catch-all: likely first.last guesses
    ps = people(conn, app)
    conn.execute("UPDATE contacts SET email_status = 'bounced' WHERE id = ?", (ps[0]["contact_id"],))
    conn.execute("UPDATE contacts SET email = 'vikram@zeptonow.com', email_status = 'verified' WHERE id = ?", (ps[1]["contact_id"],))
    conn.commit()
    find_contacts(conn, app, prefs, deps(FakeSMTP(default=250))[0])
    ps = people(conn, app)
    assert ps[0]["email"] != "asha.rao@zeptonow.com"  # never re-offer a bounced guess
    assert (ps[1]["email"], ps[1]["email_status"]) == ("vikram@zeptonow.com", "verified")


def test_fallback_errors_keep_verified_results(prefs):
    conn, app = setup_app()
    smtp = FakeSMTP({"asha.rao@zeptonow.com": 250})
    d, _ = deps(smtp, apify=_ApifyEmails(fail=True))
    summary = find_contacts(conn, app, prefs, d)
    ps = people(conn, app)
    assert ps[0]["email_status"] == "verified" and any("Apify" in n for n in summary["notes"])


def test_changing_the_domain_replaces_verified_addresses_on_the_old_domain(prefs):
    from jobseeker.db.contacts_repo import save_domain

    conn, app = setup_app()
    find_contacts(conn, app, prefs, deps(FakeSMTP(default=250))[0])
    ps = people(conn, app)
    conn.execute("UPDATE contacts SET email = 'asha@oldname.com', email_status = 'verified' WHERE id = ?", (ps[0]["contact_id"],))
    conn.commit()
    save_domain(conn, "zepto", domain="zeptonow.com", pattern="first.last", catch_all=1, mx_host="mx")  # user set it
    find_contacts(conn, app, prefs, deps(FakeSMTP(default=250))[0])
    p = people(conn, app)[0]
    assert p["email"] == "asha.rao@zeptonow.com" and p["email_status"] == "unverified"


def _second_user_app(conn, app1):
    from jobseeker.db.users import set_outreach
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    set_outreach(conn, 2, True)
    return ensure_application(conn, 2, get_application(conn, app1)["job_id"], NOW)


def test_second_user_same_company_reuses_search_and_spends_no_tavily(prefs):
    from jobseeker.db.usage import Budget, outreach_limits
    conn, app1 = setup_app()
    app2 = _second_user_app(conn, app1)
    tavily = FakeTavily()
    d, _ = deps(FakeSMTP(default=250), tavily=tavily)
    find_contacts(conn, app1, prefs, d)
    asked = len(tavily.queries)
    find_contacts(conn, app2, prefs, d)
    assert len(tavily.queries) == asked                                   # every search came from people_searches
    assert Budget(conn, 2, outreach_limits(conn, prefs.contacts, 20), NOW).used("tavily") == 0
    mine = {p["contact_id"] for p in people(conn, app2)}
    assert mine and conn.execute("SELECT COUNT(*) FROM application_contacts WHERE application_id = ?",
                                 (app2,)).fetchone()[0] == len(mine)       # the roommate's own links


def test_person_blocked_by_b_is_still_found_for_a(prefs):
    from jobseeker.db.applications import mark_not_interested
    conn, app1 = setup_app()
    app2 = _second_user_app(conn, app1)
    d, _ = deps(FakeSMTP(default=250))
    find_contacts(conn, app2, prefs, d)
    mark_not_interested(conn, app2, block_company=True)                   # B blocks the people and the company
    find_contacts(conn, app1, prefs, d)                                    # A, served from the cache
    assert "Asha Rao" in [p["name"] for p in people(conn, app1)]


def _draft_share_used(conn, prefs):
    from jobseeker.db.usage import Budget, outreach_limits
    b = Budget(conn, 1, outreach_limits(conn, prefs.contacts, 20), NOW)
    b.spend("draft", b.limits["draft"].share_cap)


def test_ranking_needs_a_draft_unit(prefs):
    conn, app = setup_app()
    _draft_share_used(conn, prefs)

    def no_llm(schema, prompt):
        raise AssertionError("the ranking LLM must not be called")
    d, _ = deps(llm=FakeLLM(handler=no_llm))
    with pytest.raises(FinderError, match="Your drafting share is used for today"):
        find_contacts(conn, app, prefs, d)


def test_ranking_and_domain_pick_each_spend_a_draft_unit(prefs):
    from jobseeker.db.usage import Budget, outreach_limits
    conn, app = setup_app()
    find_contacts(conn, app, prefs, deps()[0])                             # ranks people, then picks the website
    assert Budget(conn, 1, outreach_limits(conn, prefs.contacts, 20), NOW).used("draft") == 2


def test_review_11_an_empty_search_is_not_cached(prefs):
    from jobseeker.contacts.finder import _search
    from jobseeker.db.usage import Budget, outreach_limits

    class Empty(FakeTavily):
        def search(self, query, include_domains=None, max_results=10):
            self.queries.append(query)
            return []
    conn, _ = setup_app()
    d, _ = deps(tavily=Empty())
    budget = Budget(conn, 1, outreach_limits(conn, prefs.contacts, 20), NOW)
    assert _search(d, conn, "Zepto", budget, [], "q") == []
    assert _search(d, conn, "Zepto", budget, [], "q") == []
    assert d.tavily.queries == ["q", "q"]                             # asked again: nothing was cached
    assert conn.execute("SELECT COUNT(*) FROM people_searches").fetchone()[0] == 0
