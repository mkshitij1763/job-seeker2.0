# Multi-user outreach (Gmail and contacts): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Chosen method for this plan: Native (inline), via superpowers:executing-plans** (as for plans 2 and 3).

**Goal:** Outreach becomes a per-user switch (`users.outreach_enabled`, off for roommates, an admin toggle). Each outreach user drafts into their **own** Gmail through an encrypted, reconnectable token. Contact lookups are shared and cached, while edits, "not interested" and who-was-emailed stay private. Budgets are split among outreach users only, and SMTP verification can be switched off for the server.

**Architecture:**
- `require_outreach` (404 when off) replaces plan 2's interim `require_owner`, and `user.outreach_enabled` replaces the `can_outreach = user.id == OWNER_ID` template flag.
- Gmail tokens live in `gmail_tokens`, sealed with AES-256-GCM under `TOKEN_KEY`, with AAD `user:<id>`. `load_service(conn, user_id, key)` replaces the Desktop-client `token.json`.
- `contacts.owner_user_id` splits the shared cache (`NULL`) from private rows. Edits are copy-on-write, and bounces stay shared.
- `people_searches` caches Tavily and Apify people searches for 30 days.
- `outreach_limits(conn, contacts, global_drafts_per_day)` gives every service a per-user share of `floor(global / outreach users)`.
- Migration **v5**.

**Tech Stack:** Python 3.13, FastAPI, Jinja2 + HTMX, SQLite, `cryptography` (AESGCM), `google-auth` (`Credentials`), `httpx` + `respx`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-mu-outreach-design.md`. Research: `docs/superpowers/research/2026-10-08-outreach-proposal.md`.

## Preconditions (read first)

1. **The per-user pipeline plan (`2026-10-08-mu-per-user-pipeline.md`) is fully merged into `multi-user`** (devops-lead2's `build/devops2`, through pipeline Task 16), and so are migrations **v3 (extras) and v4 (pipeline)**. This plan's migration is **v5**, and Task 6 edits `pipeline/draft.py`, which pipeline Task 11 creates (`drafts_enabled`, `draft_round_robin`, `draft_application`).
   Check: `grep -n "MIGRATIONS.append(Migration(4" src/jobseeker/db/migrations.py && test -f src/jobseeker/pipeline/draft.py && ! grep -n "def draft_application" src/jobseeker/pipeline/run.py`. If any part fails, stop and tell `manager`.
2. Plans 2 and 3 are built (`require_owner`, `can_outreach`, `current_prefs`, `owned_app`, `user_scoped_tables`, `seeded_two`, `client_as`, `AUTH_TEST`).

### File overlap with devops-lead2 (pipeline T12/T13, still in progress when this plan was written)

| File | Pipeline task(s) | This plan | What to watch for |
|---|---|---|---|
| `src/jobseeker/pipeline/draft.py` | T11 creates it | T6 | `drafts_enabled` → `user.outreach_enabled`; the draft share comes from `outreach_limits` |
| `src/jobseeker/pipeline/run.py` | T12 rewrites it (`run_all`) | T6 reads it only | the eligible-drafters line (`drafts_enabled(u)`) keeps working, because T6 changes the function, not the call |
| `src/jobseeker/web/application.py` | T12 deletes `run.draft_application`, so `draft_now`'s import must point at `pipeline.draft` | T3 moves `draft_now` into `web/outreach.py` | if T12 didn't already fix the import, T3 imports from `jobseeker.pipeline.draft` |
| `src/jobseeker/cli.py` | T13 rewrites `run`/`rescore`/`tick`/backup | T8 deletes `auth-gmail` | only the `auth-gmail` command and the `secrets_dir` mkdir in `init` change |
| `src/jobseeker/web/app.py` | T14 adds Fetch-now routes | T1, T3, T8 | startup checks, router includes, `gmail_factory` |
| `src/jobseeker/web/templates/today.html`, `pipeline.html`, `base.html` | T15 header notes and IST times | T3 | `can_outreach` already gates Today; T3 adds pipeline-column hiding |
| `src/jobseeker/db/usage.py` | T10/T11 use `Budget`/`Limit` | T5 | the new `outreach_limits`, and `Budget.summary` grows "All …" |
| `src/jobseeker/config.py` (`AppBudgets`, `ContactsConfig`) | T3 adds `global_drafts_per_day` etc. | T7 | adds `ContactsConfig.smtp_verify` only |
| `src/jobseeker/db/migrations.py`, `schema.sql` | T4 (v4) | T2 (v5) | append after v4 |
| `src/jobseeker/db/account.py` | T16 delete coverage | T9 | `gmail_tokens` and private contacts |

## Global Constraints

- Test commands: `FORCE_COLOR= uv run pytest --color=no -p no:warnings` (never `-q`). Node: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`. **Every task ends with the full suite green**, the pytest count never below the previous task's count, and 19 node tests.
- No network in tests: Google endpoints via `respx`, `verify_id_token` stubbed, the Gmail service faked, Tavily/Apify/Hunter faked.
- Migration number **v5**. Gmail scope stays `https://www.googleapis.com/auth/gmail.compose` (plus `openid email` for the connect flow only). Sign-in never requests `gmail.compose`.
- `TOKEN_KEY`: base64 of exactly 32 bytes (`jobseeker gen-key`). Separate from `BACKUP_KEY`. The web app refuses to start without it.
- Token AAD: `b"user:%d" % user_id`. Cookie for the Gmail OAuth round trip: `__Host-js_gmail_oauth`.
- `contacts.smtp_verify: Literal["off", "on", "auto"] = "off"`.
- People-search reuse window: **30 days**. Per-user share: `floor(global / n)` (Apify: `round(global / n, 2)`), `n = max(1, outreach-enabled, not-disabled users)`.
- Copy (verbatim):
  - "Gmail needs reconnecting"
  - "Google didn't grant offline access. Try again"
  - "Gmail connected: drafts go to {email}"
  - "Email checks aren't available on this server; emails are best guesses unless Apify or Hunter found them."
  - "Finding contacts timed out. Try again."
  - "Your {Service} share is used for {Month}" / "Shared {Service} budget used for {Month}"
- Every task commit also updates `HANDOFF-backend.md` (§2 table row "P5-T<n> …", the NEXT line, and §3 rulings) and is pushed with `git push origin multi-user` (`manager`'s standing rule). Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never edit, build in or migrate the main checkout or its `data/`.

## Review Focus

1. **A token row copied to another user** (DB edit, restore mix-up): it must fail to decrypt (AAD), be marked expired and offer Reconnect. It must never draft into the wrong Gmail. Task 1 tests the AAD swap, and Task 8 tests that `load_service` turns a decrypt failure into `reconnect=True`.
2. **Two users who find contacts for the same company the same day:** the second spends 0 Tavily and still gets their own ranking, their own `application_contacts` and their own blocklist filtering. A person blocked by B must still appear for A (Task 4 + Task 5 combined test).
3. **Editing a shared contact's email to an address the user controls** (plan 2's I1): the other user's Approve still drafts to the original address (Task 4).
4. **Outreach turned off while a find or approve is in flight, or with drafts and `application_contacts` in place:** every outreach route returns 404, the rest of the job page still renders, the drafts stay in the DB, and turning outreach back on shows them again (Task 3).
5. **The Gmail callback arriving with someone else's account** (the user picks a different Google account at consent): drafts go to that account, and the Settings card must show which address. `account_email` comes from the ID token, not `users.email` (Task 8).

---

## File structure

| File | Responsibility |
|---|---|
| `src/jobseeker/crypto.py` (new) | `load_token_key`, `seal`, `open_`, `TokenKeyError`, `DecryptError` |
| `src/jobseeker/db/migrations.py`, `schema.sql` | `migrate_v5` (+ fresh-schema DDL) |
| `src/jobseeker/db/users.py` | `User.outreach_enabled`, `set_outreach`, `outreach_user_count` |
| `src/jobseeker/db/gmail_tokens.py` (new) | `save_token`, `load_token`, `mark_expired`, `delete_token`, `token_info` |
| `src/jobseeker/gmail/client.py` | `load_service(conn, user_id, key)`, `create_draft(service, raw, on_auth_error=None)`, `GmailUnavailable.reconnect` |
| `src/jobseeker/web/gmail.py` (new) | `GET /gmail/connect`, `GET /gmail/callback` |
| `src/jobseeker/web/outreach.py` (new) | the outreach routes moved from `web/application.py` |
| `src/jobseeker/web/deps.py` | `require_outreach` (replaces `require_owner`), `render()` `can_outreach` from the user, the reconnect flash |
| `src/jobseeker/web/admin.py` | `POST /admin/users/{user_id}/outreach` |
| `src/jobseeker/db/contacts_repo.py`, `db/applications.py` | owner-scoped matching, private rows, copy-on-write edit, people-search cache |
| `src/jobseeker/db/usage.py` | `outreach_limits`, `Budget.summary` with "All" |
| `src/jobseeker/contacts/finder.py` | cache use, draft units, SMTP switch, wording |
| `src/jobseeker/contacts/smtp_probe.py` (new) | `port25_open(conn, now, probe=...)` with the 24 h `app_state` memo |
| `src/jobseeker/pipeline/draft.py` | `drafts_enabled` → `outreach_enabled`; the share from `outreach_limits` |
| `src/jobseeker/db/account.py` | delete/export coverage |

---

### Task 1: Token encryption and `TOKEN_KEY`

**Files:**
- Create: `src/jobseeker/crypto.py`
- Modify: `src/jobseeker/config.py` (`Settings.token_key: str = ""`), `src/jobseeker/web/app.py` (startup check; `app.state.token_key`)
- Modify: `tests/conftest.py` (`AUTH_TEST` gains `token_key`)
- Test: `tests/test_crypto.py` (new), `tests/test_auth.py` (append)

**Interfaces:**
- Produces: `TokenKeyError(ValueError)`, `DecryptError(ValueError)`, `load_token_key(b64: str) -> bytes`, `seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes`, `open_(key: bytes, blob: bytes, aad: bytes) -> bytes`, `user_aad(user_id: int) -> bytes`; `app.state.token_key: bytes`.

- [ ] **Step 1: Write the failing tests** (`tests/test_crypto.py`):

```python
import base64

import pytest

from jobseeker.crypto import DecryptError, TokenKeyError, load_token_key, open_, seal, user_aad

KEY = base64.b64encode(b"k" * 32).decode()


def test_roundtrip_and_fresh_nonce():
    key = load_token_key(KEY)
    a, b = seal(key, b"secret", user_aad(1)), seal(key, b"secret", user_aad(1))
    assert a != b and open_(key, a, user_aad(1)) == b"secret"


def test_wrong_user_aad_fails():  # a row copied to another user never decrypts
    key = load_token_key(KEY)
    with pytest.raises(DecryptError):
        open_(key, seal(key, b"secret", user_aad(1)), user_aad(2))


def test_tampered_or_short_blob_fails():
    key = load_token_key(KEY)
    blob = bytearray(seal(key, b"secret", user_aad(1)))
    blob[-1] ^= 1
    for bad in (bytes(blob), b"short"):
        with pytest.raises(DecryptError):
            open_(key, bad, user_aad(1))


@pytest.mark.parametrize("raw", ["", "not base64!", base64.b64encode(b"k" * 16).decode()])
def test_key_must_be_32_bytes(raw):
    with pytest.raises(TokenKeyError, match="TOKEN_KEY"):
        load_token_key(raw)
```
Append to `tests/test_auth.py`:
```python
def test_startup_refuses_missing_or_bad_token_key(settings):
    for bad in ("", "short"):
        with pytest.raises(RuntimeError, match="TOKEN_KEY"):
            create_app(settings.model_copy(update={"token_key": bad}))
```
In `tests/conftest.py`, `AUTH_TEST` gains `token_key=base64.b64encode(b"t" * 32).decode()` (`import base64` at the top).

- [ ] **Step 2: Run and watch them fail.** `FORCE_COLOR= uv run pytest --color=no -p no:warnings tests/test_crypto.py tests/test_auth.py` → ImportError (`jobseeker.crypto`).

- [ ] **Step 3: Implement** (`src/jobseeker/crypto.py`):

```python
"""Secrets at rest (Gmail tokens): AES-256-GCM under TOKEN_KEY, bound to the owning user through the AAD."""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE = 12


class TokenKeyError(ValueError):
    pass


class DecryptError(ValueError):
    pass


def load_token_key(b64: str) -> bytes:
    try:
        key = base64.b64decode(b64 or "", validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != 32:
        raise TokenKeyError("TOKEN_KEY must be 32 random bytes, base64 (run `jobseeker gen-key`)")
    return key


def user_aad(user_id: int) -> bytes:
    return b"user:%d" % user_id


def seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def open_(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < NONCE + 16:
        raise DecryptError("token is damaged")
    try:
        return AESGCM(key).decrypt(blob[:NONCE], blob[NONCE:], aad)
    except InvalidTag as e:
        raise DecryptError("token doesn't decrypt for this user (key rotated or row moved)") from e
```
`src/jobseeker/config.py`, `Settings`: add `token_key: str = ""` next to `secret_key`.
`src/jobseeker/web/app.py`, in `create_app`, after the `SECRET_KEY` length check:
```python
    from jobseeker.crypto import TokenKeyError, load_token_key
    try:
        token_key = load_token_key(settings.token_key)
    except TokenKeyError as e:
        raise RuntimeError(str(e)) from e
```
and, after `app.state.settings = settings`: `app.state.token_key = token_key`.

- [ ] **Step 4: Run the suites.** pytest is green (every web test now carries `token_key` through `AUTH_TEST`); node 19.

- [ ] **Step 5: Commit** (with the HANDOFF update; push):
```bash
git add src/jobseeker/crypto.py src/jobseeker/config.py src/jobseeker/web/app.py tests/conftest.py tests/test_crypto.py tests/test_auth.py HANDOFF-backend.md
git commit -m "feat(crypto): AES-GCM token sealing under TOKEN_KEY, bound to the user; startup check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin multi-user
```

---

### Task 2: Migration v5 and `User.outreach_enabled`

**Files:**
- Modify: `src/jobseeker/db/migrations.py` (`V5_DDL`, `migrate_v5`, register v5), `src/jobseeker/db/schema.sql` (fresh-DB equivalents), `src/jobseeker/db/core.py` (`_seed_fresh` sets the owner's `outreach_enabled = 1`)
- Modify: `src/jobseeker/db/users.py` (`User.outreach_enabled`; `_user`; `set_outreach`; `outreach_user_count`; `resolve_sign_in` unchanged: new users default to 0)
- Test: `tests/test_migrations.py` (append), `tests/test_users.py` (append)

**Interfaces:**
- Produces:
  - `User(id, email, name, is_admin, google_sub, outreach_enabled: bool = False)`. The new field goes **last and defaulted**, so every existing `User(...)` positional call keeps working;
  - `set_outreach(conn, user_id: int, enabled: bool) -> None` (turning it off also deletes `gmail_tokens`);
  - `outreach_user_count(conn) -> int` (`max(1, …)` is applied by the caller);
  - tables `people_searches`, `gmail_tokens`, `app_state`; columns `users.outreach_enabled`, `contacts.owner_user_id`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_migrations.py`:

```python
def test_v5_splits_contacts_and_enables_owner(tmp_path):
    import shutil
    db = live_like_v0(tmp_path / "db.sqlite")
    prof = tmp_path / "profile"
    prof.mkdir()
    shutil.copy("tests/fixtures/preferences.yaml", prof / "preferences.yaml")
    shutil.copy("tests/fixtures/facts.json", prof / "facts.json")
    raw = sqlite3.connect(db)
    raw.execute("INSERT INTO contacts (company, name, source) VALUES ('Acme', 'Finder Person', 'finder')")
    raw.execute("INSERT INTO contacts (company, name, source) VALUES ('Acme', 'Manual Person', 'manual')")
    raw.commit()
    raw.close()
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk")
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] >= 5
    assert c.execute("SELECT outreach_enabled FROM users WHERE id = 1").fetchone()[0] == 1
    owners = dict(c.execute("SELECT name, owner_user_id FROM contacts WHERE company = 'Acme'").fetchall())
    assert owners == {"Finder Person": None, "Manual Person": 1}
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    for t in ("people_searches", "gmail_tokens", "app_state"):
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = ?", (t,)).fetchone()[0] == 1
    assert m.migrate(db, _ctx(tmp_path), tmp_path / "bk")[0].startswith("Already at")


def test_v5_keeps_every_application_contact_link(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk")
    c = sqlite3.connect(db)
    assert c.execute("""SELECT COUNT(*) FROM application_contacts ac
                        LEFT JOIN contacts c ON c.id = ac.contact_id WHERE c.id IS NULL""").fetchone()[0] == 0
```
(`test_fresh_schema_matches_migrated_v0` already compares a fresh DB with a migrated v0, so it guards `schema.sql` == v5.)

Append to `tests/test_users.py`:
```python
def test_outreach_flag_roundtrip_and_count(settings):
    from jobseeker.db.core import connect
    from jobseeker.db.users import outreach_user_count, set_outreach, user_by_id
    conn = connect(settings.db_path)
    assert user_by_id(conn, 1).outreach_enabled is True and outreach_user_count(conn) == 1
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    set_outreach(conn, 2, True)
    assert user_by_id(conn, 2).outreach_enabled and outreach_user_count(conn) == 2
    conn.execute("UPDATE users SET disabled_at = 't' WHERE id = 2")
    assert outreach_user_count(conn) == 1  # disabled users hold no share
```

- [ ] **Step 2: Run and watch them fail** (`no such column: outreach_enabled` / ImportError).

- [ ] **Step 3: Implement.** `V5_DDL` in `migrations.py`:

```python
V5_DDL = """
ALTER TABLE users ADD COLUMN outreach_enabled INTEGER NOT NULL DEFAULT 0;
UPDATE users SET outreach_enabled = 1 WHERE id = 1;
ALTER TABLE contacts ADD COLUMN owner_user_id INTEGER REFERENCES users (id);
UPDATE contacts SET owner_user_id = 1 WHERE source = 'manual';
CREATE INDEX idx_contacts_owner ON contacts (owner_user_id);
CREATE TABLE people_searches (
  company_norm TEXT NOT NULL,
  query TEXT NOT NULL,
  provider TEXT NOT NULL,
  results TEXT NOT NULL,
  searched_at TEXT NOT NULL,
  PRIMARY KEY (company_norm, query, provider)
);
CREATE TABLE gmail_tokens (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  account_email TEXT NOT NULL,
  token_enc BLOB NOT NULL,
  status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'expired')),
  connected_at TEXT NOT NULL,
  refreshed_at TEXT
);
CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, checked_at TEXT NOT NULL);
"""


def migrate_v5(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    """Per-user outreach: the switch, private vs shared contacts, the people-search cache, Gmail tokens."""
    before = conn.execute("SELECT COUNT(*) FROM application_contacts").fetchone()[0]
    for stmt in V5_DDL.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    dangling = conn.execute("""SELECT COUNT(*) FROM application_contacts ac LEFT JOIN contacts c ON c.id = ac.contact_id
                               WHERE c.id IS NULL""").fetchone()[0]
    if dangling or conn.execute("SELECT COUNT(*) FROM application_contacts").fetchone()[0] != before:
        raise MigrationError("v5: an application_contacts row lost its contact")


MIGRATIONS.append(Migration(5, "per-user outreach", migrate_v5))
```
`schema.sql`:
- `users` gains `outreach_enabled INTEGER NOT NULL DEFAULT 0`;
- `contacts` gains `owner_user_id INTEGER REFERENCES users (id)` and `CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts (owner_user_id);`;
- the three new tables with `IF NOT EXISTS`.

Put each column **at the end** of its table so the shape matches `ALTER TABLE … ADD COLUMN`. `core._seed_fresh`'s owner insert adds `outreach_enabled` = 1.

`db/users.py`:
```python
@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    is_admin: bool
    google_sub: str | None
    outreach_enabled: bool = False


def _user(row) -> User:
    return User(row["id"], row["email"], row["name"], bool(row["is_admin"]), row["google_sub"],
                bool(row["outreach_enabled"]))


def set_outreach(conn: sqlite3.Connection, user_id: int, enabled: bool) -> None:
    conn.execute("UPDATE users SET outreach_enabled = ? WHERE id = ?", (int(enabled), user_id))
    if not enabled:  # drafts and history stay (hidden by the gate); the Gmail grant goes
        conn.execute("DELETE FROM gmail_tokens WHERE user_id = ?", (user_id,))
    conn.commit()


def outreach_user_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE outreach_enabled = 1 AND disabled_at IS NULL").fetchone()[0]
```

- [ ] **Step 4: Run the suites** (all green; node 19). Then on a `.backup` copy of the live DB plus the owner's `profile/` (scratchpad): `jobseeker migrate` → "Applied v5", `foreign_key_check` is `[]`, and the 15 finder / 1 manual split holds.

- [ ] **Step 5: Commit + HANDOFF + push** — `feat(db): migration v5 — outreach switch, owner-scoped contacts, people-search cache, gmail_tokens`.

---

### Task 3: The `require_outreach` gate, the outreach router and the admin toggle

**Files:**
- Create: `src/jobseeker/web/outreach.py` (moves `draft_now`, `edit_draft`, `approve` + `_approve`/`_approve_single`/`_raw_for`, `contact`, `followed_up` out of `web/application.py`; `REGENERATABLE` moves with them)
- Modify: `src/jobseeker/web/deps.py` (`require_outreach` replaces `require_owner`; `render()` sets `can_outreach = user.outreach_enabled`)
- Modify: `src/jobseeker/web/contacts.py` (drop every per-route `dependencies=[Depends(require_owner)]`; the whole router is gated in `app.py`; `card` GET is gated too, per spec §4.2)
- Modify: `src/jobseeker/web/app.py` (include `outreach.router` and `contacts.router` with `[Depends(require_onboarded), Depends(owned_app), Depends(require_outreach)]`)
- Modify: `src/jobseeker/web/admin.py` + `templates/admin.html` (the toggle, the checklist flash, the "Outreach: on/off" column)
- Modify: `src/jobseeker/web/templates/pipeline.html` (hide the `drafted`, `approved` and `sent` columns and the outreach stats when `not can_outreach`)
- Modify: `tests/test_web_guards.py` (`OUTREACH` walk → `require_outreach`; the roommate tests keep passing), `tests/test_admin.py` (append)

**Interfaces:**
- Consumes: `User.outreach_enabled`, `set_outreach` (Task 2).
- Produces: `require_outreach(user=Depends(require_onboarded)) -> User`; `outreach.router` (prefix `/applications`); `POST /admin/users/{user_id}/outreach` (form `enabled=1|0`). `_raw_for(state, prefs, user_id, to, name, email, extra="")` now lives in `jobseeker.web.outreach`, and `web/contacts.py` imports it from there.

- [ ] **Step 1: Write the failing tests.** In `tests/test_web_guards.py`, replace the `require_owner` import and assertion in `test_outreach_routes_are_owner_only` with `require_outreach`, rename it `test_outreach_routes_require_outreach`, and widen `_outreach` so it also matches the `card` GET:

```python
def _outreach(r):
    return any((m, r.path) in OUTREACH for m in r.methods) or "/contacts/" in r.path or r.path.startswith("/gmail")


def test_outreach_routes_require_outreach(settings):
    from jobseeker.web.deps import require_outreach
    gated = [r for r in _api_routes(create_app(settings)) if _outreach(r)]
    assert len(gated) >= 12
    for r in gated:
        assert require_outreach in set(_calls(r.dependant)), f"{r.path} has no require_outreach"


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
```
Append to `tests/test_admin.py`:
```python
def test_admin_outreach_toggle(seeded_two, client_as, settings):
    from jobseeker.db.users import user_by_id
    owner = client_as(1, follow_redirects=False)
    r = owner.post("/admin/users/2/outreach", data={"enabled": "1"})
    assert r.status_code == 303 and "test%20user" in r.headers["location"].replace("+", "%20")
    assert user_by_id(connect(settings.db_path), 2).outreach_enabled
    assert "Outreach: on" in client_as(1).get("/admin").text
    owner.post("/admin/users/2/outreach", data={"enabled": "0"})
    assert not user_by_id(connect(settings.db_path), 2).outreach_enabled
    assert client_as(2, follow_redirects=False).post("/admin/users/2/outreach", data={"enabled": "1"}).status_code == 404


def test_pipeline_hides_outreach_columns_for_matching_only(seeded_two, client_as):
    html = client_as(2).get("/pipeline").text
    assert "No drafts waiting." not in html and "No Gmail drafts waiting to send." not in html
    assert "Drafted (30d)" not in html
```

- [ ] **Step 2: Run and watch them fail** (`ImportError: require_outreach`; 404 for the roommate's card; the admin route 404s).

- [ ] **Step 3: Implement.**

`web/deps.py` (replacing `require_owner`):
```python
def require_outreach(user: User = Depends(require_onboarded)) -> User:
    """Outreach (contacts, drafts, Gmail) is a per-user switch; off means the routes don't exist (404)."""
    if not user.outreach_enabled:
        raise HTTPException(404)
    return user
```
`require_onboarded` already depends on `current_user`. In `render()`: `ctx["can_outreach"] = user.outreach_enabled`. Delete `require_owner` and the now-unused `OWNER_ID` import if nothing else uses it.

`web/outreach.py`:
- `router = APIRouter(prefix="/applications")`;
- move the five routes and their helpers verbatim from `web/application.py`, minus the per-route `dependencies=[Depends(require_owner)]`;
- `draft_now` imports `draft_application` from `jobseeker.pipeline.draft`;
- `web/application.py` keeps `detail`, `set_status`, `snooze_route`, `notes`, `undo`, `not_interested` and `_back`. Remove its outreach-only imports, and keep `_back` importable from `web.application` (outreach and contacts use it).

In `web/contacts.py`, the two `from jobseeker.web.application import _raw_for` lines become `from jobseeker.web.outreach import _raw_for`.

`web/app.py`:
```python
    gate = [Depends(require_onboarded), Depends(owned_app), Depends(require_outreach)]
    app.include_router(application.router, dependencies=[Depends(require_onboarded), Depends(owned_app)])
    app.include_router(outreach.router, dependencies=gate)
    app.include_router(contacts.router, dependencies=gate)
```

`web/admin.py`:
```python
@router.post("/users/{user_id}/outreach")
def outreach(user_id: int, enabled: str = Form("0"), conn=Depends(get_conn)):
    target = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        return _back(err="No such user")
    on = enabled == "1"
    set_outreach(conn, user_id, on)
    if not on:
        return _back(msg="Outreach off. Their Gmail grant was removed; drafts and history stay hidden")
    return _back(msg=f"Outreach on. 1. Add {target['email']} as a test user in Google Cloud → OAuth consent screen. "
                     "2. Ask them to open Settings → Connect Gmail")
```
`admin.html`, users table: a column `Outreach: on|off` plus a form button `Turn outreach on/off` posting `enabled=1|0`.

`pipeline.html`: when `not can_outreach`, use `active = ["shortlisted", "replied", "interview", "offer"]`, skip the `drafted`/`approved`/`sent` columns, and hide the "Drafted (30d)"/"Sent"/"Reply rate" stat tiles.

- [ ] **Step 4: Run the suites.** The `can_outreach` tests from plan 2 (`test_roommate_job_page_has_no_outreach_markup…`, `test_roommate_today_has_no_outreach_tiles`, `test_owner_*`) still pass unchanged. Node 19.

- [ ] **Step 5: Commit + HANDOFF (§3: "`require_owner` replaced by `require_outreach`; `can_outreach` now reads `users.outreach_enabled`") + push** — `feat(outreach): per-user switch — require_outreach router, admin toggle, matching-only pipeline`.

---

### Task 4: Owner-scoped contacts, copy-on-write edits and private "not interested"

**Files:**
- Modify: `src/jobseeker/db/contacts_repo.py` (`upsert_contact` matches only shared rows; `edit_contact` (new): copy-on-write; `bounced_emails` unchanged, since bounces are shared facts)
- Modify: `src/jobseeker/db/applications.py` (`save_contact` always writes a private row)
- Modify: `src/jobseeker/web/contacts.py` (`edit` calls `edit_contact`)
- Test: `tests/test_contacts_private.py` (new)

**Interfaces:**
- Produces:
  - `upsert_contact(conn, user_id, company, name, role, linkedin_url, email, email_status, domain=None) -> int | None`: the same signature, but it never adopts a row with `owner_user_id IS NOT NULL`;
  - `edit_contact(conn, user_id, app_id, rank, name, email, email_status) -> int`, which returns the contact id now linked at that rank;
  - `save_contact(...)`: the same signature; it inserts or updates the **user's own** private row (matching on that user's private rows by email, then by LinkedIn URL).

- [ ] **Step 1: Write the failing tests** (`tests/test_contacts_private.py`):

```python
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
```

- [ ] **Step 2: Run and watch them fail** (ImportError: `edit_contact`; then the shared row is overwritten).

- [ ] **Step 3: Implement.**

`upsert_contact`: both `SELECT`s add `AND owner_user_id IS NULL`, and the `INSERT` writes `owner_user_id` NULL (shared). The block check (`blocklist … AND user_id = ?`) is unchanged; it's already per user.

`edit_contact` (in `contacts_repo.py`):
```python
def edit_contact(conn: sqlite3.Connection, user_id: int, app_id: int, rank: int, name: str, email: str,
                 email_status: str) -> int:
    """A user's edit never changes another user's view: shared rows are copied on write, except a bounce,
    which is a fact about the address and is recorded on the shared row for everyone."""
    row = conn.execute("""SELECT c.* FROM application_contacts ac JOIN contacts c ON c.id = ac.contact_id
                          WHERE ac.application_id = ? AND ac.rank = ?""", (app_id, rank)).fetchone()
    if row is None:
        raise LookupError("no contact at that rank")
    name, email = name.strip(), email.strip()
    bounce_only = (row["owner_user_id"] is None and name == row["name"] and email.lower() == (row["email"] or "").lower()
                   and email_status == "bounced")
    if row["owner_user_id"] == user_id or bounce_only:
        cid = row["id"]
        conn.execute("UPDATE contacts SET name = ?, email = ?, email_status = ? WHERE id = ?",
                     (name, email, email_status, cid))
    else:
        cid = conn.execute(
            """INSERT INTO contacts (company, name, role, linkedin_url, email, email_status, source, owner_user_id)
               VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)""",
            (row["company"], name, row["role"], row["linkedin_url"], email, email_status, user_id)).lastrowid
        conn.execute("UPDATE application_contacts SET contact_id = ? WHERE application_id = ? AND rank = ?",
                     (cid, app_id, rank))
        conn.execute("UPDATE applications SET contact_id = ? WHERE id = ? AND contact_id = ?", (cid, app_id, row["id"]))
    conn.execute("UPDATE application_contacts SET email_source = 'manual' WHERE application_id = ? AND rank = ?",
                 (app_id, rank))
    conn.commit()
    return cid
```
`web/contacts.py` `edit`: after the status check, `edit_contact(conn, user.id, app_id, rank, name, email, email_status)` (add `user=Depends(current_user)`), with `LookupError` → 404.

`save_contact` (`db/applications.py`): match `existing` only among `owner_user_id = user_id` rows (by email, then LinkedIn URL); the `INSERT` sets `source='manual', owner_user_id=user_id`. The blocklist check stays (per user).

- [ ] **Step 4: Run the suites.** `tests/test_contacts_finder.py`, `tests/test_web_contacts.py` and `tests/test_web_contacts_outreach.py` stay green (the finder writes shared rows, as before). Node 19.

- [ ] **Step 5: Commit + HANDOFF + push** — `feat(contacts): owner-scoped contacts — copy-on-write edits, shared bounces, private rows never adopted`.

---

### Task 5: People-search cache (30 days) and outreach budget shares

**Files:**
- Modify: `src/jobseeker/db/contacts_repo.py` (`cached_search`, `store_search`)
- Modify: `src/jobseeker/contacts/finder.py` (`_search` and the Apify people search go through the cache; `Budget` from `outreach_limits`; the share/global note wording)
- Modify: `src/jobseeker/db/usage.py` (`outreach_limits`; `Budget.summary` shows "Your … · All …"; a `scope(service)` helper for notes)
- Modify: `src/jobseeker/web/contacts.py` (`card_context` uses `outreach_limits`), `src/jobseeker/web/app.py` (`_contacts_deps` passes `global_drafts_per_day`)
- Test: `tests/test_people_cache.py` (new), `tests/test_usage.py` (append)

**Interfaces:**
- Consumes: `outreach_user_count` (Task 2).
- Produces:
  - `SEARCH_TTL = timedelta(days=30)`; `cached_search(conn, company, query, provider, now) -> list[dict] | None`; `store_search(conn, company, query, provider, results, now)`;
  - `outreach_limits(conn, contacts: ContactsConfig, global_drafts_per_day: int) -> dict[str, Limit]` (keys `tavily`, `apify`, `hunter`, `smtp`, `draft`);
  - `Budget.exhausted_note(service, label) -> str` ("Your Tavily share is used for October" / "Shared Tavily budget used for October");
  - `Deps.global_drafts_per_day: int = 20`.

- [ ] **Step 1: Write the failing tests.** `tests/test_usage.py`, appended:

```python
def test_outreach_limits_split_among_outreach_users(settings):
    from jobseeker.config import ContactsConfig
    from jobseeker.db.core import connect
    from jobseeker.db.usage import outreach_limits
    from jobseeker.db.users import set_outreach
    conn, cfg = connect(settings.db_path), ContactsConfig()
    assert outreach_limits(conn, cfg, 20)["tavily"].share_cap == cfg.tavily_monthly_limit       # owner alone: all
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    assert outreach_limits(conn, cfg, 20)["tavily"].share_cap == cfg.tavily_monthly_limit       # matching-only: no share
    set_outreach(conn, 2, True)
    lim = outreach_limits(conn, cfg, 20)
    assert lim["tavily"].share_cap == cfg.tavily_monthly_limit // 2 and lim["draft"].share_cap == 10
    assert lim["apify"].share_cap == round(cfg.apify_monthly_usd_limit / 2, 2)
    assert lim["tavily"].global_cap == cfg.tavily_monthly_limit


def test_summary_shows_mine_and_all(settings):
    from datetime import UTC, datetime

    from jobseeker.config import ContactsConfig
    from jobseeker.db.core import connect
    from jobseeker.db.usage import Budget, outreach_limits
    conn = connect(settings.db_path)
    Budget(conn, 1, outreach_limits(conn, ContactsConfig(), 20), datetime.now(UTC)).spend("tavily", 3)
    s = Budget(conn, 1, outreach_limits(conn, ContactsConfig(), 20), datetime.now(UTC)).summary()
    assert s.startswith("Your Tavily 3/950 · All 3/950")
```
`tests/test_people_cache.py`:
```python
from datetime import timedelta

from jobseeker.db.contacts_repo import cached_search, store_search
from jobseeker.db.core import connect
from tests.test_contacts_finder import NOW  # the finder tests' fixed clock


def test_cache_hit_within_30_days_then_miss(settings):
    conn = connect(settings.db_path)
    store_search(conn, "Acme Pvt Ltd", "q", "tavily", [{"url": "u"}], NOW)
    assert cached_search(conn, "acme", "q", "tavily", NOW + timedelta(days=29)) == [{"url": "u"}]
    assert cached_search(conn, "acme", "q", "tavily", NOW + timedelta(days=31)) is None
    assert cached_search(conn, "acme", "other", "tavily", NOW) is None
```
And the end-to-end checks, appended to `tests/test_contacts_finder.py` (they use that file's `setup_app`, `deps`, `FakeSMTP`, `FakeTavily` and `NOW`):
```python
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
```
(Add `ensure_application`/`get_application` to that file's imports if they aren't there yet.)

- [ ] **Step 2: Run and watch them fail** (ImportError: `outreach_limits`, `cached_search`).

- [ ] **Step 3: Implement.**

`db/usage.py`:
```python
def outreach_limits(conn: sqlite3.Connection, cfg: ContactsConfig, global_drafts_per_day: int) -> dict[str, Limit]:
    """Each outreach user's share of the free tiers; matching-only users hold none (no pooling)."""
    from jobseeker.db.users import outreach_user_count
    n = max(1, outreach_user_count(conn))
    return {"tavily": Limit("month", cfg.tavily_monthly_limit, cfg.tavily_monthly_limit // n),
            "apify": Limit("month", cfg.apify_monthly_usd_limit, round(cfg.apify_monthly_usd_limit / n, 2)),
            "hunter": Limit("month", cfg.hunter_monthly_limit, cfg.hunter_monthly_limit // n),
            "smtp": Limit("day", cfg.smtp_daily_limit, cfg.smtp_daily_limit // n),
            "draft": Limit("day", global_drafts_per_day, global_drafts_per_day // n)}
```
Keep `contacts_limits` for callers outside outreach (none should remain after this task: `grep -rn contacts_limits src`). `Budget.summary`:
```python
    def summary(self) -> str:
        lim = self.limits

        def part(label, svc, money=False):
            f = (lambda v: f"${v:.2f}") if money else (lambda v: f"{v:.0f}")
            return (f"{label} {f(self.used(svc))}/{f(lim[svc].share_cap)} · "
                    f"All {f(self.used_all(svc))}/{f(lim[svc].global_cap)}")
        return " · ".join(["Your " + part("Tavily", "tavily"), part("Apify", "apify", True), part("Hunter", "hunter"),
                           part("SMTP today", "smtp")])

    def exhausted_note(self, service: str, label: str) -> str:
        period = datetime.strptime(self.month, "%Y-%m").strftime("%B") if self.limits[service].period == "month" \
            else "today"
        mine = self.used(service) >= self.limits[service].share_cap - 1e-9
        return f"Your {label} share is used for {period}" if mine else f"Shared {label} budget used for {period}"
```
(Add `from datetime import datetime` if it isn't imported.)

`contacts_repo.py`:
```python
SEARCH_TTL = timedelta(days=30)


def cached_search(conn, company: str, query: str, provider: str, now: datetime) -> list[dict] | None:
    row = conn.execute("""SELECT results FROM people_searches WHERE company_norm = ? AND query = ? AND provider = ?
                          AND searched_at >= ?""",
                       (normalize_company(company), query, provider, iso(now - SEARCH_TTL))).fetchone()
    return json.loads(row["results"]) if row else None


def store_search(conn, company: str, query: str, provider: str, results: list[dict], now: datetime) -> None:
    conn.execute("""INSERT INTO people_searches (company_norm, query, provider, results, searched_at)
                    VALUES (?, ?, ?, ?, ?) ON CONFLICT (company_norm, query, provider) DO UPDATE
                    SET results = excluded.results, searched_at = excluded.searched_at""",
                 (normalize_company(company), query, provider, json.dumps(results), iso(now)))
    conn.commit()
```
(`import json` at the top.)

`finder.py`:
- `_search(deps, conn, company, budget, notes, query, **kw)`:
  - a hit on `cached_search(conn, company, f"{query}|{sorted(kw.items())}", "tavily", deps.now())` returns without spending;
  - a miss checks `budget.can("tavily")` (else `notes.append(budget.exhausted_note("tavily", "Tavily"))`), spends, calls the provider, then `store_search`s.
- The Apify people search does the same under provider `"apify"`, keyed `f"{role words}|{location_city}"`. Results are stored as `[c.__dict__ …]`: they're `Candidate`-like dataclasses, so rebuild them with the same class on a hit (check `contacts/people.py` for the class name and fields).
- `budget = Budget(conn, user_id, outreach_limits(conn, prefs.contacts, deps.global_drafts_per_day), app_now(deps.now()))`.
- Every `f"… budget used for {budget.month}"` note becomes `budget.exhausted_note(service, Label)`.

`web/contacts.py` `card_context`: `Budget(conn, request.state.user.id, outreach_limits(conn, prefs.contacts, request.app.state.app_config.budgets.global_drafts_per_day), app_now())`.

`web/app.py` `_contacts_deps`: `Deps(..., global_drafts_per_day=app_config.budgets.global_drafts_per_day)`. Pass `app_config` in from `create_app`.

- [ ] **Step 4: Run the suites** (green; node 19). Update existing finder tests whose note text was "Tavily budget used for …" to the new wording.

- [ ] **Step 5: Commit + HANDOFF + push** — `feat(contacts): 30-day people-search cache and per-user outreach shares`.

---

### Task 6: Draft units and drafting eligibility

**Files:**
- Modify: `src/jobseeker/pipeline/draft.py` (`drafts_enabled` returns `user.outreach_enabled`; `draft_round_robin` takes each drafter's `Budget` from `outreach_limits`)
- Modify: `src/jobseeker/contacts/finder.py` (people ranking and `pick_domain` each spend 1 `draft` unit, and are skipped with the note when out)
- Modify: `src/jobseeker/web/outreach.py` (`draft_now` checks and spends 1 `draft` unit)
- Test: `tests/test_draft_round_robin.py` (append), `tests/test_contacts_finder.py` (append)

**Interfaces:**
- Consumes: `outreach_limits` (Task 5), `User.outreach_enabled` (Task 2), and pipeline Task 11's `Drafter`, `draft_round_robin(conn, drafters, llm, cfg, now, heartbeat)` and `apps_needing_drafts`.
- Produces: `drafts_enabled(user) -> bool` (now `user.outreach_enabled`).

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_draft_round_robin.py` (reuse that file's helpers for seeding shortlisted, scored applications; look at its first test for the names):

```python
def test_drafts_enabled_follows_the_switch():
    from jobseeker.db.users import User
    from jobseeker.pipeline.draft import drafts_enabled
    assert drafts_enabled(User(2, "r@x", "R", False, None, True))
    assert not drafts_enabled(User(1, "o@x", "O", True, None, False))   # admin alone no longer implies drafts


def test_draft_share_counts_outreach_users_only(settings):
    from jobseeker.config import ContactsConfig
    from jobseeker.db.core import connect
    from jobseeker.db.usage import outreach_limits
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")  # matching-only
    assert outreach_limits(conn, ContactsConfig(), 20)["draft"].share_cap == 20
```
Plus one end-to-end: with two outreach users and `global_drafts_per_day = 4`, a run drafts at most 2 per user, best score first. Build it from the file's existing round-robin test, swapping the eligibility to `set_outreach(conn, 2, True)`.

Append to `tests/test_contacts_finder.py`: a find with the user's `draft` share already used (`Budget(...).spend("draft", share)`) makes **no** ranking LLM call (an LLM fake that fails if called) and raises `FinderError` with "Your drafting share is used for today".

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement.**

`pipeline/draft.py`:
```python
def drafts_enabled(user) -> bool:
    return bool(user.outreach_enabled)
```
In `draft_round_robin`, replace the `share`/`Budget` lines with:
```python
    from jobseeker.db.usage import outreach_limits
    limits = outreach_limits(conn, cfg.contacts, b.global_drafts_per_day)
    for d in drafters:
        d.budget = Budget(conn, d.user_id, limits, app_now(now))
        d.room = min(b.draft_per_run, max(0, int(limits["draft"].share_cap - d.budget.used("draft"))))
```
`finder.py`, before `rank(...)`:
```python
    if not budget.can("draft"):
        raise FinderError(budget.exhausted_note("draft", "drafting").replace("used for today", "used for today"))
    budget.spend("draft")
```
Before `pick_domain(...)`: when `budget.can("draft")` is false, skip the guess and add the note; otherwise `budget.spend("draft")`.

`web/outreach.py` `draft_now`:
- build `Budget(conn, user.id, outreach_limits(conn, prefs.contacts, app_config.budgets.global_drafts_per_day), app_now())`;
- `if not budget.can("draft"): return _back(app_id, err=budget.exhausted_note("draft", "drafting"))`;
- spend after a successful `draft_application`.

- [ ] **Step 4: Run the suites** (green; node 19).

- [ ] **Step 5: Commit + HANDOFF + push** — `feat(outreach): drafting follows users.outreach_enabled; ranking, domain picks and drafts share the draft budget`.

---

### Task 7: The SMTP verification switch

**Files:**
- Modify: `src/jobseeker/config.py` (`ContactsConfig.smtp_verify: Literal["off", "on", "auto"] = "off"`); `config/app.example.yaml` (`contacts: {…, smtp_verify: "off"}`)
- Create: `src/jobseeker/contacts/smtp_probe.py`
- Modify: `src/jobseeker/contacts/finder.py` (step 3 behind the switch; the server wording); `src/jobseeker/db/contacts_repo.py:37` (the stale wording)
- Test: `tests/test_smtp_switch.py` (new)

**Interfaces:**
- Produces: `PROBE_TTL = timedelta(hours=24)`; `port25_open(conn, now, probe: Callable[[], bool] = _probe) -> bool`; `Deps.port25: Callable[[sqlite3.Connection, datetime], bool] = port25_open`.

- [ ] **Step 1: Write the failing tests** (`tests/test_smtp_switch.py`):

```python
from datetime import UTC, datetime, timedelta

from jobseeker.contacts.smtp_probe import port25_open
from jobseeker.db.core import connect

T = datetime(2026, 10, 9, tzinfo=UTC)


def test_probe_result_is_remembered_for_24h(settings):
    conn, calls = connect(settings.db_path), []
    probe = lambda: calls.append(1) or False
    assert port25_open(conn, T, probe) is False
    assert port25_open(conn, T + timedelta(hours=23), probe) is False and calls == [1]
    assert port25_open(conn, T + timedelta(hours=25), lambda: True) is True


def _mode(prefs, mode):
    return prefs.model_copy(update={"contacts": prefs.contacts.model_copy(update={"smtp_verify": mode})})


def _no_smtp(host):
    raise AssertionError("SMTP must not be used when verification is off")


SERVER_NOTE = "Email checks aren't available on this server; emails are best guesses unless Apify or Hunter found them."


def test_off_never_builds_a_verifier(prefs):
    from jobseeker.contacts.finder import find_contacts
    from jobseeker.db.contacts_repo import people
    from tests.test_contacts_finder import deps, setup_app
    conn, app = setup_app()
    d, _ = deps(smtp_factory=_no_smtp)
    summary = find_contacts(conn, app, _mode(prefs, "off"), d)
    ps = people(conn, app)
    assert SERVER_NOTE in summary["notes"]
    assert ps[0]["email"] == "asha.rao@zeptonow.com" and {p["email_status"] for p in ps} == {"unverified"}


def test_auto_with_port_25_blocked_behaves_as_off(prefs):
    from jobseeker.contacts.finder import find_contacts
    from tests.test_contacts_finder import deps, setup_app
    conn, app = setup_app()
    d, _ = deps(smtp_factory=_no_smtp, port25=lambda c, n: False)
    assert SERVER_NOTE in find_contacts(conn, app, _mode(prefs, "auto"), d)["notes"]


def test_on_is_unchanged(prefs):
    from jobseeker.contacts.finder import find_contacts
    from tests.test_contacts_finder import FakeSMTP, deps, setup_app
    conn, app = setup_app()
    d, _ = deps(FakeSMTP({"asha.rao@zeptonow.com": 250, "vikram.singh@zeptonow.com": 250,
                          "rahul.sharma@zeptonow.com": 250, "priya.nair@zeptonow.com": 250}))
    assert find_contacts(conn, app, _mode(prefs, "on"), d)["verified"] == 3
```

- [ ] **Step 2: Run and watch them fail** (ImportError).

- [ ] **Step 3: Implement** (`src/jobseeker/contacts/smtp_probe.py`):

```python
"""Is outbound port 25 usable from this server? Asked at most once a day (Oracle and most clouds block it)."""
from __future__ import annotations

import socket
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from jobseeker.db.core import iso

PROBE_TTL = timedelta(hours=24)
PROBE_HOST = "gmail-smtp-in.l.google.com"


def _probe() -> bool:
    try:
        with socket.create_connection((PROBE_HOST, 25), timeout=5):
            return True
    except OSError:
        return False


def port25_open(conn: sqlite3.Connection, now: datetime, probe: Callable[[], bool] = _probe) -> bool:
    row = conn.execute("SELECT value, checked_at FROM app_state WHERE key = 'smtp25'").fetchone()
    if row and row["checked_at"] >= iso(now - PROBE_TTL):
        return row["value"] == "open"
    is_open = probe()
    conn.execute("""INSERT INTO app_state (key, value, checked_at) VALUES ('smtp25', ?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value, checked_at = excluded.checked_at""",
                 ("open" if is_open else "blocked", iso(now)))
    conn.commit()
    return is_open
```
`finder.py`, step 3: wrap the `SmtpVerifier` block in
```python
    mode = prefs.contacts.smtp_verify
    smtp_ok = mode == "on" or (mode == "auto" and deps.port25(conn, deps.now()))
    if domain and mx and not smtp_ok:
        notes.append("Email checks aren't available on this server; emails are best guesses unless Apify or Hunter "
                     "found them.")
        save_domain(conn, norm, domain=domain, mx_host=mx, catch_all=catch_all, pattern=hints[0] if hints else None)
    elif domain and mx:
        ...  # today's SMTP block, unchanged
```
In the existing `except PortBlocked` branch, the note becomes the same server wording. `contacts_repo.find_state`'s stale note becomes "Finding contacts timed out. Try again."

`Deps` gains `port25: Callable = port25_open` (imported from `smtp_probe`).

- [ ] **Step 4: Run the suites.** `tests/test_contacts_smtp.py` and the existing finder tests must pass. **Any finder test that expects SMTP-verified results now sets `smtp_verify="on"`** on its prefs (`prefs.model_copy(update={"contacts": prefs.contacts.model_copy(update={"smtp_verify": "on"})})`), because the default is `off`. Node 19.

- [ ] **Step 5: Commit + HANDOFF + push** — `feat(contacts): smtp_verify off|on|auto (default off) with a daily port-25 probe`.

---

### Task 8: Per-user Gmail: connect, callback, encrypted tokens, reconnect

**Files:**
- Create: `src/jobseeker/db/gmail_tokens.py`, `src/jobseeker/web/gmail.py`
- Modify: `src/jobseeker/gmail/client.py` (`load_service(conn, user_id, key)`; `GmailUnavailable(msg, reconnect=False)`; `create_draft` 401/403 → `reconnect=True`; delete `authorize` and the `InstalledAppFlow` import)
- Modify: `src/jobseeker/web/auth.py` (`exchange_code(settings, code, verifier, redirect_path="/auth/callback") -> dict`, which returns the token JSON; the sign-in caller takes `["id_token"]`)
- Modify: `src/jobseeker/web/app.py` (`gmail_factory(conn, user_id)`; include `gmail.router` with `require_outreach`; `PUBLIC` is unchanged)
- Modify: `src/jobseeker/web/outreach.py` and `web/contacts.py` (call `gmail_factory(conn, user.id)`; a `GmailUnavailable` with `reconnect` → `_back(app_id, err="Gmail needs reconnecting", reconnect=True)`)
- Modify: `src/jobseeker/web/application.py` (`_back(..., reconnect=False)` adds `&reconnect=1`), `web/deps.py` (`render()` sets `reconnect_url` when `?reconnect=1`), `templates/base.html` (a Reconnect Gmail button in the err flash)
- Modify: `src/jobseeker/web/settings.py` + `templates/settings.html` (the Gmail card when `can_outreach`)
- Modify: `src/jobseeker/cli.py` (delete `auth-gmail`; `init` no longer creates `secrets/`), `src/jobseeker/config.py` (delete `Settings.secrets_dir`)
- Modify tests: `tests/test_gmail.py` (rewrite around the DB token), `tests/test_web_application.py` + `tests/test_web_contacts_outreach.py` (`gmail_factory=lambda conn, uid: gmail`)
- Test: `tests/test_gmail_connect.py` (new)

**Interfaces:**
- Consumes: `seal`/`open_`/`user_aad`/`DecryptError` (Task 1); `require_outreach` (Task 3); `oauth.sign/unsign/pkce_pair/auth_url/local_path` (plan 2).
- Produces:
  - `GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.compose"`; `GMAIL_COOKIE = "__Host-js_gmail_oauth"`;
  - `save_token(conn, key, user_id, account_email, creds_json: str, now)`, `load_token(conn, key, user_id) -> str` (raises `GmailUnavailable(reconnect=True)`), `mark_expired(conn, user_id)`, `delete_token(conn, user_id)`, `token_info(conn, user_id) -> dict | None` (`account_email`, `status`, `connected_at`; never the blob);
  - `load_service(conn, user_id, key)`;
  - `app.state.gmail_factory: Callable[[conn, int], service]`.

- [ ] **Step 1: Write the failing tests** (`tests/test_gmail_connect.py`):

```python
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from jobseeker.crypto import user_aad
from jobseeker.db.core import connect
from jobseeker.db.gmail_tokens import load_token, save_token, token_info
from jobseeker.gmail.client import GmailUnavailable, load_service
from jobseeker.web import auth, oauth

T = datetime(2026, 10, 9, tzinfo=UTC)
CREDS = json.dumps({"token": "at", "refresh_token": "rt", "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": "cid", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/gmail.compose"]})


def _connect(web, next_="/applications/1"):
    r = web.get(f"/gmail/connect?next={next_}")
    assert r.status_code == 303
    return parse_qs(urlsplit(r.headers["location"]).query)


def test_connect_redirect_asks_for_compose_offline_with_login_hint(client_as):
    q = _connect(client_as(1, follow_redirects=False))
    assert q["scope"] == ["openid email https://www.googleapis.com/auth/gmail.compose"]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["login_hint"] == ["owner@example.com"]
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"][0].endswith("/gmail/callback")


def test_sign_in_never_asks_for_gmail(client_as, anon_client):
    loc = anon_client().get("/login").headers["location"]
    assert "gmail" not in parse_qs(urlsplit(loc).query)["scope"][0]


def test_callback_stores_sealed_token_for_the_account_google_returned(client_as, settings, monkeypatch):
    web = client_as(1, follow_redirects=False)
    q = _connect(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": q["nonce"][0], "email": "other@gmail.com",
                                                                    "email_verified": True, "sub": "g"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={
            "id_token": "x", "access_token": "at", "refresh_token": "rt", "expires_in": 3600}))
        r = web.get(f"/gmail/callback?code=c&state={q['state'][0]}")
    assert r.status_code == 303 and r.headers["location"].startswith("/applications/1")
    conn = connect(settings.db_path)
    assert token_info(conn, 1)["account_email"] == "other@gmail.com"      # drafts go where Google said
    blob = conn.execute("SELECT token_enc FROM gmail_tokens WHERE user_id = 1").fetchone()[0]
    assert b"rt" not in blob
    assert json.loads(load_token(conn, web.app.state.token_key, 1))["refresh_token"] == "rt"


def test_callback_without_refresh_token_is_refused(client_as, settings, monkeypatch):
    web = client_as(1, follow_redirects=False)
    q = _connect(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": q["nonce"][0], "email": "o@gmail.com",
                                                                    "email_verified": True, "sub": "g"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x", "access_token": "at"}))
        r = web.get(f"/gmail/callback?code=c&state={q['state'][0]}")
    assert "Google didn't grant offline access" in r.text and token_info(connect(settings.db_path), 1) is None


def test_row_moved_to_another_user_needs_reconnect(settings, client_as):
    key = client_as(1).app.state.token_key
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    save_token(conn, key, 1, "o@gmail.com", CREDS, T)
    blob = conn.execute("SELECT token_enc FROM gmail_tokens WHERE user_id = 1").fetchone()[0]
    conn.execute("INSERT INTO gmail_tokens (user_id, account_email, token_enc, connected_at) VALUES (2, 'x', ?, 't')",
                 (blob,))
    with pytest.raises(GmailUnavailable) as e:
        load_service(conn, 2, key)
    assert e.value.reconnect and token_info(conn, 2)["status"] == "expired"


def test_refresh_writes_back_and_invalid_grant_expires(settings, client_as, monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    key = client_as(1).app.state.token_key
    conn = connect(settings.db_path)
    save_token(conn, key, 1, "o@gmail.com", CREDS, T)
    before = conn.execute("SELECT token_enc FROM gmail_tokens WHERE user_id = 1").fetchone()[0]
    monkeypatch.setattr(Credentials, "valid", property(lambda self: self.token == "fresh"))
    monkeypatch.setattr(Credentials, "refresh", lambda self, req: setattr(self, "token", "fresh"))
    load_service(conn, 1, key)
    after = conn.execute("SELECT token_enc, refreshed_at FROM gmail_tokens WHERE user_id = 1").fetchone()
    assert after[0] != before and after[1]
    monkeypatch.setattr(Credentials, "valid", property(lambda self: False))

    def bad(self, req):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(Credentials, "refresh", bad)
    with pytest.raises(GmailUnavailable) as e:
        load_service(conn, 1, key)
    assert e.value.reconnect and token_info(conn, 1)["status"] == "expired"


def test_approve_with_expired_token_offers_reconnect_to_the_same_job(seeded, client_as, settings):
    from jobseeker.db.applications import save_draft
    conn = connect(settings.db_path)
    save_draft(conn, seeded[0], "email", "S", "B")
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id = ?", (seeded[0],))
    conn.commit()

    def expired(c, uid):
        raise GmailUnavailable("Gmail needs reconnecting", reconnect=True)
    web = client_as(1, gmail_factory=expired, follow_redirects=False)
    r = web.post(f"/applications/{seeded[0]}/approve", data={"confirm_unverified": "true"})
    page = web.get(r.headers["location"]).text
    assert f'/gmail/connect?next=/applications/{seeded[0]}' in page and "Reconnect Gmail" in page


def test_auth_gmail_command_is_gone():
    from typer.testing import CliRunner

    from jobseeker.cli import app
    assert CliRunner().invoke(app, ["auth-gmail"]).exit_code != 0
```
(The approve test needs a contact with an email. Copy the contact setup from `tests/test_web_application.py`'s `ctx` fixture, which saves a contact before approving.)

Also rewrite `tests/test_gmail.py`'s `load_service(tmp_path…)` tests as `load_service(conn, 1, key)` with no row → `GmailUnavailable(reconnect=True)`. Keep the `create_draft`, MIME and scope tests. Add: `create_draft` with an `HttpError` 401 raises `GmailUnavailable` with `reconnect=True`.

- [ ] **Step 2: Run and watch them fail** (404 on `/gmail/connect`; ImportError).

- [ ] **Step 3: Implement.**

`gmail/client.py`:
```python
class GmailUnavailable(RuntimeError):
    def __init__(self, message: str, reconnect: bool = False):
        super().__init__(message)
        self.reconnect = reconnect


def load_service(conn, user_id: int, key: bytes):
    from jobseeker.db.gmail_tokens import load_token, mark_expired, save_token, token_info

    info = json.loads(load_token(conn, key, user_id))  # raises GmailUnavailable(reconnect=True)
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            mark_expired(conn, user_id)
            raise GmailUnavailable("Gmail needs reconnecting", reconnect=True) from e
        except TransportError as e:
            raise GmailUnavailable(f"Couldn't reach Gmail ({e}). Check the internet and try again.") from e
        save_token(conn, key, user_id, token_info(conn, user_id)["account_email"], creds.to_json(), datetime.now(UTC),
                   refreshed=True)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
```
In `create_draft`, the 401/403 branch raises `GmailUnavailable("Gmail needs reconnecting", reconnect=True)`. The callers mark the token expired: `except GmailUnavailable as e: if e.reconnect: mark_expired(conn, user.id)`.

`db/gmail_tokens.py`:
```python
from __future__ import annotations

import sqlite3
from datetime import datetime

from jobseeker.crypto import DecryptError, open_, seal, user_aad
from jobseeker.db.core import iso


def save_token(conn: sqlite3.Connection, key: bytes, user_id: int, account_email: str, creds_json: str,
               now: datetime, refreshed: bool = False) -> None:
    blob = seal(key, creds_json.encode(), user_aad(user_id))
    if refreshed:
        conn.execute("UPDATE gmail_tokens SET token_enc = ?, status = 'ok', refreshed_at = ? WHERE user_id = ?",
                     (blob, iso(now), user_id))
    else:
        conn.execute("""INSERT INTO gmail_tokens (user_id, account_email, token_enc, status, connected_at, refreshed_at)
                        VALUES (?, ?, ?, 'ok', ?, ?) ON CONFLICT (user_id) DO UPDATE SET
                        account_email = excluded.account_email, token_enc = excluded.token_enc, status = 'ok',
                        connected_at = excluded.connected_at, refreshed_at = excluded.refreshed_at""",
                     (user_id, account_email, blob, iso(now), iso(now)))
    conn.commit()


def load_token(conn: sqlite3.Connection, key: bytes, user_id: int) -> str:
    from jobseeker.gmail.client import GmailUnavailable
    row = conn.execute("SELECT token_enc, status FROM gmail_tokens WHERE user_id = ?", (user_id,)).fetchone()
    if row is None or row["status"] == "expired":
        raise GmailUnavailable("Gmail needs reconnecting", reconnect=True)
    try:
        return open_(key, row["token_enc"], user_aad(user_id)).decode()
    except DecryptError as e:
        import logging
        logging.getLogger(__name__).warning("gmail token for user %s doesn't decrypt: %s", user_id, e)
        mark_expired(conn, user_id)
        raise GmailUnavailable("Gmail needs reconnecting", reconnect=True) from e


def mark_expired(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("UPDATE gmail_tokens SET status = 'expired' WHERE user_id = ?", (user_id,))
    conn.commit()


def delete_token(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM gmail_tokens WHERE user_id = ?", (user_id,))
    conn.commit()


def token_info(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT account_email, status, connected_at, refreshed_at FROM gmail_tokens WHERE user_id = ?",
                       (user_id,)).fetchone()
    return dict(row) if row else None
```
(`set_outreach` from Task 2 already deletes the row. It can call `delete_token` instead, which is equivalent.)

`web/auth.py`: `exchange_code(settings, code, verifier, redirect_path="/auth/callback") -> dict` returns `r.json()`. The sign-in callback uses `exchange_code(...)["id_token"]`, wrapped in the same `KeyError` handling it has today.

`web/gmail.py`:
```python
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from jobseeker.db.gmail_tokens import save_token
from jobseeker.web import auth
from jobseeker.web.deps import get_conn, require_outreach
from jobseeker.web.oauth import BadSignature, auth_url, local_path, pkce_pair, sign, unsign

router = APIRouter(prefix="/gmail")
GMAIL_COOKIE = "__Host-js_gmail_oauth"
SCOPE = "openid email https://www.googleapis.com/auth/gmail.compose"


@router.get("/connect")
def connect(request: Request, next: str = "", user=Depends(require_outreach)):
    s, now = request.app.state.settings, datetime.now(UTC)
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    url = auth_url(s.google_client_id, f"{s.base_url}/gmail/callback", state, nonce, challenge, scope=SCOPE,
                   access_type="offline", prompt="consent", include_granted_scopes="false", login_hint=user.email)
    resp = RedirectResponse(url, 303)
    payload = {"state": state, "nonce": nonce, "verifier": verifier, "next": local_path(next) or "/settings",
               "uid": user.id}
    resp.set_cookie(GMAIL_COOKIE, sign(payload, s.secret_key, now, timedelta(minutes=10)), max_age=600, path="/",
                    secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp


def _fail(request, message: str):
    resp = request.app.state.templates.TemplateResponse(
        request, "auth_message.html", {"message": message, "retry": "/gmail/connect"}, status_code=400)
    return resp


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", user=Depends(require_outreach),
             conn=Depends(get_conn)):
    s, now = request.app.state.settings, datetime.now(UTC)
    try:
        data = unsign(request.cookies.get(GMAIL_COOKIE, ""), s.secret_key, now)
    except BadSignature:
        data = {}
    if error or not state or not secrets.compare_digest(state, data.get("state", "")) or data.get("uid") != user.id:
        resp = _fail(request, "Gmail connection expired. Try again")
    else:
        try:
            tokens = auth.exchange_code(s, code, data["verifier"], redirect_path="/gmail/callback")
            claims = auth.verify_id_token(tokens["id_token"], s.google_client_id)
        except (httpx.HTTPError, KeyError, ValueError):
            resp = _fail(request, "Couldn't reach Google, try again.")
        else:
            if claims.get("nonce") != data.get("nonce"):
                resp = _fail(request, "Gmail connection couldn't be verified. Try again")
            elif not tokens.get("refresh_token"):
                resp = _fail(request, "Google didn't grant offline access. Try again")
            else:
                from google.oauth2.credentials import Credentials
                creds = Credentials(tokens["access_token"], refresh_token=tokens["refresh_token"],
                                    token_uri="https://oauth2.googleapis.com/token", client_id=s.google_client_id,
                                    client_secret=s.google_client_secret,
                                    scopes=["https://www.googleapis.com/auth/gmail.compose"])
                email = claims.get("email", "")
                save_token(conn, request.app.state.token_key, user.id, email, creds.to_json(), now)
                msg = quote(f"Gmail connected: drafts go to {email}")
                nxt = data["next"]
                resp = RedirectResponse(f"{nxt}{'&' if '?' in nxt else '?'}msg={msg}", 303)
    resp.delete_cookie(GMAIL_COOKIE, path="/", secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp
```
`templates/auth_message.html`: the "Try again" link uses `{{ retry or "/login" }}`.

`web/app.py`:
```python
    app.state.gmail_factory = gmail_factory or (lambda conn, uid: load_service(conn, uid, app.state.token_key))
    app.include_router(gmail.router, dependencies=[Depends(require_outreach)])
```
Callers: `state.gmail_factory()` becomes `state.gmail_factory(conn, user.id)` in `web/outreach.py` (`_approve` and `_approve_single`) and in `web/contacts.py` (`email_third`, `follow_up`). On `GmailUnavailable` with `e.reconnect`, call `mark_expired(conn, user.id)` and `return _back(app_id, err="Gmail needs reconnecting", reconnect=True)`. Partial success keeps today's named-drafts message plus `reconnect=True`.

`web/application.py` `_back(app_id, next_=None, *, msg=None, err=None, reconnect=False)` appends `&reconnect=1` when `reconnect`. `render()` sets `ctx["reconnect_url"] = f"/gmail/connect?next={request.url.path}"` when `request.query_params.get("reconnect") == "1"`. `base.html`, inside the err flash: `{% if reconnect_url %} <a class="btn btn-primary" href="{{ reconnect_url }}" hx-boost="false">Reconnect Gmail</a>{% endif %}`.

Settings Gmail card (`settings.html`, Account section, `{% if can_outreach %}`):
- "Drafts go to {{ gmail.account_email }} · connected {{ gmail.connected_at|age }}" plus a Reconnect link, or "Not connected" plus a **Connect Gmail** link (`/gmail/connect?next=/settings`);
- when not connected, the note: "Google will warn that this app isn't verified. It's {{ owner_first }}'s personal app: tap Advanced → Continue." `owner_first` comes from `owner_first_name(conn)`;
- when `gmail.status == "expired"`: "Gmail needs reconnecting".

`page()` passes `gmail=token_info(conn, user.id)` and `owner_first=owner_first_name(conn)`.

CLI: delete the `auth-gmail` command. In `init`, drop `settings.secrets_dir` from the mkdir list. In `config.py`, delete the `secrets_dir` property, then `grep -rn secrets_dir src tests` must be empty.

- [ ] **Step 4: Run the suites** (green; node 19). `grep -rn "InstalledAppFlow\|authorize(\|token.json\|auth-gmail" src` must be empty.

- [ ] **Step 5: Commit + HANDOFF (§3: the owner taps Connect Gmail once at cutover; each outreach user must be a Google test user) + push** — `feat(gmail): per-user Gmail connect with sealed tokens, refresh write-back and one-tap reconnect`.

---

### Task 9: Delete and export coverage; acceptance; handoff

**Files:**
- Modify: `src/jobseeker/db/account.py` (`user_scoped_tables` picks up `gmail_tokens` (user_id) and `contacts` (owner_user_id) automatically; check the delete order: private `contacts` go **after** `application_contacts` and the `applications.contact_id` repoint; `export_zip` adds `gmail.json`)
- Modify: `HANDOFF.md` ("Sub-project 5 built")
- Test: `tests/test_account.py` (append)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_account.py`):

```python
def test_delete_covers_gmail_tokens_and_private_contacts(seeded_two, settings):
    from datetime import UTC, datetime

    from jobseeker.crypto import load_token_key
    from jobseeker.db.applications import save_contact
    from jobseeker.db.gmail_tokens import save_token
    from tests.conftest import AUTH_TEST
    conn = connect(settings.db_path)
    key = load_token_key(AUTH_TEST["token_key"])
    save_token(conn, key, 2, "r@gmail.com", "{}", datetime.now(UTC))
    private = save_contact(conn, seeded_two["roommate_app"], name="P", role="", linkedin_url="", email="p@x.com",
                           email_status="unverified")
    shared_before = conn.execute("SELECT COUNT(*) FROM contacts WHERE owner_user_id IS NULL").fetchone()[0]
    delete_account(conn, settings.jobseeker_home, 2)
    assert conn.execute("SELECT COUNT(*) FROM gmail_tokens WHERE user_id = 2").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE id = ?", (private,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contacts WHERE owner_user_id IS NULL").fetchone()[0] == shared_before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_export_has_gmail_json_without_the_token(seeded, settings):
    from datetime import UTC, datetime

    from jobseeker.crypto import load_token_key
    from jobseeker.db.gmail_tokens import save_token
    from tests.conftest import AUTH_TEST
    conn = connect(settings.db_path)
    save_token(conn, load_token_key(AUTH_TEST["token_key"]), 1, "o@gmail.com", '{"refresh_token": "rt"}',
               datetime.now(UTC))
    z = zipfile.ZipFile(io.BytesIO(export_zip(conn, settings.jobseeker_home, 1)))
    gmail = json.loads(z.read("gmail.json"))
    assert gmail == {"account_email": "o@gmail.com", "connected_at": gmail["connected_at"]}
    assert all(b"rt" not in z.read(n) and b"token_enc" not in z.read(n) for n in z.namelist() if n != "resume.pdf")
```

- [ ] **Step 2: Run and watch them fail** (no `gmail.json`; possibly an FK failure when deleting a private contact still referenced by `applications.contact_id`).

- [ ] **Step 3: Implement.**
- In `delete_account`, after the `application_id` group and before `applications`:
  - `UPDATE applications SET contact_id = NULL WHERE user_id = ?`;
  - delete the `owner_user_id` rows;
  - because `user_scoped_tables` returns `("contacts", "owner_user_id")` once v5 adds the column, keep it in the second loop. That's already ordered after the `application_id` deletes; add the `contact_id = NULL` update before that loop.
- `export_zip`: `z.writestr("gmail.json", json.dumps({"account_email": …, "connected_at": …}))` when `token_info(conn, user_id)` exists.

- [ ] **Step 4: Acceptance** (manual, scratchpad only; never the main checkout):
1. A `.backup` copy of the live DB plus the owner's `profile/`; `jobseeker migrate` → v5 applied; FK check `[]`; the contact split is 15 shared / 1 private; every `application_contacts` link resolves.
2. Serve on `127.0.0.1:8010` with throwaway env (including `TOKEN_KEY` from `jobseeker gen-key`); a 390×844 browser (agent-browser) as the owner:
   - the job page still shows People/Draft and Approve;
   - Settings shows "Not connected · Connect Gmail" and the unverified-app note;
   - an Approve with no token shows the **Reconnect Gmail** button pointing at `/gmail/connect?next=/applications/<id>`.

   Real Google consent is checked at deploy, because it needs the Web client and test users.
3. As a matching-only roommate (created and signed in by script): every outreach URL returns 404, and the job page shows "Open job posting ↗" and "Mark applied".
4. Full suites green; node 19.

- [ ] **Step 5: `HANDOFF.md`** "Sub-project 5 built":
- `TOKEN_KEY` (`jobseeker gen-key`) in `.env`, separate from `BACKUP_KEY`;
- add `BASE_URL/gmail/callback` as a second redirect URI on the Web client;
- each outreach user is a Google **test user**;
- the owner taps Settings → Connect Gmail once after cutover (`token.json` isn't migrated);
- `contacts.smtp_verify: off` on the server;
- the admin toggle;
- the new test count.

Commit + HANDOFF-backend + push — `feat(account): delete/export cover Gmail tokens and private contacts; handoff for sub-project 5`. Then the final whole-branch review (one fresh reviewer, the most capable model, focused on this plan's Review Focus and on token handling).

---

## Spec coverage (self-review)

| Spec 5 section | Task |
|---|---|
| §3 decisions: consent, token storage, expiry, cutover, gate, contacts split, bounces, 30-day reuse, budgets, SMTP default, enabling drafts the shortlist | 1, 2, 3, 4, 5, 6, 7, 8 |
| §4.1 connect/callback, `seal`/`open_`, `load_service(conn, user_id)`, removals, `gmail_factory(conn, user_id)`, attachment, reconnect UX, Settings card, Testing mode note | 1, 8 (the attachment is already per-user via `_raw_for` → `resume_path`, plan 3) |
| §4.2 `require_outreach`, the outreach router, templates, drafting eligibility, admin toggle and checklist; off deletes the token | 3, 6, 2 (`set_outreach`) |
| §4.3 `people_searches`, dedup/adoption only of shared rows, per-user blocklist, edit copy-on-write and bounce rule, "Add someone myself" private, remove/replace unchanged | 4, 5 |
| §4.4 shares among outreach users, draft units for ranking/`pick_domain`/drafts, "Your … · All …", no pooling | 5, 6 |
| §4.5 `smtp_verify` off/on/auto, the probe memo, wording | 7 |
| §4.6 delete/export coverage | 9 |
| §5 migration v5 + post-checks | 2 |
| §6 errors | 1 (key), 8 (consent, refresh, decrypt, unreachable), 3 (404), 5 (share notes), 7 (port 25) |
| §7 testing | every task |
| §8 acceptance | 9 |

**Clarifications this plan adds** (for the coordinator):
1. **`User.outreach_enabled` goes last, with a default,** so pipeline Task 11's `User(1, "o@x", "O", True, None)` test literal and every other positional `User(...)` keep working. One consequence: `drafts_enabled(User(1, …, True, None))` becomes **False**, because the default is off. Pipeline T11's `test_drafts_enabled…` assertion is updated in Task 6, and the plan's own test replaces it.
2. **`can_outreach` stays the template variable name;** only its source changes (`user.outreach_enabled`). That keeps plan 2's templates and render tests untouched.
3. **The `card` GET is gated too** (spec §4.2 lists all of `contacts.py`). Plan 2 had left it open, so for an outreach-off user the job page no longer renders the People include at all. It was already hidden by `can_outreach`.
4. **`exchange_code` now returns the whole token response** (a dict), so the sign-in and Gmail flows share it. Sign-in takes `["id_token"]`.
5. **The finder's cache key includes the search kwargs** (`include_domains`, `max_results`), so a LinkedIn people search and a domain search with the same words never collide.
6. **Finder tests now default to `smtp_verify: off`.** Task 7 makes `off` the default, so every existing `tests/test_contacts_finder.py` test that expects SMTP-verified results switches its prefs to `on` (`_mode(prefs, "on")`). Tests about catch-all, refusal and port-blocked behaviour need `on` too.
