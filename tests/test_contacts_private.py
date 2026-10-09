from jobseeker.db.applications import BlockedContact, ensure_application, mark_not_interested, save_contact
from jobseeker.db.contacts_repo import blocked_profile_urls, edit_contact, link_contact, people, upsert_contact
from jobseeker.db.core import connect


def _two_apps_same_person(settings, seeded_two):
    conn = connect(settings.db_path)
    a1, a2 = seeded_two["owner_apps"][0], seeded_two["roommate_app"]
    company = conn.execute("SELECT j.company FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = ?",
                           (a1,)).fetchone()[0]
    cid = upsert_contact(conn, 1, company, "Hira Manager", "PM", "https://li/hm", "hm@acme.com", "verified")
    link_contact(conn, a1, 1, cid, "Hiring manager", "r", "smtp")
    link_contact(conn, a2, 1, upsert_contact(conn, 2, company, "Hira Manager", "PM", "https://li/hm", "hm@acme.com",
                                             "verified"), "Hiring manager", "r", "smtp")
    return conn, a1, a2, cid


def test_email_edit_is_copy_on_write(settings, seeded_two):
    conn, a1, a2, shared = _two_apps_same_person(settings, seeded_two)
    new = edit_contact(conn, 2, a2, 1, "Hira Manager", "attacker@evil.com", "verified")
    assert new != shared
    assert people(conn, a1)[0]["email"] == "hm@acme.com"           # the owner still drafts to the real address
    assert people(conn, a2)[0]["email"] == "attacker@evil.com"
    assert conn.execute("SELECT owner_user_id FROM contacts WHERE id = ?", (new,)).fetchone()[0] == 2
    again = edit_contact(conn, 2, a2, 1, "Hira M.", "attacker@evil.com", "verified")
    assert again == new                                               # own private row: edited in place


def test_bounce_only_edit_updates_the_shared_row(settings, seeded_two):
    conn, a1, a2, shared = _two_apps_same_person(settings, seeded_two)
    assert edit_contact(conn, 2, a2, 1, "Hira Manager", "hm@acme.com", "bounced") == shared
    assert people(conn, a1)[0]["email_status"] == "bounced"           # a bounce protects everyone


def test_private_rows_are_never_adopted(settings, seeded_two):
    conn, a1, a2, shared = _two_apps_same_person(settings, seeded_two)
    company = conn.execute("SELECT company FROM contacts WHERE id = ?", (shared,)).fetchone()[0]
    private = save_contact(conn, a2, name="Own Pick", role="VP", linkedin_url="https://li/own", email="own@acme.com",
                           email_status="unverified")
    assert conn.execute("SELECT owner_user_id FROM contacts WHERE id = ?", (private,)).fetchone()[0] == 2
    assert upsert_contact(conn, 1, company, "Own Pick", "VP", "https://li/own", "own@acme.com", "unverified") != private
    assert save_contact(conn, a1, name="Own Pick", role="VP", linkedin_url="https://li/own", email="own@acme.com",
                        email_status="unverified") != private


def test_not_interested_is_private(settings, seeded_two):
    conn, a1, a2, shared = _two_apps_same_person(settings, seeded_two)
    company = conn.execute("SELECT company FROM contacts WHERE id = ?", (shared,)).fetchone()[0]
    mark_not_interested(conn, a2, block_company=True)
    assert blocked_profile_urls(conn, 2, company) == {"https://li/hm"}
    assert blocked_profile_urls(conn, 1, company) == set()
    assert upsert_contact(conn, 1, company, "Hira Manager", "PM", "https://li/hm", "hm@acme.com", "verified") == shared
    assert upsert_contact(conn, 2, company, "Hira Manager", "PM", "https://li/hm", "hm@acme.com", "verified") is None


def test_edit_route_uses_copy_on_write(settings, seeded_two, client_as):
    from jobseeker.db.users import set_outreach
    conn, a1, a2, shared = _two_apps_same_person(settings, seeded_two)
    set_outreach(conn, 2, True)
    r = client_as(2, follow_redirects=False).post(f"/applications/{a2}/contacts/1/edit",
                                                  data={"name": "Hira Manager", "email": "x@evil.com",
                                                        "email_status": "verified"})
    assert r.status_code == 303 and people(conn, a1)[0]["email"] == "hm@acme.com"


def test_i1_replay_roommate_edit_leaves_owner_row_untouched(settings, seeded_two, client_as):
    """Plan 2's I1: a roommate (outreach on) edits a contact that the owner's application also links to."""
    from jobseeker.db.users import set_outreach
    conn, a1, a2, shared = _two_apps_same_person(settings, seeded_two)
    assert people(conn, a2)[0]["contact_id"] == shared               # both applications link the same shared row
    before = dict(conn.execute("SELECT * FROM contacts WHERE id = ?", (shared,)).fetchone())
    set_outreach(conn, 2, True)
    r = client_as(2, follow_redirects=False).post(f"/applications/{a2}/contacts/1/edit",
                                                  data={"name": "Someone Else", "email": "me@attacker.com",
                                                        "email_status": "verified"})
    assert r.status_code == 303
    assert dict(conn.execute("SELECT * FROM contacts WHERE id = ?", (shared,)).fetchone()) == before
    assert people(conn, a1)[0]["contact_id"] == shared and people(conn, a1)[0]["email"] == "hm@acme.com"
    mine = people(conn, a2)[0]
    assert mine["contact_id"] != shared and mine["email"] == "me@attacker.com"
    assert conn.execute("SELECT owner_user_id FROM contacts WHERE id = ?", (mine["contact_id"],)).fetchone()[0] == 2


def _zepto_apps(settings):
    """One Zepto job, an application for the owner and one for user 2 (outreach on), both onboarded."""
    from datetime import UTC, datetime

    from jobseeker.config import UserPrefs
    from jobseeker.db.jobs import upsert_job
    from jobseeker.db.users import set_outreach
    from tests.factories import make_job
    conn = connect(settings.db_path)
    conn.execute("INSERT OR IGNORE INTO users (id, email, name, created_at) VALUES (2, 'b@example.com', 'B', 't')")
    conn.execute("""INSERT OR IGNORE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (2, ?, 1, NULL, 't', 't')""",
                 (UserPrefs(roles=["Growth Analyst"], cities=["Pune"], experience_summary="x").model_dump_json(),))
    set_outreach(conn, 2, True)
    job, _ = upsert_job(conn, make_job(company="Zepto", title="Associate Product Manager",
                                       jd_text="Own the funnel. 1-2 years of experience."))
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    return conn, ensure_application(conn, 1, job, now), ensure_application(conn, 2, job, now)


def test_review_1_replay_domain_override_and_find_never_rewrite_the_owners_contact(settings, prefs, client_as):
    """Final review #1: B sets the company's email domain to one they control and runs Find contacts."""
    from tests.test_contacts_finder import FakeSMTP, deps
    from jobseeker.contacts.finder import find_contacts
    conn, a1, a2 = _zepto_apps(settings)
    prefs.contacts.smtp_verify = "on"
    find_contacts(conn, a1, prefs, deps(FakeSMTP({"asha.rao@zeptonow.com": 250}))[0])
    owner = people(conn, a1)[0]
    assert (owner["email"], owner["email_status"]) == ("asha.rao@zeptonow.com", "verified")
    domains_before = [dict(r) for r in conn.execute("SELECT * FROM company_domains")]
    r = client_as(2, follow_redirects=False).post(f"/applications/{a2}/contacts/domain", data={"domain": "evil.com"})
    assert r.status_code == 303
    assert [dict(r) for r in conn.execute("SELECT * FROM company_domains")] == domains_before  # per-user override
    find_contacts(conn, a2, prefs, deps(FakeSMTP({"asha.rao@evil.com": 250}, default=550))[0])
    assert people(conn, a1)[0] == owner                                 # A's People and Approve are untouched
    mine = people(conn, a2)[0]
    assert mine["email"] == "asha.rao@evil.com" and mine["contact_id"] != owner["contact_id"]
    assert conn.execute("SELECT owner_user_id FROM contacts WHERE id = ?", (mine["contact_id"],)).fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM user_company_domains WHERE user_id = 2").fetchone()[0] == 1


def test_finder_never_rewrites_a_shared_row_another_user_links(settings, seeded_two):
    conn, a1, a2, shared = _two_apps_same_person(settings, seeded_two)
    company = conn.execute("SELECT company FROM contacts WHERE id = ?", (shared,)).fetchone()[0]
    cid = upsert_contact(conn, 2, company, "Hira Manager", "PM", "https://li/hm", "x@other.com", "verified",
                         domain="other.com")
    assert cid != shared and people(conn, a1)[0]["email"] == "hm@acme.com"
    assert conn.execute("SELECT owner_user_id FROM contacts WHERE id = ?", (cid,)).fetchone()[0] == 2
    again = upsert_contact(conn, 2, company, "Hira Manager", "PM", "https://li/hm", "x@other.com", "verified",
                           domain="other.com")
    assert again == cid                                                 # reruns reuse the finder's private copy


def test_finder_never_replaces_a_verified_email_with_one_on_another_domain(settings, seeded_two):
    conn, a1, _, shared = _two_apps_same_person(settings, seeded_two)
    company = conn.execute("SELECT company FROM contacts WHERE id = ?", (shared,)).fetchone()[0]
    conn.execute("DELETE FROM application_contacts WHERE contact_id = ? AND application_id != ?", (shared, a1))
    conn.commit()  # only the acting user links it now
    cid = upsert_contact(conn, 1, company, "Hira Manager", "PM", "https://li/hm", "hira@new.com", "unverified",
                         domain="new.com")
    assert tuple(conn.execute("SELECT email, email_status FROM contacts WHERE id = ?", (shared,)).fetchone()) == (
        "hm@acme.com", "verified")
    assert cid != shared  # the acting user still gets the address their run found


def test_review_4_replay_block_on_a_private_copy_stops_relinking(settings, seeded_two):
    """Final review #4: edit (private copy), Not interested, then Remove pulls the same person back."""
    conn, a1, _, shared = _two_apps_same_person(settings, seeded_two)
    company = conn.execute("SELECT company FROM contacts WHERE id = ?", (shared,)).fetchone()[0]
    private = edit_contact(conn, 1, a1, 1, "Hira Manager", "hira@acme.com", "unverified")
    assert private != shared
    mark_not_interested(conn, a1, block_company=False)
    assert upsert_contact(conn, 1, company, "Hira Manager", "PM", "https://li/hm", "hm@acme.com", "verified") is None
