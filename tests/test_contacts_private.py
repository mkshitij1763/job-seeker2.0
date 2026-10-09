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
