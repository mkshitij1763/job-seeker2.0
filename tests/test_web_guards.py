from fastapi.routing import APIRoute, iter_route_contexts

from jobseeker.web.app import PUBLIC, create_app
from jobseeker.web.deps import current_user, optional_user, owned_app, require_admin


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
        if r.path.startswith("/admin"):
            assert require_admin in calls, f"{r.path} has no require_admin"
        if "{app_id}" in r.path:
            assert owned_app in calls, f"{r.path} has no owned_app"


def test_anonymous_requests_are_sent_to_login(settings, seeded, anon_client):
    web, app_id = anon_client(), seeded[0]
    root = web.get("/")
    assert root.status_code == 303 and root.headers["location"] == "/login" and "Senior Product" not in root.text
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
