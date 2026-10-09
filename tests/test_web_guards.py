from fastapi.routing import APIRoute, iter_route_contexts

from jobseeker.web.app import PUBLIC, create_app
from jobseeker.web.deps import current_user, optional_user, owned_app, require_admin, require_onboarded


def _api_routes(app):
    """Every API route with its effective path and dependencies. FastAPI 0.142 keeps included routers as
    _IncludedRouter entries in app.routes, so a plain isinstance(r, APIRoute) walk sees none of them."""
    routes = [r for r in iter_route_contexts(app.routes) if isinstance(r.original_route, APIRoute)]
    assert len(routes) > 20, "route walk found too few routes; the guard tests would pass vacuously"
    return routes


def _calls(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _calls(d)


def test_every_route_is_guarded(settings):
    for r in _api_routes(create_app(settings)):
        if r.path in PUBLIC:
            continue
        calls = set(_calls(r.dependant))
        if r.path == "/":
            assert optional_user in calls
            continue
        assert current_user in calls, f"{r.path} has no current_user"
        if r.path.startswith("/onboarding"):
            assert require_onboarded not in calls, f"{r.path} must not require onboarding"
        elif not r.path.startswith(("/logout", "/settings/delete", "/settings/export", "/push/")):
            assert require_onboarded in calls, f"{r.path} has no require_onboarded"
        if r.path.startswith("/admin"):
            assert require_admin in calls, f"{r.path} has no require_admin"
        if "{app_id}" in r.path:
            assert owned_app in calls, f"{r.path} has no owned_app"


def test_anonymous_requests_are_sent_to_login(settings, seeded, anon_client):
    web, app_id = anon_client(), seeded[0]
    root = web.get("/")
    assert root.status_code == 200 and 'class="landing' in root.text and "Senior Product" not in root.text
    for r in _api_routes(create_app(settings)):
        if r.path in PUBLIC or r.path == "/":
            continue
        path = (r.path.replace("{app_id}", str(app_id)).replace("{kind}", "email").replace("{rank}", "1")
                .replace("{user_id}", "2").replace("{email}", "x@example.com"))
        for method in r.methods - {"HEAD"}:
            resp = web.request(method, path)
            assert resp.status_code == 303 and resp.headers["location"].startswith("/login"), (method, path)
            hx = web.request(method, path, headers={"HX-Request": "true"})
            assert hx.status_code == 401 and hx.headers["HX-Redirect"].startswith("/login"), (method, path)


def test_roommate_gets_404_on_owner_application(seeded_two, client_as, settings):
    web, a = client_as(2, follow_redirects=False), seeded_two["owner_apps"][0]
    for r in _api_routes(create_app(settings)):
        if "{app_id}" in r.path:
            path = r.path.replace("{app_id}", str(a)).replace("{kind}", "email").replace("{rank}", "1")
            for method in r.methods - {"HEAD"}:
                assert web.request(method, path).status_code == 404, (method, path)


def test_owner_still_sees_everything(seeded, client_as):
    web = client_as(1)
    assert web.get("/").status_code == 200
    assert web.get(f"/applications/{seeded[0]}").status_code == 200


# Outreach (contacts, drafts, Gmail) is a per-user switch: users.outreach_enabled, else every route is a 404.
OUTREACH = {("POST", "/applications/{app_id}/contact"), ("POST", "/applications/{app_id}/drafts/{kind}"),
            ("POST", "/applications/{app_id}/draft"), ("POST", "/applications/{app_id}/approve"),
            ("POST", "/applications/{app_id}/followed-up")}


def _outreach(r):
    return any((m, r.path) in OUTREACH for m in r.methods) or "/contacts/" in r.path or r.path.startswith("/gmail")


def test_outreach_routes_require_outreach(settings):
    from jobseeker.web.deps import require_outreach
    gated = [r for r in _api_routes(create_app(settings)) if _outreach(r)]
    assert len(gated) >= 12
    for r in gated:
        assert require_outreach in set(_calls(r.dependant)), f"{r.path} has no require_outreach"


def test_roommate_gets_404_on_outreach_routes_of_their_own_application(seeded_two, client_as, settings):
    web, a = client_as(2, follow_redirects=False), seeded_two["roommate_app"]
    assert web.get(f"/applications/{a}").status_code == 200  # their own application is still theirs
    for r in _api_routes(create_app(settings)):
        if _outreach(r):
            path = r.path.replace("{app_id}", str(a)).replace("{kind}", "email").replace("{rank}", "1")
            for method in r.methods - {"HEAD"}:
                assert web.request(method, path).status_code == 404, (method, path)


def test_outreach_on_for_roommate_opens_the_routes(seeded_two, client_as, settings):
    from jobseeker.db.core import connect
    from jobseeker.db.users import set_outreach
    set_outreach(connect(settings.db_path), 2, True)
    web, a = client_as(2, follow_redirects=False), seeded_two["roommate_app"]
    assert web.get(f"/applications/{a}/contacts/card").status_code == 200
    html = web.get(f"/applications/{a}").text
    assert 'data-tab="people"' in html and "Open job posting" not in html


def test_outreach_off_keeps_drafts_and_hides_them(seeded, client_as, settings):
    from jobseeker.db.applications import save_draft
    from jobseeker.db.core import connect
    from jobseeker.db.users import set_outreach
    conn = connect(settings.db_path)
    save_draft(conn, seeded[0], "email", "Subj", "Body kept")
    conn.execute("INSERT INTO users (id, email, is_admin, created_at) VALUES (5, 'admin2@example.com', 1, 't')")
    set_outreach(conn, 1, False)
    web = client_as(1, follow_redirects=False)
    assert web.post(f"/applications/{seeded[0]}/approve").status_code == 404
    assert web.get(f"/applications/{seeded[0]}").status_code == 200
    assert conn.execute("SELECT body FROM drafts WHERE application_id = ?", (seeded[0],)).fetchone()[0] == "Body kept"
    set_outreach(conn, 1, True)
    assert "Body kept" in client_as(1).get(f"/applications/{seeded[0]}").text


OUTREACH_MARKUP = ("/contacts/", "/approve", "/draft", "/contact\"", "/followed-up", "Find contacts", "Gmail",
                   'data-tab="people"', 'data-tab="draft"', 'value="sent"')


def test_roommate_job_page_has_no_outreach_markup_and_can_mark_applied(seeded_two, client_as, settings):
    from jobseeker.db.applications import get_status
    from jobseeker.db.core import connect
    web, a = client_as(2, follow_redirects=False), seeded_two["roommate_app"]
    html = web.get(f"/applications/{a}").text
    for bit in OUTREACH_MARKUP:
        assert bit not in html, bit
    assert "Open job posting" in html and 'name="status" value="applied_via_portal"' in html and "Mark applied" in html
    assert web.post(f"/applications/{a}/status", data={"status": "applied_via_portal"}).status_code == 303
    assert get_status(connect(settings.db_path), a) == "applied_via_portal"


def test_owner_job_page_keeps_outreach(seeded, client_as):
    html = client_as(1).get(f"/applications/{seeded[0]}").text
    assert "/approve" in html and 'data-tab="people"' in html and "Find contacts" in html


def test_roommate_today_has_no_outreach_tiles(seeded_two, client_as):
    html = client_as(2).get("/today").text
    for bit in ("Send in Gmail", "Ready to approve", "Need contacts", "Find contacts", "Follow-ups due", 'value="sent"'):
        assert bit not in html, bit
    assert "Apply on the company site" in html and f"/applications/{seeded_two['roommate_app']}" in html


def test_owner_today_keeps_outreach_tiles(seeded, client_as):
    html = client_as(1).get("/today").text
    assert "Send in Gmail" in html and "Need contacts" in html and "Apply on the company site" not in html
