# Proposal: sub-project 2, accounts, auth and data scoping (draft, pre-spec)

**Date:** 2026-10-08 · **Branch:** `multi-user` · **Builds on:** `2026-10-08-multi-user-impact.md`. Since that audit the job count has grown from 3,948 to 4,497.
**Rulings applied:**
- Q1: company domain, MX, catch-all and people/email lookups are a shared cache. Outreach state is per-user.
- Q3: Groq gets a per-user daily cap of an equal share, plus the global cap. Unused shares aren't pooled. Users run round-robin.
- Q2 is assumed: matching first, with outreach built so it can be switched on per user later.

**Scope:** identity, invites, sessions, CSRF, route guards, the migration framework, and migration v1, which scopes every table. The per-user pipeline (sub-project 4) and per-user Gmail (sub-project 5) only consume what this sets up. Until sub-project 4 lands, the CLI pipeline passes the owner's `user_id=1`.

---

## (a) Google sign-in: hand-rolled code flow (recommended) vs Authlib

| | Authlib (`starlette_client`) | Hand-rolled code flow |
|---|---|---|
| New dependencies | `authlib`, plus `itsdangerous` for Starlette's `SessionMiddleware`, where Authlib keeps state and nonce | **none**: `httpx` and `google-auth` (`google.oauth2.id_token.verify_oauth2_token`) are already installed |
| Crypto-sensitive part (JWT signature, `aud`/`iss`/`exp`) | Authlib | `google-auth`, the same library the Gmail client already trusts |
| Sessions | signed cookie with all state client-side; no server-side revoke unless we add one | DB rows: logout and an admin "kick" actually revoke the session |
| Code we still write | users, invites, sessions, guards | the same, plus about 60 lines: `/login`, `/auth/callback`, state/nonce/PKCE |
| Risk | low; a mature library | getting state, nonce and PKCE right. Mitigated by unit tests on each check (state mismatch, nonce mismatch, `email_verified` false, wrong `aud`) |

**Recommendation: hand-rolled**, with JWT verification delegated to `google-auth`. Authlib would save about 60 lines but adds two dependencies and a second, cookie-only session system next to the DB sessions we want anyway.

**Flow** (`src/jobseeker/web/auth.py`, new):
1. `GET /login` creates `state`, `nonce` and a PKCE `verifier`. It stores them in a 10-minute, HMAC-signed cookie `__Host-js_oauth` (stdlib `hmac` with `SECRET_KEY`; HttpOnly, Secure, SameSite=Lax; Lax is needed because the callback is a top-level GET from accounts.google.com). Then it redirects to Google with `scope=openid email profile`, `response_type=code`, `code_challenge` (S256), `state`, `nonce` and `prompt=select_account`.
2. `GET /auth/callback`:
   - check `state` against the cookie;
   - POST the code and the verifier to `https://oauth2.googleapis.com/token` with `httpx`;
   - verify the ID token with `verify_oauth2_token(tok, Request(), GOOGLE_CLIENT_ID)`;
   - check that `nonce` matches and that `email_verified` is true;
   - resolve the user (b), create a session (c), delete the oauth cookie;
   - redirect to `/onboarding` if there is no profile yet, otherwise to `/`.
3. **Identity only.** Sign-in never requests `gmail.compose`. Sub-project 5 adds a separate "Connect Gmail" consent: same Google *Web* client, its own redirect URI, `access_type=offline`, `include_granted_scopes=true`, `login_hint=<email>`. Signing in therefore never stalls on the weekly Testing-mode Gmail re-consent.
4. Config (`Settings`, `src/jobseeker/config.py:11`): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `BASE_URL` (exact origin, used for `redirect_uri` and the CSRF check), `SECRET_KEY` (32+ random bytes), `OWNER_EMAIL`, `COOKIE_SECURE=true` (tests set `https://testserver` instead of turning it off).

## (b) Invite allow-list and the owner/admin role

- `users(id, google_sub UNIQUE NULL, email UNIQUE NOT NULL, name, is_admin INT NOT NULL DEFAULT 0, disabled_at, created_at, last_login_at)`.
- `invites(email PRIMARY KEY, invited_by REFERENCES users(id), created_at, accepted_at)`. Emails are stored lower-cased.
- **Owner bootstrap:** migration v1 creates `users(id=1, email=OWNER_EMAIL, is_admin=1, google_sub=NULL)`, and all migrated data belongs to that user.
- **Resolving a sign-in:**
  1. Find the user by `google_sub`.
  2. If there is none, match on email for a user with no `google_sub` yet (the owner's first login), then set `google_sub`.
  3. If that fails too, look for an `invites` row for the email: create the user and set `accepted_at`.
  4. Otherwise show a 403 page: "This app is invite-only. Ask Kshitij for an invite." No user row is created for uninvited people.
- Matching on `sub` after the first login means a changed Gmail address can't take over an account. `email_verified` must be true.
- **Admin:** `require_admin = Depends(current_user)` plus an `is_admin` check (else 404, so the admin area isn't advertised). The admin routes are `/admin` (users, invites, usage per person), `POST /admin/invites`, and `POST /admin/users/{id}/disable` (sets `disabled_at` and deletes that user's sessions). A disabled user is treated like an uninvited one.

## (c) Sessions, CSRF and logout

- `sessions(token_hash PRIMARY KEY, user_id REFERENCES users(id), created_at, expires_at, last_seen_at)`. The cookie holds 32 random bytes (`secrets.token_urlsafe`); the DB stores only the SHA-256, so a leaked DB backup can't log anyone in.
- Cookie `__Host-js_session`: `Secure; HttpOnly; SameSite=Lax; Path=/`, no `Domain` (the `__Host-` prefix enforces this), `Max-Age=30d`. Sliding expiry: `expires_at` is extended at most once a day, so reads don't write on every request (WAL writer contention, `src/jobseeker/db/core.py:28`).
- **CSRF, in two layers, without touching the 27 POST forms or `static/swipe.js:70`:**
  1. `SameSite=Lax`: the browser doesn't send the session cookie on cross-site POSTs.
  2. An `OriginCheck` middleware for every non-GET/HEAD request. Allow it when `Sec-Fetch-Site` is `same-origin`, or when `Origin == BASE_URL`. Otherwise return 403. Requests that carry neither header are also refused. Every browser this app targets (iOS Safari 16.4+, Chrome, Firefox) sends `Origin` on form and `fetch` POSTs. `hx-boost` turns forms into XHRs, which are same-origin as well.

  A synchronizer token (hidden field plus `hx-headers`) is the fallback if a client ever turns up that sends no `Origin`. It isn't needed for v1.
- **Logout:** `POST /logout` (a form, so it gets the CSRF check) deletes the session row, expires the cookie and redirects to `/login`. "Sign out everywhere" in Settings deletes all of that user's sessions.
- **Unauthenticated response:** for a normal request, a 303 to `/login?next=<path>`, where `next` is checked with the same local-path rule as `_back`, `src/jobseeker/web/application.py:31`. For HTMX requests (`HX-Request: true`), a 401 with `HX-Redirect: /login`, so a swapped fragment doesn't render the login page inside a card.

## (d) `current_user`, `owned_app`, and making them unskippable

`src/jobseeker/web/deps.py`, new:
```python
def current_user(request: Request, conn=Depends(get_conn)) -> User: ...   # session cookie -> users row; raises NotAuthenticated
def owned_app(app_id: int, user: User = Depends(current_user), conn=Depends(get_conn)) -> int:
    row = conn.execute("SELECT 1 FROM applications WHERE id = ? AND user_id = ?", (app_id, user.id)).fetchone()
    if not row:
        raise HTTPException(404)   # 404, not 403: don't confirm another user's ids exist
    return app_id
```
- FastAPI caches dependencies per request, so `get_conn` returns **one** connection shared by `current_user`, `owned_app` and the route.
- **Wiring:** routers are protected, not individual routes. `app.include_router(r, dependencies=[Depends(current_user)])` for inbox, pipeline and today; `APIRouter(prefix="/applications", dependencies=[Depends(owned_app)])` for `web/application.py:25` and `web/contacts.py:18`. Every one of their routes has `{app_id}`, so the router-level dependency resolves it. Route bodies take `user: User = Depends(current_user)` (cached, so free) wherever they query, and pass `user.id` down.
- **Public allow-list** (the only routes without `current_user`): `/login`, `/auth/callback`, `/logout`, `/healthz`, `/static/*`, `/manifest.webmanifest`, and the public landing page.
- **Data functions take `user_id` explicitly.** `queries.inbox(conn, user_id, ...)`, `ensure_application(conn, user_id, job_id)`, `blocked_companies(conn, user_id)`, `nav_counts(conn, user_id)`, `last_run(conn, user_id)`, and so on, as listed in the audit's §3. No implicit context variable: a missing argument is a `TypeError` in tests, not a silent leak.
- `render` (`web/deps.py:21`) passes `user` into every template; `today.html:6` reads `user.name` instead of `request.app.state.prefs.name`. The background `run_find` (`web/contacts.py:50`) gets `user_id` and re-checks ownership in its own connection.
- **Guard test** (`tests/test_web_guards.py`), which fails when a new route skips the guards:
```python
def _deps(dependant):  # every callable in the dependency tree
    for d in dependant.dependencies:
        yield d.call; yield from _deps(d)
def test_every_route_is_guarded(app):
    for r in app.routes:
        if not isinstance(r, APIRoute) or r.path in PUBLIC:
            continue
        calls = set(_deps(r.dependant))
        assert current_user in calls, f"{r.path} has no current_user"
        if "{app_id}" in r.path:
            assert owned_app in calls, f"{r.path} has no owned_app"
        if r.path.startswith("/admin"):
            assert require_admin in calls
```
  A second, behavioural test sends an anonymous request to every non-public route, filling `{app_id}` with a real id, and expects a 303 to `/login`. That catches a guard which is present but broken.

## (e) The versioned `jobseeker migrate` framework

- `src/jobseeker/db/migrations.py`: `MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]]`, with `LATEST = MIGRATIONS[-1][0]`, recorded in `PRAGMA user_version` (0 in the live DB today).
- `jobseeker migrate [--dry-run]`:
  1. refuse if another process holds the DB (the launchd/systemd units must be stopped; check with `BEGIN IMMEDIATE` and a short timeout);
  2. write a backup with `db/backup.py` and refuse to continue if that fails;
  3. for each pending version: `PRAGMA foreign_keys=OFF` (it has to be set *outside* a transaction), `BEGIN IMMEDIATE`, `fn(conn)`, `PRAGMA foreign_key_check` (any row → `ROLLBACK` and stop), `PRAGMA user_version=N`, `COMMIT`;
  4. then `PRAGMA integrity_check` and `foreign_keys=ON`.

  `--dry-run` runs the same steps on a copy in a temp directory and prints the before and after row counts per table.
- `connect()` (`src/jobseeker/db/core.py:20`):
  - A **fresh** DB (no tables) runs `schema.sql`, which now describes the latest shape, and sets `user_version=LATEST`.
  - An **existing** DB with `user_version < LATEST` raises `SchemaOutOfDate("run `jobseeker migrate`")`.
  - The `NEW_COLUMNS`/`REQUIRED_TABLES` path (`core.py:9-17`) is frozen as the v0 catch-up. It only runs when `user_version == 0`, so a pre-v1 DB gets to the exact shape migration 1 expects.
  - `create_app` calls `connect` once at startup, so a stale schema fails at boot, not on the first request.
- **Migration 1, "users and scoping"** (one transaction):
  1. `CREATE TABLE users, invites, sessions` as in (b) and (c); `INSERT INTO users (id, email, is_admin, created_at) VALUES (1, :owner_email, 1, :now)`. It refuses if `OWNER_EMAIL` is unset.
  2. `CREATE TABLE user_jobs (user_id NOT NULL REFERENCES users, job_id NOT NULL REFERENCES jobs, filter_reason TEXT, prescore INTEGER, evaluated_at TEXT NOT NULL, PRIMARY KEY (user_id, job_id))`; `INSERT INTO user_jobs SELECT 1, id, filter_reason, prescore, first_seen_at FROM jobs`. The `jobs.filter_reason` and `jobs.prescore` columns are **kept**, unread, and dropped in a later migration.
  3. **Rebuild** `applications`, `scores`, `blocklist` and `usage`. For each table T:
     - `CREATE TABLE T_new` with the same columns, plus `user_id INTEGER NOT NULL REFERENCES users(id)` and **no DEFAULT**;
     - `INSERT INTO T_new (id, user_id, <cols>) SELECT id, 1, <cols> FROM T` (`usage` has no id);
     - `DROP TABLE T`; `ALTER TABLE T_new RENAME TO T`; recreate the indexes.

     The constraint changes:
     - `applications`: `UNIQUE(job_id)` becomes `UNIQUE(user_id, job_id)`.
     - `scores`: `idx_scores_job` is replaced by `idx_scores_user_job (user_id, job_id, id)`.
     - `usage`: the PK becomes `(user_id, period, service)`. Groq per-user caps are later tracked here as `service='groq:<model>'`, daily.

     Ids are copied explicitly, so `drafts`, `events`, `application_contacts` and `contact_candidates` keep pointing at the same applications.

     *Why rebuild instead of `ADD COLUMN user_id NOT NULL DEFAULT 1`?* With foreign keys off, that ALTER would be allowed, but the `DEFAULT 1` would stay in the schema for good. Any future INSERT that forgets `user_id` would then silently file the row under the owner, which is exactly the leak this sub-project exists to prevent. Without a default, a forgotten `user_id` fails loudly.
  4. `ALTER TABLE runs ADD COLUMN user_id INTEGER REFERENCES users(id)` (nullable: NULL means the shared fetch run) and `ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy'`; then `UPDATE runs SET user_id = 1`.
  5. **Unchanged (shared, per the Q1 ruling):** `jobs`, `discovered_companies`, `company_domains`, `contacts`, `contact_candidates`. `drafts`, `events` and `application_contacts` stay scoped through their `applications` foreign key. One shared-cache caveat goes to the sub-project 4/5 spec: the contact edit route (`web/contacts.py:114`) rewrites a shared `contacts` row. It must instead insert a manual contact and re-link only this user's `application_contacts` row.
  6. Run `foreign_key_check`, then check that the counts match before and after (jobs 4,497; scores 168; applications 167; drafts 135; events 204 at audit time), and that `SELECT COUNT(*) FROM applications WHERE user_id != 1` returns 0.

## (f) Test fixtures and isolation tests

- **`tests/conftest.py` changes:**
  - `home` (`conftest.py:16-22`) stops copying the real `profile/preferences.yaml`; it uses a fixture `Preferences`.
  - `settings` gains `google_client_id`, `secret_key`, `owner_email` and `base_url="https://testserver"`.
- **New fixtures:**
  - `users`: inserts `owner` (id 1, admin) and `roommate` (id 2) and returns `User` objects.
  - `seeded_two`: shared jobs J1 to J3. Each user gets their own scores, applications, drafts and `user_jobs` on **the same J1**, so the per-user `UNIQUE(user_id, job_id)` path is exercised. The roommate also gets a blocklist row for a contact the owner has linked, and a `usage` row.
  - `client_as(user)`: inserts a session row and returns a `TestClient(app, base_url="https://testserver")` with the cookie and `Origin: https://testserver` set. `anon_client` is the same without a cookie.
  - The existing `seeded` becomes a thin wrapper: `seeded_two`, viewed as the owner.
- **Isolation tests** (`tests/test_isolation.py`):
  - The roommate gets 404 on every `/applications/{owner_app}` route, GET and POST, via the route walk with ids from `seeded_two`.
  - `/`, `/pipeline`, `/today`, the nav badges and the stats show only the caller's rows. The facets don't list the other user's `role_family`.
  - `ensure_application(conn, 2, J1)` returns a new id, not the owner's.
  - The roommate's blocklist doesn't hide the shared contact from the owner (`blocked_profile_urls`, `blocked_names`, `upsert_contact`).
  - `Budget.can` refuses once a user hits their share even with global headroom, and refuses for everyone at the global cap.
  - The run banner shows only the caller's runs plus fetch runs.
- **Auth tests** (`tests/test_auth.py`):
  - state mismatch → 400;
  - nonce mismatch, `email_verified=false` or wrong `aud` → no session;
  - an uninvited email → 403 and no user row;
  - an invited email → user created and `accepted_at` set;
  - the owner's first login fills in `google_sub`;
  - a disabled user is refused;
  - logout deletes the session;
  - a POST with a foreign `Origin`, or with no `Origin` and no `Sec-Fetch-Site`, → 403;
  - an HTMX request without a session → 401 with `HX-Redirect`.

  Google's token endpoint is mocked with `respx`, and `verify_oauth2_token` is monkeypatched, since `pytest-socket` blocks the network.
- **Migration tests** (`tests/test_migrations.py`):
  - Freeze today's `schema.sql` as `tests/fixtures/schema_v0.sql`. Build a v0 DB with data, including two applications on different jobs and drafts/events on them, then migrate. Assert: ids are preserved, `user_id=1` everywhere, `user_jobs` mirrors `jobs`, inserting a duplicate `(user_id, job_id)` fails, inserting without `user_id` fails, `foreign_key_check` is empty and `user_version == 1`.
  - Rerunning the migration is a no-op.
  - `connect()` on a v0 DB raises `SchemaOutOfDate`, and on a fresh DB it lands directly at `LATEST`.
- The guard test (d) and these suites run in the normal `uv run pytest`. The 14 existing web test files switch from `TestClient(create_app(settings))` to `client_as(owner)`.

## Open points for the spec
1. Whether to send invite emails: probably not; the admin shares the link by hand.
2. Session length: 30 days sliding is proposed, suited to a phone PWA.
3. Should `/admin` show per-user usage in v1 or wait for sub-project 6? It's cheap once `usage.user_id` exists.
