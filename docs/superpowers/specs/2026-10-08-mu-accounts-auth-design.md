# job-seeker2.0 multi-user: accounts, sign-in and data scoping (design)

**Date:** 2026-10-08
**Status:** The combined multi-user design was approved by the user on 2026-10-08. This is the written spec for sub-project 2, awaiting review.
**Depends on:**
- Sub-project 1 (hosting) only for deployment: HTTPS on `BASE_URL` through Caddy, and uvicorn `--proxy-headers`. Everything here also runs and is tested locally.
- Sub-projects 3-6 build on this one.

**Builds on:** the MVP, job-discovery, mobile-access, contact-finder and UI-redesign specs, which still hold except where this one changes them. Research: `docs/superpowers/research/2026-10-08-multi-user-impact.md` (the audit) and `…-auth-scoping-proposal.md`.

## 1. Goal

Turn the single-user app into an invite-only, multi-user app with **Google sign-in**, where **every row of personal data belongs to one user**, so no user can ever see or change another user's data. The owner's existing data (4,497 jobs, 167 applications, …) becomes user 1's, unchanged.

## 2. Non-goals

- **Onboarding, the Settings page, and per-user preferences and facts:** sub-project 3. Until it lands, every user's preferences come from today's `profile/preferences.yaml`, and only the owner uses the app.
- **The per-user daily run, fair budgets, `tick`:** sub-project 4. Until it lands, the CLI pipeline runs as the owner (`user_id=1`).
- **Per-user Gmail and the outreach gate:** sub-project 5.
- **The landing page, `/healthz`, push and backups:** sub-project 6. Here they're only listed as public routes.
- **Invite emails:** none. The owner adds an email in `/admin` and shares the URL by hand.
- **Password or email sign-in, other identity providers, multiple admins in v1:** not planned.

## 3. Decisions (brainstorming and coordinator rulings)

| Topic | Decision |
|---|---|
| Sign-in | A hand-rolled OAuth 2.0 authorization-code flow with **PKCE, state and nonce**. ID-token verification is delegated to `google-auth` (`google.oauth2.id_token.verify_oauth2_token`). Authlib was rejected: it needs two extra dependencies and brings its own cookie session system. |
| Scopes | Sign-in is **identity only**: `openid email profile`. Gmail compose is a separate consent (sub-project 5). |
| Google client | One Google **Web** OAuth client (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`), with the redirect URI `BASE_URL/auth/callback`. Sub-project 5 adds `/gmail/callback`. |
| Access | Invite-only allow-list. The owner is user 1 (`OWNER_EMAIL`), the only admin in v1. |
| Sessions | Server-side DB rows. The cookie holds a random token; the DB stores its SHA-256. 30 days, sliding. |
| CSRF | `SameSite=Lax` plus an **Origin / `Sec-Fetch-Site` check** on every non-GET request. No per-form tokens. |
| Guards | Router-level `current_user` and `owned_app` dependencies, enforced by a route-walk test. |
| Unauthorised access | **404** for another user's application (ids aren't confirmed to exist). |
| Migrations | Versioned through `PRAGMA user_version` and an explicit `jobseeker migrate`, with a backup first. Never on connect. |
| Admin v1 | Minimal: an invites list (add/remove), a users list (disable), and a read-only usage table per user and service for the current day and month. No charts. |
| Dependencies | Add **`google-auth`** as a direct dependency in `pyproject.toml`. Today it's only transitive, through `google-auth-oauthlib`. `requests` stays transitive and is used by `google.auth.transport.requests`. |

## 4. Design

### 4.1 Configuration

New `Settings` fields (`src/jobseeker/config.py:11`), read from the environment. The names match the hosting spec's `.env` table:

| Variable | Use |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | the Web OAuth client |
| `BASE_URL` | exact origin, e.g. `https://<sub>.duckdns.org`; used for the redirect URI and the Origin check (never `request.url`) |
| `SECRET_KEY` | ≥ 32 random bytes; HMAC key for the short-lived OAuth cookie |
| `OWNER_EMAIL` | the owner's Google email; required by migration v1 |
| `COOKIE_SECURE` | default `true`; tests use `base_url="https://testserver"` rather than turning it off |

`create_app` refuses to start if `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `BASE_URL` or `SECRET_KEY` is empty, naming the missing variable.

### 4.2 The sign-in flow (`src/jobseeker/web/auth.py`)

1. **`GET /login?next=<path>`**:
   - generates `state` and `nonce` (`secrets.token_urlsafe(32)`) and a PKCE `verifier` (`secrets.token_urlsafe(64)`) with `challenge = BASE64URL(SHA256(verifier))`;
   - stores `{state, nonce, verifier, next}` in the cookie `__Host-js_oauth`: JSON, base64, with an HMAC-SHA256 under `SECRET_KEY`, and an `exp` 10 minutes ahead. Flags: `Secure; HttpOnly; SameSite=Lax; Path=/`. Lax is required because the callback is a top-level GET from Google;
   - redirects (303) to `https://accounts.google.com/o/oauth2/v2/auth` with `client_id`, `redirect_uri=BASE_URL/auth/callback`, `response_type=code`, `scope=openid email profile`, `state`, `nonce`, `code_challenge`, `code_challenge_method=S256` and `prompt=select_account`.
2. **`GET /auth/callback?code&state`**:
   1. Verify the oauth cookie's HMAC and `exp`, and that `state` matches. Otherwise return 400 "Sign-in expired, try again" with a link to `/login`.
   2. POST to `https://oauth2.googleapis.com/token` (`httpx`, 10 s timeout) with `code`, `client_id`, `client_secret`, `redirect_uri`, `grant_type=authorization_code` and `code_verifier`.
   3. `verify_oauth2_token(id_token, google.auth.transport.requests.Request(), GOOGLE_CLIENT_ID)` checks the signature, `aud`, `iss` and `exp`.
   4. Require `claims["nonce"] == nonce` and `claims["email_verified"] is True`.
   5. Resolve the user (§4.3), create a session (§4.4), delete the oauth cookie, and redirect 303 to `next`. `next` must be a local path, checked with the same rule as `_back` at `src/jobseeker/web/application.py:31`; otherwise redirect to `/`.
3. Google returning `error=access_denied` → redirect to `/login` with "Sign-in was cancelled".

### 4.3 Users, invites and the admin role

- **Resolving a verified sign-in**, in order:
  1. `users.google_sub = sub`.
  2. Else `users.email = lower(email) AND google_sub IS NULL`: the owner's first login. Set `google_sub`.
  3. Else `invites.email = lower(email)`: insert a `users` row and set `invites.accepted_at`.
  4. Else render a 403 page: "This app is invite-only. Ask {owner_first_name} for an invite." `{owner_first_name}` comes from the same helper the landing page uses (sub-project 6): the first name of `users.id = 1`, falling back to "the person who shared this link". No owner name is hard-coded. It reuses `landing.html` (sub-project 6) with the invite note in place of the button; until then, a plain card. No row is created.
- **Login rules:**
  - A user with `disabled_at` set is refused with the same 403 page.
  - Every login updates `last_login_at`, plus `name` from `claims["name"]`.
  - After the first login, identity is `sub`, so a changed Gmail address can't take over an account.
- **`require_admin`** = `current_user` + `is_admin`, **else 404**.
- **Admin pages** use the `ui.css` card layout and are reached from a sidebar link shown only to admins:
  - `GET /admin`: invites (email, invited, accepted) with an add form and Remove buttons; users (email, name, last login, status) with Disable/Enable; and the **usage table**: rows are users, columns are each `usage.service`, showing today's daily services and this month's monthly services. Read-only. Sub-project 6 adds a "Backups" card here.
  - `POST /admin/invites` (adds a lower-cased email; ignores duplicates).
  - `POST /admin/invites/{email}/remove` (doesn't affect an existing user).
  - `POST /admin/users/{id}/disable`: sets `disabled_at` and deletes the user's sessions. Refused for the last admin.
  - `POST /admin/users/{id}/enable`.

### 4.4 Sessions

- **Cookie:** `__Host-js_session`. Value: `secrets.token_urlsafe(32)`. Flags: `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000` (30 days), with no `Domain`.
- **Row:** `sessions(token_hash = sha256(token), user_id, created_at, expires_at, last_seen_at)`.
- **`current_user`:**
  - hashes the cookie, joins `users`, and requires `expires_at > now` and `disabled_at IS NULL`;
  - when `last_seen_at` is more than 24 h old, extends `expires_at` to now + 30 days, updates `last_seen_at` and re-sets the cookie. At most one write per session per day, which keeps reads lock-free (WAL; `src/jobseeker/db/core.py:28`);
  - stores the `User` on `request.state.user`.
- **Clean-up:** expired sessions are deleted opportunistically, on 1 in 100 logins. No timer is needed.

### 4.5 CSRF: the `OriginCheck` middleware

For any method other than GET, HEAD or OPTIONS:
- **Allow** when `Sec-Fetch-Site` is `same-origin`, or when `Origin == BASE_URL`.
- **Reject with 403** when `Origin` is present and different, when `Sec-Fetch-Site` is `cross-site`/`same-site`, or when **both headers are missing**.

Every form POST (about 27 in the templates) and `static/swipe.js:70` (`fetch` with `credentials: "same-origin"`) already send `Origin` in the target browsers, so no template changes are needed. `/auth/callback` is a GET, so it isn't affected.

### 4.6 Logout and unauthenticated responses

- **`POST /logout`:** deletes the session row, expires the cookie, and redirects 303 to `/login`. **`POST /logout/all`** deletes every session for the user. Both get the Origin check. A "Sign out" control goes in the sidebar footer and, on phone, under the existing More menu.
- **Unauthenticated request to a guarded route:**
  - a normal request gets a 303 to `/login?next=<path+query>`;
  - an HTMX request (`HX-Request: true`) gets a **401** with the header `HX-Redirect: /login?next=<HX-Current-URL path>`;
  - `fetch` from `swipe.js` gets a 401 and falls back to its existing error toast.

### 4.7 Guards and wiring (`src/jobseeker/web/deps.py`)

```python
def current_user(request, conn=Depends(get_conn)) -> User            # raises NotAuthenticated → §4.6
def owned_app(app_id: int, user=Depends(current_user), conn=Depends(get_conn)) -> int:
    if not conn.execute("SELECT 1 FROM applications WHERE id = ? AND user_id = ?", (app_id, user.id)).fetchone():
        raise HTTPException(404)
    return app_id
def require_admin(user=Depends(current_user)) -> User                # 404 unless user.is_admin
```
- FastAPI caches dependencies within a request, so `get_conn` yields **one** connection, shared by the guards and the route.
- **Routers:**
  - `inbox`, `pipeline` (with `/today`): included with `dependencies=[Depends(current_user)]`;
  - `application` (`web/application.py:25`) and `contacts` (`web/contacts.py:18`): `APIRouter(prefix="/applications", dependencies=[Depends(owned_app)])`;
  - the new `admin` router uses `require_admin`.
- **Public routes (`PUBLIC`):** `/login`, `/auth/callback`, `/logout`, `/logout/all`, `/healthz` (GET and HEAD), `/sw.js`, `/static/*`, `/manifest.webmanifest`. `/logout*` require a session but tolerate a missing one.
- **`/` is the one mixed route.** It depends on `optional_user` (`current_user` that returns `None` instead of raising). A signed-in user gets the Jobs inbox (and `require_onboarded`, sub-project 3). An anonymous visitor gets the public landing page, `landing.html` (sub-project 6), or a 303 to `/login` until that template exists.
- `/healthz` is defined by sub-project 6. It opens the DB read-only and doesn't use `get_conn`. It returns `200 {"ok": true}` or `503 {"ok": false, "check": "db" | "schema"}`, where `schema` means `user_version != LATEST` (§4.9).
- **Background work:** `run_find` (`web/contacts.py:50`) receives `user_id`, and re-checks ownership on its own connection before doing anything.
- **Templates:** `render` (`web/deps.py:21`) adds `user` to every template context. `today.html:6` reads `user.name`.

### 4.8 Data access takes `user_id` explicitly

Every function that touches per-user data gets a required `user_id` parameter. There's no implicit context, so a missing argument is a `TypeError` in tests, not a silent leak. The list comes from the audit's §3:

- **`db/queries.py`:**
  - `_LATEST_SCORE` adds `AND user_id = a.user_id`;
  - `inbox`, `inbox_facets` (role families from this user's scores), `application_detail`, `pipeline`, `stats` (events joined to this user's applications) and `today` all filter on `a.user_id`.
- **`db/jobs.py`:**
  - `save_score` and `latest_score` take `user_id`;
  - `set_filter_reason`/`set_prescore` become `set_user_job(conn, user_id, job_id, filter_reason=…, prescore=…)` on `user_jobs`;
  - `expire_unscored`, `jobs_missing_prescore` and `jobs_needing_score` read `user_jobs` and this user's scores.
- **`db/applications.py`:**
  - `ensure_application(conn, user_id, job_id)` (`INSERT OR IGNORE … (user_id, job_id)`, then select by both);
  - `blocked_companies(conn, user_id)`;
  - `mark_not_interested` writes `blocklist.user_id`;
  - `save_contact` checks this user's blocklist only.
- **`db/contacts_repo.py`:** `blocked_profile_urls`, `blocked_names` and `upsert_contact`'s block check take `user_id`. The shared-contacts layering is sub-project 5.
- **`db/runs.py`:** `start_run(conn, now, user_id=None, kind=…)` and `last_run(conn, user_id)` (the user's runs, plus runs with `user_id IS NULL`).
- **`db/usage.py`:** `Budget(conn, user_id, limits, now)`. Here `limits: dict[service, Limit(period, global_cap, share_cap)]`. `can` requires the user's own usage ≤ `share_cap` **and** everyone's ≤ `global_cap`; `spend` writes the user's row.

  In this sub-project the limits come from `prefs.contacts` with `share_cap == global_cap`, since the owner is the only user. Sub-projects 3-5 add services and compute shares.
- **`web/view.py:83-91`:** `nav_counts(conn, user_id)`.
- **`pipeline/run.py`:**
  - `run_daily(…, user_id)` threads the id through `_fetch`, `_rank`, `_select`, `_apps_needing_drafts` and `_run`;
  - **interim:** `src/jobseeker/cli.py` passes `user_id=1`.
- **`pipeline/refilter.py`:** `refilter(conn, user_id, …)` joins `applications` on `user_id`.
- **`jobs.filter_reason` and `jobs.prescore`** are no longer read or written by any code after this sub-project. They stay in the schema until a later migration drops them.

### 4.9 The `jobseeker migrate` framework (`src/jobseeker/db/migrations.py`)

- `MIGRATIONS: list[Migration(version, name, apply)]`, with `LATEST = MIGRATIONS[-1].version`. The versions in this release are v1 (this spec), v2 (sub-project 3: onboarding), v3 (sub-project 6: extras), v4 (sub-project 4: pipeline) and v5 (sub-project 5: outreach). The numbers order schema changes only; v3 and v4 don't depend on each other's tables.
- **`jobseeker migrate [--dry-run]`** (there's no import flag: v2 reads the owner's files from `$JOBSEEKER_HOME/profile/`):
  1. **Exclusive access:** open the DB, `BEGIN IMMEDIATE` with a 5 s busy timeout, then roll back. If it times out: "Database is busy: stop jobseeker-web and the tick timer first". Exit 1.
  2. **Backup:** write `data/backups/pre-migrate-v<from>-<timestamp>.db` using `db/backup.py`'s snapshot function (unchanged; SQLite backup API). If that fails, stop. The hosting `deploy.sh` stops the web service and the tick timer around `migrate`.
  3. **Each pending version, in order:**
     - `PRAGMA foreign_keys=OFF` (outside a transaction), then `BEGIN IMMEDIATE`, then `apply(conn, ctx)`;
     - `PRAGMA foreign_key_check`: any row → `ROLLBACK`, print the rows, exit 1;
     - `PRAGMA user_version = N`, then `COMMIT`.
  4. Then `PRAGMA integrity_check` must be `ok`, then `foreign_keys=ON`.
  5. Print row counts per table, before and after.

  `--dry-run` copies the DB to a temp dir, migrates the copy, and prints the same report.
- **`connect()` (`db/core.py:20-41`):**
  - A **fresh** file (no tables) runs `schema.sql` (now the latest shape) and sets `user_version = LATEST`.
  - `user_version == 0` with tables: run the frozen v0 catch-up (today's `REQUIRED_TABLES`/`NEW_COLUMNS`) only.
  - Then, if `user_version < LATEST`, raise `SchemaOutOfDate("Run `jobseeker migrate`")`. `migrate` itself opens without this check.
  - `create_app` opens one connection at startup, so a stale schema fails at boot, not on the first request.

### 4.10 Migration v1: users and scoping

It runs inside the framework's transaction with foreign keys off, and requires `OWNER_EMAIL`.

1. Create `users`, `invites` and `sessions` (§5). `INSERT INTO users (id, email, name, is_admin, created_at) VALUES (1, lower(:owner_email), '', 1, :now)`.
2. Create `user_jobs`, then `INSERT INTO user_jobs (user_id, job_id, filter_reason, prescore, jd_hash, evaluated_at) SELECT 1, id, filter_reason, prescore, jd_hash, first_seen_at FROM jobs`. `jd_hash` is copied so sub-project 4's `evaluate` doesn't redo all jobs.
3. **Rebuild `applications`, `scores`, `blocklist` and `usage`.** For each table T:
   - `CREATE TABLE T_new (…)` with the §5 shape: `user_id INTEGER NOT NULL REFERENCES users(id)` with **no DEFAULT**;
   - `INSERT INTO T_new (id, user_id, <every other old column>) SELECT id, 1, <every other old column> FROM T` (`usage` has no `id`);
   - `DROP TABLE T`; `ALTER TABLE T_new RENAME TO T`; recreate T's indexes.

   Ids are copied explicitly, so `drafts`, `events`, `application_contacts` and `contact_candidates` keep pointing at the same applications. There's no DEFAULT on purpose: an INSERT that forgets `user_id` must fail, never silently file the row under the owner.
4. `ALTER TABLE runs ADD COLUMN user_id INTEGER REFERENCES users(id)` and `ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy'`; then `UPDATE runs SET user_id = 1`.
5. **Post-checks** (all inside the transaction):
   - row counts for applications, scores, blocklist, usage, drafts, events and jobs are unchanged;
   - `user_jobs` count = `jobs` count;
   - `SELECT COUNT(*) FROM applications WHERE user_id != 1` = 0.

   Any mismatch raises and the migration rolls back.

`schema.sql` is updated to describe the post-v1 shape (and, as later sub-projects land, the latest shape), so fresh databases match migrated ones. A test checks this (§7).

## 5. Data model (after v1)

```sql
users(id INTEGER PRIMARY KEY, google_sub TEXT UNIQUE, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '',
      is_admin INTEGER NOT NULL DEFAULT 0, disabled_at TEXT, created_at TEXT NOT NULL, last_login_at TEXT)
invites(email TEXT PRIMARY KEY, invited_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, accepted_at TEXT)
sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
         expires_at TEXT NOT NULL, last_seen_at TEXT NOT NULL)
CREATE INDEX idx_sessions_user ON sessions (user_id);
user_jobs(user_id INTEGER NOT NULL REFERENCES users(id), job_id INTEGER NOT NULL REFERENCES jobs(id),
          filter_reason TEXT, prescore INTEGER, jd_hash TEXT NOT NULL, evaluated_at TEXT NOT NULL,
          PRIMARY KEY (user_id, job_id))
CREATE INDEX idx_user_jobs_open ON user_jobs (user_id, filter_reason);
applications: + user_id INTEGER NOT NULL REFERENCES users(id); UNIQUE (user_id, job_id) replaces UNIQUE (job_id)
scores:       + user_id INTEGER NOT NULL REFERENCES users(id); idx_scores_user_job (user_id, job_id, id) replaces idx_scores_job
blocklist:    + user_id INTEGER NOT NULL REFERENCES users(id)
usage:        + user_id INTEGER NOT NULL REFERENCES users(id); PRIMARY KEY (user_id, period, service)
runs:         + user_id INTEGER REFERENCES users(id) (NULL = shared fetch run), + kind TEXT NOT NULL DEFAULT 'legacy'
```

**Unchanged and shared:** `jobs` (its `filter_reason`/`prescore` columns are unused), `discovered_companies`, `company_domains`, `contacts`. **Scoped through `applications`:** `drafts`, `events`, `application_contacts`, `contact_candidates`.

## 6. Errors

| Situation | Behaviour |
|---|---|
| Missing auth env vars | `create_app` exits at startup naming the variable; `migrate` requires `OWNER_EMAIL` |
| OAuth cookie missing or expired, state mismatch | 400 "Sign-in expired, try again" + link to `/login`; no session |
| Token exchange fails or times out (10 s) | 502 page "Couldn't reach Google, try again"; logged |
| ID token invalid (signature, `aud`, `iss`, `exp`), nonce mismatch, `email_verified` false | 400 "Sign-in couldn't be verified"; no session; logged |
| Uninvited or disabled | 403 invite-only page; no user row is created |
| Session expired or unknown | §4.6: 303 to `/login`, or 401 + `HX-Redirect` |
| Another user's application id | 404 |
| Non-admin on `/admin*` | 404 |
| Cross-site or header-less POST | 403 "Request blocked" (plain text) |
| Old schema at startup | `SchemaOutOfDate`; the web service doesn't start and the message names `jobseeker migrate` |
| Migration check fails | rolled back, offending rows printed, exit 1; the DB is unchanged and the pre-migrate backup remains |
| Disabling the last admin | refused with "There must be at least one admin" |

## 7. Testing

No network: Google's token endpoint is mocked with `respx`, and `verify_oauth2_token` is monkeypatched to return given claims or raise.

- **Fixtures** (`tests/conftest.py`):
  - `home` stops copying the real `profile/preferences.yaml` and writes a fixture file instead;
  - `settings` gains `google_client_id`, `google_client_secret`, `secret_key`, `owner_email` and `base_url="https://testserver"`;
  - new `users` fixture: `owner` (id 1, admin) and `roommate` (id 2);
  - **`seeded_two`:** shared jobs J1-J3. Each user has their own `user_jobs`, scores and applications **on the same J1**, plus drafts and events. The roommate has a blocklist row and a `usage` row;
  - `client_as(user)`: inserts a session row, returns a `TestClient(app, base_url="https://testserver")` with the session cookie and `Origin: https://testserver` set;
  - `anon_client`: the same without a cookie;
  - the existing `seeded` becomes `seeded_two` seen as the owner;
  - the about 14 web test files switch from `TestClient(create_app(settings))` to `client_as(owner)`.
- **Guard test** (`tests/test_web_guards.py`):
  - walk `app.routes`, collecting every dependency callable recursively from `route.dependant`;
  - every `APIRoute` not in `PUBLIC` must include `current_user`, except `/`, which must include `optional_user`;
  - every path containing `{app_id}` must include `owned_app`;
  - every `/admin` path must include `require_admin`;
  - **behavioural:** `anon_client` requests every non-public route (path params filled from `seeded_two`) and expects 303 to `/login`, or 401 with `HX-Redirect` when sent with `HX-Request`. An anonymous `/` gets the landing page (200) or a 303 to `/login` before sub-project 6, and never inbox data.
- **Isolation** (`tests/test_isolation.py`):
  - the roommate gets 404 on every `/applications/{owner_app_id}…` route, GET and POST;
  - `/`, `/pipeline`, `/today`, the nav counts, `stats` and the facets show only the caller's rows;
  - `ensure_application(conn, 2, J1)` returns a different id from the owner's;
  - the roommate's blocklist doesn't affect the owner's `blocked_companies`/`blocked_profile_urls`/`blocked_names`;
  - `Budget` refuses at the user's share and at the global cap;
  - `last_run` shows only the caller's runs plus shared ones;
  - inserting into `applications`, `scores`, `blocklist` or `usage` without `user_id` raises `IntegrityError`.
- **Auth** (`tests/test_auth.py`):
  - `/login` sets the oauth cookie and redirects with S256 PKCE, state, nonce and the exact scopes;
  - in the callback: state mismatch → 400; expired oauth cookie → 400; tampered HMAC → 400; nonce mismatch, `email_verified=False` or a verify exception → no session;
  - uninvited → 403 and no row; invited → user created and `accepted_at` set;
  - the owner's first login fills `google_sub`; a later login with the same `sub` and a new email still resolves to the owner;
  - disabled → 403;
  - sliding expiry writes at most once per 24 h;
  - `POST /logout` deletes the row; `/logout/all` deletes all of the user's sessions;
  - `next` rejects `//evil.com` and `https://evil.com`.
- **CSRF:** POST with a foreign `Origin` → 403; with no `Origin` and no `Sec-Fetch-Site` → 403; with `Sec-Fetch-Site: same-origin` and no `Origin` → allowed; GET is never blocked.
- **Admin:** a non-admin gets 404; invite add/remove; disable deletes sessions and blocks login; the last admin can't be disabled; the usage table shows each user's day and month numbers from `seeded_two`.
- **Migrations** (`tests/test_migrations.py`):
  - today's `schema.sql` is frozen as `tests/fixtures/schema_v0.sql`; build a v0 DB with data (two applications on different jobs, with drafts and events), then `migrate`;
  - ids are preserved, `user_id = 1` everywhere, `user_jobs` mirrors `jobs` (including `jd_hash`), `UNIQUE(user_id, job_id)` holds, inserting without `user_id` fails, `foreign_key_check` is empty, `user_version == 1`;
  - a second `migrate` is a no-op;
  - `connect()` on v0 raises `SchemaOutOfDate`; on a fresh file it lands at `LATEST`;
  - a fresh `schema.sql` DB and a migrated v0 DB have identical `sqlite_master` table definitions (normalised);
  - `--dry-run` leaves the file byte-identical;
  - a missing `OWNER_EMAIL` aborts before any change.
- **Regression:** the whole existing suite passes with the owner fixture. Today that's 346 tests.

## 8. Acceptance criteria

1. On a copy of the live DB, `jobseeker migrate` completes, the row counts match, `foreign_key_check` is clean, and the owner signs in with Google and sees the same Today, Jobs, Job detail and Pipeline as before the migration.
2. An invited second Google account can sign in. It sees empty lists, and every attempt to open one of the owner's application ids returns 404.
3. An uninvited Google account gets the invite-only page and no user row.
4. The guard test fails if a new route is added without `current_user` (verified by temporarily adding one).
5. Cross-site POSTs are rejected; logout and logout-all end sessions.
6. The web service refuses to start on an un-migrated DB.
7. `google-auth` is a direct dependency in `pyproject.toml`, and `uv.lock` is updated.
8. All tests pass, with no network.
