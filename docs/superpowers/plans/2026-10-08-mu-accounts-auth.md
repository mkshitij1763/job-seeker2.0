# Multi-user accounts, sign-in and data scoping: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Chosen method for this plan: Native (inline), via superpowers:executing-plans.**

**Goal:** Make the app invite-only and multi-user, with Google sign-in, where every per-user row carries `user_id`. The owner's existing data becomes user 1's, and the app keeps working exactly as today for that single user.

**Architecture:** An explicit, versioned `jobseeker migrate` (with `PRAGMA user_version`) rebuilds four tables with `user_id NOT NULL` and adds `users`/`invites`/`sessions`/`user_jobs`. Data functions take `user_id` explicitly. A hand-rolled OAuth code flow (PKCE + state + nonce, ID token verified by `google-auth`) creates DB-backed sessions. Router-level `current_user`/`owned_app` dependencies guard every route, enforced by a route-walk test. An Origin check middleware handles CSRF.

**Tech Stack:** Python 3.13, uv, FastAPI/Starlette, Jinja2 + HTMX, SQLite (WAL), httpx, `google-auth` (made direct), pytest + respx + pytest-socket.

**Spec:** `docs/superpowers/specs/2026-10-08-mu-accounts-auth-design.md` (read it alongside this plan). Research: `docs/superpowers/research/2026-10-08-multi-user-impact.md`.

## Global Constraints

- Test commands: `FORCE_COLOR= uv run pytest --color=no` (never `-q`: `addopts` already has it). Node: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`.
- **Every task ends with the full suite green:** pytest (≥ 400 passed, the count only grows) **and** 19 node tests.
- The app must keep working **single-user as user 1** after every task (`jobseeker serve` and `jobseeker run` work against a migrated DB).
- `user_id` is a **required** parameter on every per-user data function. No defaults, no context variables.
- Rebuilt tables use `user_id INTEGER NOT NULL REFERENCES users(id)` with **no DEFAULT**.
- Migration numbers: v1 is this plan. v2 is onboarding, v3 extras, v4 pipeline, v5 outreach (they register later).
- Env var names, exactly: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `BASE_URL`, `SECRET_KEY`, `OWNER_EMAIL`, `COOKIE_SECURE` (default `true`).
- Cookies: `__Host-js_session` (`Secure; HttpOnly; SameSite=Lax; Path=/`, 30 days) and `__Host-js_oauth` (10 minutes).
- Another user's application id → **404**. A non-admin on `/admin*` → **404**. A cross-site or header-less POST → **403** "Request blocked".
- **No hard-coded owner name** in any copy. Use `owner_first_name(conn)` (Task 6).
- No network in tests (`pytest-socket`). Google's endpoints are mocked with `respx`, and ID-token verification is monkeypatched.
- Commits: one per task on `multi-user`, staging only the task's files. End each message with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2
  ```
  Don't push.

## Execution setup (do this before Task 1; it needs the user's OK)

The live launchd agents (`com.kshitij.jobseeker.web`, which is running, and the 11:15 `com.kshitij.jobseeker`) run **from the main checkout** `/Users/user/Desktop/untitled folder/job-seeker2.0`, which is currently on `multi-user`. Once Task 3 lands there, the live app would refuse to start (`SchemaOutOfDate`), and the daily run would fail.

1. In the main checkout: `git switch main`. The live app keeps running today's code, and nothing changes for the user.
2. `git worktree add "../js-mu-backend" multi-user`, then do all the work in `/Users/user/Desktop/untitled folder/js-mu-backend`. That worktree has no `data/`, `.env` or `profile/` (all git-ignored), so the live DB is never touched.
3. `cd ../js-mu-backend && uv sync`, then run both suites once: expect 400 + 19 passed.

## Review Focus

1. **Existing live data:** `migrate` on a copy of the real DB (v0 shape, columns added by `NEW_COLUMNS` in a different order from `schema.sql`) must preserve every id and count. Tested in Task 2 against a DB built from `schema_v0.sql` plus `NEW_COLUMNS`-style `ALTER`s, with columns out of order.
2. **A fresh install or test DB:** with foreign keys on, `applications.user_id = 1` needs a `users` row. A fresh `connect()` must seed a placeholder owner (Task 3). Tested by inserting an application right after `connect()` on a new file.
3. **The same job for two users:** `ensure_application(conn, 2, J1)` must create a second row and never return user 1's (Task 3).
4. **A stale or forged cookie, or a session for a disabled user:** must behave as signed out (303 to `/login`), never as a 500 (Task 7).
5. **`next=` open redirects** (`//evil.com`, `https://evil.com`, `/\evil`): always fall back to `/` (Task 7).

---

## File structure

| File | Responsibility |
|---|---|
| `src/jobseeker/db/schema_v0.sql` (new) | frozen copy of today's `schema.sql`; used only for the v0 catch-up and the migration tests |
| `src/jobseeker/db/schema.sql` | the **latest** shape (post-v1 from Task 3) |
| `src/jobseeker/db/migrations.py` (new) | `Migration`, `MigrationContext`, `MIGRATIONS`, `latest()`, `migrate()`, `migrate_v1()` |
| `src/jobseeker/db/core.py` | `connect(path, *, check_version=True)`: fresh, v0 catch-up, version check, owner seed |
| `src/jobseeker/db/backup.py` | `snapshot(db_path, out)` extracted (used by `migrate` and `backup`) |
| `src/jobseeker/db/users.py` (new) | `OWNER_ID`, `User`, `ensure_owner`, `owner_first_name`, `resolve_sign_in`, invites, enable/disable |
| `src/jobseeker/db/sessions.py` (new) | `create_session`, `user_for_token`, `delete_session`, `delete_user_sessions`, `purge_expired` |
| `src/jobseeker/db/usage.py` | `Limit`, `contacts_limits`, `Budget(conn, user_id, limits, now)` |
| `src/jobseeker/db/{jobs,applications,queries,contacts_repo,runs}.py` | `user_id` threading |
| `src/jobseeker/web/oauth.py` (new) | pure helpers: `sign`/`unsign`, `pkce_pair`, `auth_url`, `local_path`, cookie names |
| `src/jobseeker/web/auth.py` (new) | `/login`, `/auth/callback`, `/logout`, `/logout/all`; `exchange_code`, `verify_id_token` |
| `src/jobseeker/web/deps.py` | `get_conn`, `optional_user`, `current_user`, `owned_app`, `require_admin`, `NotAuthenticated`, `render` |
| `src/jobseeker/web/csrf.py` (new) | `OriginCheck` ASGI middleware |
| `src/jobseeker/web/admin.py` (new) | `/admin` and its POST routes |
| `src/jobseeker/web/templates/{bare,auth_message,not_invited,admin}.html` (new) | sign-in pages and admin |
| `tests/test_migrations.py`, `test_users.py`, `test_auth.py`, `test_web_guards.py`, `test_csrf.py`, `test_admin.py`, `test_isolation.py` (new) | the new behaviour |

---

### Task 1: The migration framework and `jobseeker migrate`

**Files:**
- Create: `src/jobseeker/db/schema_v0.sql` (a byte-for-byte copy of today's `src/jobseeker/db/schema.sql`)
- Create: `src/jobseeker/db/migrations.py`
- Modify: `src/jobseeker/db/core.py:1-41`
- Modify: `src/jobseeker/db/backup.py:13-28` (extract `snapshot`)
- Modify: `src/jobseeker/cli.py` (add the `migrate` command)
- Modify: `tests/test_db_migration.py` (build v0 DBs explicitly)
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces:
  - `SchemaOutOfDate(RuntimeError)`, `DatabaseBusy(RuntimeError)`, `MigrationError(RuntimeError)`;
  - `Migration(version: int, name: str, apply: Callable[[sqlite3.Connection, MigrationContext], None])`;
  - `MigrationContext(owner_email: str, now: datetime, home: Path)`;
  - `MIGRATIONS: list[Migration]`, `latest(migrations=None) -> int`, `table_counts(conn) -> dict[str, int]`;
  - `migrate(db_path: Path, ctx: MigrationContext, backup_dir: Path, *, migrations=None, dry_run=False) -> list[str]` (report lines);
  - `connect(path, *, check_version=True)`;
  - `snapshot(db_path: Path, out: Path) -> Path`.

  devops-lead's nightly backup should reuse `snapshot` (tell the coordinator).

- [ ] **Step 1: Freeze the v0 schema**

```bash
cp src/jobseeker/db/schema.sql src/jobseeker/db/schema_v0.sql
```

- [ ] **Step 2: Write the failing tests** in `tests/test_migrations.py`:

```python
import sqlite3
from datetime import UTC, datetime

import pytest

from jobseeker.db import migrations as m
from jobseeker.db.core import SCHEMA_V0, connect

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def v0_db(path):
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA_V0)
    raw.commit()
    raw.close()
    return path


def _ctx(tmp_path):
    return m.MigrationContext(owner_email="owner@example.com", now=NOW, home=tmp_path)


def _add_flag(conn, ctx):
    conn.execute("CREATE TABLE flag (x INTEGER)")


def test_latest_of_empty_is_zero():
    assert m.latest([]) == 0


def test_migrate_applies_pending_in_order_and_sets_version(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    report = m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "flag", _add_flag)])
    raw = sqlite3.connect(db)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert raw.execute("SELECT name FROM sqlite_master WHERE name = 'flag'").fetchone()
    assert any("v1" in line for line in report)
    assert list((tmp_path / "bk").glob("pre-migrate-v0-*.db"))


def test_migrate_twice_is_a_noop(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    ms = [m.Migration(1, "flag", _add_flag)]
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=ms)
    assert m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=ms) == ["Already at v1"]


def test_failed_foreign_key_check_rolls_back(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")

    def orphan(conn, ctx):
        conn.execute("INSERT INTO drafts (application_id, kind, body, created_at) VALUES (999, 'email', 'x', 'now')")

    with pytest.raises(m.MigrationError):
        m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "orphan", orphan)])
    raw = sqlite3.connect(db)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    assert raw.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_dry_run_leaves_file_identical(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    before = db.read_bytes()
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "flag", _add_flag)], dry_run=True)
    assert db.read_bytes() == before


def test_busy_database_is_refused(tmp_path):
    db = v0_db(tmp_path / "db.sqlite")
    holder = sqlite3.connect(db)
    holder.execute("BEGIN IMMEDIATE")
    with pytest.raises(m.DatabaseBusy):
        m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "flag", _add_flag)], busy_timeout=0.1)
    holder.rollback()


def test_connect_on_old_version_raises_when_behind(tmp_path, monkeypatch):
    db = v0_db(tmp_path / "db.sqlite")
    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration(1, "flag", _add_flag)])
    with pytest.raises(m.SchemaOutOfDate, match="jobseeker migrate"):
        connect(db)
    connect(db, check_version=False).close()  # migrate itself opens without the check


def test_fresh_file_lands_at_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MIGRATIONS", [m.Migration(1, "flag", _add_flag)])
    conn = connect(tmp_path / "fresh.sqlite")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
```

- [ ] **Step 3: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_migrations.py`
Expected: FAIL (`ModuleNotFoundError: jobseeker.db.migrations` / `ImportError: SCHEMA_V0`).

- [ ] **Step 4: Implement**

`src/jobseeker/db/migrations.py`:
```python
"""Versioned schema migrations (PRAGMA user_version), run only by `jobseeker migrate`."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class SchemaOutOfDate(RuntimeError):
    pass


class DatabaseBusy(RuntimeError):
    pass


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationContext:
    owner_email: str
    now: datetime
    home: Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection, MigrationContext], None]


MIGRATIONS: list[Migration] = []  # v1 is registered in Task 3


def latest(migrations: list[Migration] | None = None) -> int:
    ms = MIGRATIONS if migrations is None else migrations
    return ms[-1].version if ms else 0


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def _version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(db_path: Path, ctx: MigrationContext, backup_dir: Path, *, migrations: list[Migration] | None = None,
            dry_run: bool = False, busy_timeout: float = 5.0) -> list[str]:
    from jobseeker.db.backup import snapshot
    from jobseeker.db.core import connect

    ms = MIGRATIONS if migrations is None else migrations
    db_path = Path(db_path)
    probe = sqlite3.connect(db_path, timeout=busy_timeout)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.rollback()
    except sqlite3.OperationalError as e:
        raise DatabaseBusy("Database is busy: stop jobseeker-web and the tick timer first") from e
    finally:
        probe.close()
    if dry_run:
        tmp = Path(tempfile.mkdtemp())
        work = tmp / db_path.name
        snapshot(db_path, work)
        try:
            return ["(dry run)"] + migrate(work, ctx, tmp / "bk", migrations=ms)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    conn = connect(db_path, check_version=False)
    try:
        start = _version(conn)
        pending = [x for x in ms if x.version > start]
        if not pending:
            return [f"Already at v{start}"]
        backup_dir.mkdir(parents=True, exist_ok=True)
        snapshot(db_path, backup_dir / f"pre-migrate-v{start}-{ctx.now:%Y%m%d-%H%M%S}.db")
        before = table_counts(conn)
        report = []
        for mig in pending:
            conn.commit()
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            try:
                mig.apply(conn, ctx)
                bad = conn.execute("PRAGMA foreign_key_check").fetchall()
                if bad:
                    raise MigrationError(f"v{mig.version}: foreign key check failed: {[tuple(r) for r in bad][:10]}")
                conn.execute(f"PRAGMA user_version = {mig.version}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
            report.append(f"Applied v{mig.version}: {mig.name}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("integrity_check failed after migrating")
        after = table_counts(conn)
        report += [f"  {t}: {before.get(t, '-')} -> {after.get(t, '-')}" for t in sorted(set(before) | set(after))]
        return report
    finally:
        conn.close()
```

`src/jobseeker/db/core.py`: replace lines 1-41 with:
```python
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jobseeker.db.migrations import SchemaOutOfDate, latest

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
SCHEMA_V0 = (Path(__file__).parent / "schema_v0.sql").read_text(encoding="utf-8")
# v0 only: tables/columns added after the MVP, so an old database reaches the exact shape migration 1 expects.
REQUIRED_TABLES = {"runs", "discovered_companies", "application_contacts", "contact_candidates",
                   "company_domains", "usage"}
NEW_COLUMNS = {
    "jobs": {"prescore": "INTEGER", "jd_attempts": "INTEGER NOT NULL DEFAULT 0"},
    "applications": {"find_status": "TEXT NOT NULL DEFAULT 'idle'", "find_error": "TEXT NOT NULL DEFAULT ''",
                     "find_started_at": "TEXT"},
    "company_domains": {"catch_all_at": "TEXT"},
    "application_contacts": {"nudged_at": "TEXT"},
}


def _catch_up_v0(conn: sqlite3.Connection, tables: set[str]) -> None:
    if not REQUIRED_TABLES <= tables:
        conn.executescript(SCHEMA_V0)  # every statement is IF NOT EXISTS
    changed = False
    for table, columns in NEW_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                changed = True
    if changed:
        conn.commit()


def connect(path: Path | str, *, check_version: bool = True) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    # Only touch the schema when something is missing, so a reader never needs a write lock while the daily run writes.
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not tables:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {latest()}")
        _seed_fresh(conn)
        conn.commit()
        return conn
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        _catch_up_v0(conn, tables)
    if check_version and version < latest():
        conn.close()
        raise SchemaOutOfDate(f"Database is at v{version}, the app needs v{latest()}. Run `jobseeker migrate`.")
    return conn


def _seed_fresh(conn: sqlite3.Connection) -> None:
    """Rows a brand-new database needs (Task 3 adds the placeholder owner)."""


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def utcnow() -> str:
    return iso(datetime.now(UTC))
```

`src/jobseeker/db/backup.py`: extract the snapshot. Replace lines 18-25 (the `with tempfile.TemporaryDirectory()` block's snapshot part) so that `backup()` calls the new function:
```python
def snapshot(db_path: Path, out: Path) -> Path:
    """A consistent copy of a live (WAL) database through SQLite's backup API."""
    out.parent.mkdir(parents=True, exist_ok=True)
    src, dst = sqlite3.connect(db_path), sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return out
```
Inside `backup()`, the line `src, dst = …` through `dst.close()` becomes `snapshot(db_path, Path(tmp) / "snapshot.db")`.

`src/jobseeker/cli.py`: add after `backup`:
```python
@app.command()
def migrate(dry_run: bool = typer.Option(False, "--dry-run", help="Migrate a copy and report; change nothing.")) -> None:
    """Upgrade the database schema (back up first; stop the web service and timer before running)."""
    from datetime import UTC, datetime

    from jobseeker.db.migrations import DatabaseBusy, MigrationContext, MigrationError
    from jobseeker.db.migrations import migrate as run_migrate

    settings = Settings()
    ctx = MigrationContext(owner_email=settings.owner_email, now=datetime.now(UTC), home=settings.jobseeker_home)
    try:
        for line in run_migrate(settings.db_path, ctx, settings.data_dir / "backups", dry_run=dry_run):
            typer.echo(line)
    except (DatabaseBusy, MigrationError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
```
`Settings` gains `owner_email: str = ""` (`src/jobseeker/config.py:15`, next to the API keys).

`tests/test_db_migration.py`: the two tests that build an "MVP-era" DB must start from v0. In `test_migrates_mvp_database`, replace `conn = connect(path)` (the first one) with:
```python
    raw = sqlite3.connect(path)
    raw.executescript(SCHEMA_V0)
    raw.close()
    conn = connect(path)
```
and add `from jobseeker.db.core import SCHEMA_V0`.

- [ ] **Step 5: Run the new tests, then the full suites**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_migrations.py tests/test_db_migration.py tests/test_backup.py`
Expected: PASS.
Run: `FORCE_COLOR= uv run pytest --color=no` → all pass (more than 400). Then `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs` → 19 pass.

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/db/schema_v0.sql src/jobseeker/db/migrations.py src/jobseeker/db/core.py src/jobseeker/db/backup.py \
        src/jobseeker/cli.py src/jobseeker/config.py tests/test_migrations.py tests/test_db_migration.py
git commit -m "feat(db): versioned migrations and jobseeker migrate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 2: Migration v1 as a function (not registered yet)

**Files:**
- Modify: `src/jobseeker/db/migrations.py` (add `V1_DDL`, `migrate_v1`)
- Test: `tests/test_migrations.py` (append)

**Interfaces:**
- Consumes: `MigrationContext`, `SCHEMA_V0` (Task 1).
- Produces: `migrate_v1(conn, ctx) -> None`, and the DDL constant `V1_DDL` (str). Task 3 registers it and copies the same DDL into `schema.sql`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_migrations.py`):

```python
from tests.factories import make_job


def live_like_v0(path):
    """v0 DB shaped like the live one: NEW_COLUMNS appended out of order, with data."""
    from jobseeker.db.core import NEW_COLUMNS
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    raw.executescript(SCHEMA_V0.replace("  find_status TEXT NOT NULL DEFAULT 'idle',\n  find_error TEXT NOT NULL DEFAULT '',\n"
                                        "  find_started_at TEXT,\n", ""))
    for col, ddl in NEW_COLUMNS["applications"].items():
        raw.execute(f"ALTER TABLE applications ADD COLUMN {col} {ddl}")
    raw.execute("INSERT INTO jobs (id, source, source_job_id, company, title, jd_hash, apply_url, fingerprint, "
                "first_seen_at, filter_reason, prescore) VALUES (1,'lever','a','CRED','PA','h1','u','f1','t',NULL,70),"
                "(2,'lever','b','CRED','SDE','h2','u','f2','t','title: sde',NULL)")
    raw.execute("INSERT INTO applications (id, job_id, status, created_at, updated_at) VALUES (7, 1, 'drafted', 't', 't')")
    raw.execute("INSERT INTO drafts (application_id, kind, body, created_at) VALUES (7, 'email', 'b', 't')")
    raw.execute("INSERT INTO events (application_id, at, type) VALUES (7, 't', 'status')")
    raw.execute("INSERT INTO scores (id, job_id, score, breakdown, matches, gaps, recommendation, role_family, model, "
                "rubric_version, jd_hash, created_at) VALUES (3, 1, 88, '{}', '[]', '[]', 'apply', 'pa', 'm', 'v1', 'h1', 't')")
    raw.execute("INSERT INTO usage (period, service, amount) VALUES ('2026-10', 'tavily', 5)")
    raw.execute("INSERT INTO runs (started_at) VALUES ('t')")
    raw.commit()
    raw.close()
    return path


def test_v1_preserves_ids_and_assigns_owner(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "users", m.migrate_v1)])
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    assert dict(c.execute("SELECT id, email, is_admin FROM users").fetchone()) == {"id": 1, "email": "owner@example.com", "is_admin": 1}
    assert c.execute("SELECT id, user_id, job_id, find_status FROM applications").fetchone()[:] == (7, 1, 1, "idle")
    assert c.execute("SELECT application_id FROM drafts").fetchone()[0] == 7
    assert c.execute("SELECT user_id FROM scores WHERE id = 3").fetchone()[0] == 1
    assert c.execute("SELECT user_id, period, service, amount FROM usage").fetchone()[:] == (1, "2026-10", "tavily", 5)
    assert c.execute("SELECT user_id, kind FROM runs").fetchone()[:] == (1, "legacy")
    uj = {r["job_id"]: dict(r) for r in c.execute("SELECT * FROM user_jobs")}
    assert uj[1]["prescore"] == 70 and uj[1]["jd_hash"] == "h1" and uj[2]["filter_reason"] == "title: sde"
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v1_constraints(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk", migrations=[m.Migration(1, "users", m.migrate_v1)])
    c = sqlite3.connect(db)
    c.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    c.execute("INSERT INTO applications (user_id, job_id, created_at, updated_at) VALUES (2, 1, 't', 't')")  # same job, other user
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO applications (user_id, job_id, created_at, updated_at) VALUES (1, 1, 't', 't')")
    for sql in ("INSERT INTO applications (job_id, created_at, updated_at) VALUES (2, 't', 't')",
                "INSERT INTO blocklist (company, at) VALUES ('x', 't')",
                "INSERT INTO usage (period, service, amount) VALUES ('d', 's', 1)"):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)


def test_v1_requires_owner_email(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    ctx = m.MigrationContext(owner_email="", now=NOW, home=tmp_path)
    with pytest.raises(m.MigrationError, match="OWNER_EMAIL"):
        m.migrate(db, ctx, tmp_path / "bk", migrations=[m.Migration(1, "users", m.migrate_v1)])
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 0
```

- [ ] **Step 2: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_migrations.py -k v1`
Expected: FAIL (`AttributeError: module 'jobseeker.db.migrations' has no attribute 'migrate_v1'`).

- [ ] **Step 3: Implement** (append to `src/jobseeker/db/migrations.py`):

```python
V1_DDL = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  google_sub TEXT UNIQUE,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  is_admin INTEGER NOT NULL DEFAULT 0,
  disabled_at TEXT,
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE TABLE invites (
  email TEXT PRIMARY KEY,
  invited_by INTEGER REFERENCES users (id),
  created_at TEXT NOT NULL,
  accepted_at TEXT
);
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions (user_id);
CREATE TABLE user_jobs (
  user_id INTEGER NOT NULL REFERENCES users (id),
  job_id INTEGER NOT NULL REFERENCES jobs (id),
  filter_reason TEXT,
  prescore INTEGER,
  jd_hash TEXT NOT NULL,
  evaluated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, job_id)
);
CREATE INDEX idx_user_jobs_open ON user_jobs (user_id, filter_reason);
"""

V1_REBUILT = {
    "applications": """CREATE TABLE applications_new (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id),
  job_id INTEGER NOT NULL REFERENCES jobs (id),
  contact_id INTEGER REFERENCES contacts (id),
  status TEXT NOT NULL DEFAULT 'new',
  snoozed_until TEXT,
  snoozed_from TEXT,
  applied_via_portal INTEGER NOT NULL DEFAULT 0,
  followups_sent INTEGER NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  suggested_contact_role TEXT NOT NULL DEFAULT '',
  suggested_contact_reason TEXT NOT NULL DEFAULT '',
  linkedin_search_url TEXT NOT NULL DEFAULT '',
  draft_warnings TEXT NOT NULL DEFAULT '[]',
  find_status TEXT NOT NULL DEFAULT 'idle',
  find_error TEXT NOT NULL DEFAULT '',
  find_started_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, job_id)
)""",
    "scores": """CREATE TABLE scores_new (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id),
  job_id INTEGER NOT NULL REFERENCES jobs (id),
  score INTEGER NOT NULL,
  breakdown TEXT NOT NULL,
  matches TEXT NOT NULL,
  gaps TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  role_family TEXT NOT NULL,
  model TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  jd_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
)""",
    "blocklist": """CREATE TABLE blocklist_new (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users (id),
  contact_id INTEGER REFERENCES contacts (id),
  company TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL
)""",
    "usage": """CREATE TABLE usage_new (
  user_id INTEGER NOT NULL REFERENCES users (id),
  period TEXT NOT NULL,
  service TEXT NOT NULL,
  amount REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, period, service)
)""",
}
V1_INDEXES = "CREATE INDEX idx_scores_user_job ON scores (user_id, job_id, id);"
V1_CHECKED = ("applications", "scores", "blocklist", "usage", "drafts", "events", "jobs")


def migrate_v1(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    if not ctx.owner_email.strip():
        raise MigrationError("Set OWNER_EMAIL in .env before migrating (v1 makes that account the owner)")
    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in V1_CHECKED}
    now = ctx.now.isoformat(timespec="seconds")
    for stmt in V1_DDL.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    conn.execute("INSERT INTO users (id, email, name, is_admin, created_at) VALUES (1, lower(?), '', 1, ?)",
                 (ctx.owner_email.strip(), now))
    conn.execute("""INSERT INTO user_jobs (user_id, job_id, filter_reason, prescore, jd_hash, evaluated_at)
                    SELECT 1, id, filter_reason, prescore, jd_hash, first_seen_at FROM jobs""")
    for table, ddl in V1_REBUILT.items():
        cols = ", ".join(r[1] for r in conn.execute(f"PRAGMA table_info({table})"))
        conn.execute(ddl)
        conn.execute(f"INSERT INTO {table}_new (user_id, {cols}) SELECT 1, {cols} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
    conn.execute(V1_INDEXES)
    conn.execute("ALTER TABLE runs ADD COLUMN user_id INTEGER REFERENCES users (id)")
    conn.execute("ALTER TABLE runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'legacy'")
    conn.execute("UPDATE runs SET user_id = 1")
    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in V1_CHECKED}
    if before != after:
        raise MigrationError(f"v1 row counts changed: {before} -> {after}")
    if conn.execute("SELECT COUNT(*) FROM user_jobs").fetchone()[0] != after["jobs"]:
        raise MigrationError("v1: user_jobs doesn't mirror jobs")
    if conn.execute("SELECT COUNT(*) FROM applications WHERE user_id != 1").fetchone()[0]:
        raise MigrationError("v1: an application isn't owned by user 1")
```
(The old `idx_scores_job` disappears with the dropped `scores` table, so it doesn't need dropping explicitly.)

- [ ] **Step 4: Run the tests, then the full suites**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_migrations.py` → PASS.
Run: `FORCE_COLOR= uv run pytest --color=no` (all pass) and the node suite (19).

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/db/migrations.py tests/test_migrations.py
git commit -m "feat(db): migration v1 (users, user_jobs, user-scoped rebuilds), not yet registered

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 3: Switch to the v1 schema; writers take `user_id`

This is the one task that changes the schema under the app. All writers to rebuilt tables, their callers and their tests change together. Afterwards, the app runs single-user as user 1.

**Files:**
- Modify: `src/jobseeker/db/schema.sql` (the post-v1 shape)
- Modify: `src/jobseeker/db/migrations.py` (register v1)
- Modify: `src/jobseeker/db/core.py` (`_seed_fresh` placeholder owner)
- Create: `src/jobseeker/db/users.py` (`OWNER_ID`, `ensure_owner`)
- Modify: `src/jobseeker/db/applications.py:31-38, 159-175` (`ensure_application`, `mark_not_interested`)
- Modify: `src/jobseeker/db/jobs.py:141-150` (`save_score`)
- Modify: `src/jobseeker/db/usage.py` (all of it)
- Modify: `src/jobseeker/pipeline/run.py` (`run_daily(..., user_id)` threaded to `ensure_application`/`save_score`)
- Modify: `src/jobseeker/contacts/finder.py:57-60` (user from the application)
- Modify: `src/jobseeker/web/contacts.py:26-34` (`card_context`)
- Modify: `src/jobseeker/web/app.py:42-67` (startup check plus `ensure_owner`)
- Modify: `src/jobseeker/cli.py` (`_run` passes `OWNER_ID`; `_load` runs `ensure_owner`)
- Modify tests: `tests/conftest.py:69,72`, `tests/test_db_applications.py:22,28,79`, `tests/test_contacts_finder.py:67,130`, `tests/test_refilter.py:26,28`, `tests/test_db_jobs.py:56,136`, `tests/test_contacts_setup.py:55,64`, `tests/test_run.py:46,122`, `tests/test_run_discovery.py:50`
- Test: `tests/test_migrations.py` (append), `tests/test_users.py` (new)

**Interfaces:**
- Consumes: `migrate_v1`, `V1_DDL`, `V1_REBUILT` (Task 2).
- Produces:
  - `OWNER_ID = 1`, `ensure_owner(conn, email: str) -> None`;
  - `ensure_application(conn, user_id: int, job_id: int, now=None) -> int`;
  - `save_score(conn, user_id: int, job_id: int, result, model, rubric_version, jd_hash_value) -> None`;
  - `Limit(period: Literal["day", "month"], global_cap: float, share_cap: float)`;
  - `contacts_limits(cfg: ContactsConfig) -> dict[str, Limit]`;
  - `Budget(conn, user_id: int, limits: dict[str, Limit], now)` with `.can`, `.spend`, `.used`, `.used_all`, `.summary`, `.month`, `.day`;
  - `run_daily(conn, *, user_id: int, ...)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrations.py`:
```python
def _table_shape(conn):
    shape = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        cols = sorted((r[1], r[2].upper(), r[3], r[4], r[5]) for r in conn.execute(f"PRAGMA table_info({name})"))
        fks = sorted((r[2], r[3], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({name})"))
        shape[name] = (cols, fks)
    return shape


def test_fresh_schema_matches_migrated_v0(tmp_path):
    fresh = connect(tmp_path / "fresh.sqlite")
    db = live_like_v0(tmp_path / "old.sqlite")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk")
    assert _table_shape(fresh) == _table_shape(connect(db))


def test_fresh_db_has_placeholder_owner_and_accepts_owner_rows(tmp_path):
    from jobseeker.db.applications import ensure_application
    from jobseeker.db.jobs import upsert_job
    conn = connect(tmp_path / "db.sqlite")
    assert conn.execute("SELECT id, email, is_admin FROM users").fetchone()[:] == (1, "", 1)
    job_id, _ = upsert_job(conn, make_job())
    assert ensure_application(conn, 1, job_id) > 0
```
New `tests/test_users.py`:
```python
from jobseeker.db.applications import ensure_application
from jobseeker.db.core import connect
from jobseeker.db.jobs import upsert_job
from jobseeker.db.users import OWNER_ID, ensure_owner
from tests.factories import make_job


def test_ensure_owner_sets_email_once(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    ensure_owner(conn, "Owner@Example.com")
    assert conn.execute("SELECT email FROM users WHERE id = 1").fetchone()[0] == "owner@example.com"
    conn.execute("UPDATE users SET google_sub = 'g1' WHERE id = 1")
    ensure_owner(conn, "other@example.com")  # an owner who has signed in keeps their identity
    assert conn.execute("SELECT email FROM users WHERE id = 1").fetchone()[0] == "owner@example.com"


def test_same_job_two_users_two_applications(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    job_id, _ = upsert_job(conn, make_job())
    a = ensure_application(conn, OWNER_ID, job_id)
    b = ensure_application(conn, 2, job_id)
    assert a != b
    assert ensure_application(conn, 2, job_id) == b
```
Append to `tests/test_contacts_setup.py` (the budget tests):
```python
def test_budget_share_and_global_caps(tmp_path):
    from jobseeker.db.usage import Budget, Limit
    conn = connect(tmp_path / "db.sqlite")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    limits = {"tavily": Limit("month", 3, 2)}
    a, b = Budget(conn, 1, limits, NOW), Budget(conn, 2, limits, NOW)
    a.spend("tavily"); a.spend("tavily")
    assert not a.can("tavily")          # user 1 is at their share
    assert b.can("tavily")
    b.spend("tavily")
    assert not b.can("tavily")          # the global cap (3) is reached
```

- [ ] **Step 2: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_migrations.py tests/test_users.py tests/test_contacts_setup.py`
Expected: FAIL (no `users` table in a fresh DB; `jobseeker.db.users` missing; `Limit` missing).

- [ ] **Step 3: Implement the schema switch**

`src/jobseeker/db/schema.sql`: replace the file with today's content, with these exact changes:
- the `scores`, `applications`, `blocklist` and `usage` `CREATE TABLE` statements are replaced by the bodies in `V1_REBUILT`, renamed from `<t>_new` to `<t>`, each prefixed `CREATE TABLE IF NOT EXISTS`. Keep the `applications` column order exactly as in `V1_REBUILT`;
- `CREATE INDEX IF NOT EXISTS idx_scores_job …` is replaced by `CREATE INDEX IF NOT EXISTS idx_scores_user_job ON scores (user_id, job_id, id);`;
- `runs` gains, **after** `errors`, the lines `user_id INTEGER REFERENCES users (id),` and `kind TEXT NOT NULL DEFAULT 'legacy'`;
- `V1_DDL`'s four tables and two indexes are added at the top, each with `IF NOT EXISTS`.

`src/jobseeker/db/migrations.py`, at the end: `MIGRATIONS.append(Migration(1, "users and scoping", migrate_v1))`.

`src/jobseeker/db/core.py`:
```python
def _seed_fresh(conn: sqlite3.Connection) -> None:
    """A new database starts with its owner (user 1). ensure_owner() fills the email from OWNER_EMAIL."""
    conn.execute("INSERT INTO users (id, email, name, is_admin, created_at) VALUES (1, '', '', 1, ?)", (utcnow(),))
```

`src/jobseeker/db/users.py`:
```python
from __future__ import annotations

import sqlite3

OWNER_ID = 1


def ensure_owner(conn: sqlite3.Connection, email: str) -> None:
    """Give user 1 the OWNER_EMAIL until they first sign in (after that, their Google identity is fixed)."""
    if email.strip():
        conn.execute("UPDATE users SET email = lower(?) WHERE id = ? AND google_sub IS NULL", (email.strip(), OWNER_ID))
        conn.commit()
```

- [ ] **Step 4: Writers take `user_id`**

`src/jobseeker/db/applications.py:31-38`:
```python
def ensure_application(conn: sqlite3.Connection, user_id: int, job_id: int, now: datetime | None = None) -> int:
    ts = _now(now)
    conn.execute(
        "INSERT OR IGNORE INTO applications (user_id, job_id, created_at, updated_at) VALUES (?,?,?,?)",
        (user_id, job_id, ts, ts),
    )
    conn.commit()
    return conn.execute("SELECT id FROM applications WHERE user_id = ? AND job_id = ?",
                        (user_id, job_id)).fetchone()["id"]
```
In `mark_not_interested` (`:159-175`), read `user_id = app["user_id"]`, and every `INSERT INTO blocklist (contact_id, company, reason, at)` becomes `INSERT INTO blocklist (user_id, contact_id, company, reason, at)`, with `user_id` first in the parameter tuples.

`src/jobseeker/db/jobs.py:141-150`:
```python
def save_score(conn: sqlite3.Connection, user_id: int, job_id: int, result: ScoreResult, model: str,
               rubric_version: str, jd_hash_value: str) -> None:
    conn.execute(
        """INSERT INTO scores (user_id, job_id, score, breakdown, matches, gaps, recommendation, role_family,
           model, rubric_version, jd_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, job_id, result.score, json.dumps(result.breakdown), json.dumps(result.matches),
         json.dumps(result.gaps), result.recommendation, result.role_family, model,
         rubric_version, jd_hash_value, utcnow()),
    )
    conn.commit()
```

`src/jobseeker/db/usage.py`: replace with:
```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from jobseeker.config import ContactsConfig


@dataclass(frozen=True)
class Limit:
    period: Literal["day", "month"]
    global_cap: float
    share_cap: float


def contacts_limits(cfg: ContactsConfig) -> dict[str, Limit]:
    """One user (the owner): their share is the whole free tier. Later sub-projects split shares."""
    return {"tavily": Limit("month", cfg.tavily_monthly_limit, cfg.tavily_monthly_limit),
            "apify": Limit("month", cfg.apify_monthly_usd_limit, cfg.apify_monthly_usd_limit),
            "hunter": Limit("month", cfg.hunter_monthly_limit, cfg.hunter_monthly_limit),
            "smtp": Limit("day", cfg.smtp_daily_limit, cfg.smtp_daily_limit)}


class Budget:
    """Free-tier guard: every outside call checks can() and records spend(); a user stops at their share, everyone
    at the global cap, so nothing is ever paid for."""

    def __init__(self, conn: sqlite3.Connection, user_id: int, limits: dict[str, Limit], now: datetime):
        self.conn, self.user_id, self.limits = conn, user_id, limits
        self.month, self.day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")

    def _period(self, service: str) -> str:
        return self.month if self.limits[service].period == "month" else self.day

    def used(self, service: str) -> float:
        row = self.conn.execute("SELECT amount FROM usage WHERE user_id = ? AND period = ? AND service = ?",
                                (self.user_id, self._period(service), service)).fetchone()
        return row["amount"] if row else 0.0

    def used_all(self, service: str) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(amount), 0) AS a FROM usage WHERE period = ? AND service = ?",
                                (self._period(service), service)).fetchone()
        return row["a"]

    def can(self, service: str, amount: float = 1) -> bool:
        lim = self.limits[service]
        return (self.used(service) + amount <= lim.share_cap + 1e-9
                and self.used_all(service) + amount <= lim.global_cap + 1e-9)

    def spend(self, service: str, amount: float = 1) -> None:
        self.conn.execute(
            """INSERT INTO usage (user_id, period, service, amount) VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id, period, service) DO UPDATE SET amount = amount + excluded.amount""",
            (self.user_id, self._period(service), service, amount))
        self.conn.commit()

    def summary(self) -> str:
        lim = self.limits
        return (f"Tavily {self.used('tavily'):.0f}/{lim['tavily'].share_cap:.0f} · "
                f"Apify ${self.used('apify'):.2f}/${lim['apify'].share_cap:.2f} · "
                f"Hunter {self.used('hunter'):.0f}/{lim['hunter'].share_cap:.0f} · "
                f"SMTP today {self.used('smtp'):.0f}/{lim['smtp'].share_cap:.0f}")
```
(The card text stays exactly as before for the owner: `950`, `$4.50`, `45`, `60`.)

`src/jobseeker/contacts/finder.py:57-60`: after `app = get_application(conn, app_id)`, add `user_id = app["user_id"]`. Replace `budget = Budget(conn, prefs.contacts, deps.now())` with `budget = Budget(conn, user_id, contacts_limits(prefs.contacts), deps.now())`, and import `contacts_limits` from `jobseeker.db.usage`.

`src/jobseeker/web/contacts.py:33`: `"usage": Budget(conn, app_row_user, contacts_limits(state.prefs.contacts), datetime.now(UTC)).summary(),`. Get `app_row_user` at the top of `card_context`: `app_row_user = conn.execute("SELECT user_id FROM applications WHERE id = ?", (app_id,)).fetchone()["user_id"]`.

`src/jobseeker/pipeline/run.py`:
- `run_daily` gains a required keyword `user_id: int` and passes it to `_run`;
- `_run` gains a `user_id` parameter;
- in `_run`, `save_score(conn, user_id, row["id"], result, model, rubric.version, row["jd_hash"])` and `app_id = ensure_application(conn, user_id, row["id"], now)`.

`src/jobseeker/cli.py`:
- in `_load()`, after `settings = Settings()`, add:
  ```python
  from jobseeker.db.users import ensure_owner
  conn = connect(settings.db_path)
  ensure_owner(conn, settings.owner_email)
  conn.close()
  ```
- in `_run`, pass `user_id=OWNER_ID` (imported from `jobseeker.db.users`) to `run_daily`.

`src/jobseeker/web/app.py`, in `create_app` before the routers:
```python
    from jobseeker.db.core import connect
    from jobseeker.db.users import ensure_owner

    boot = connect(settings.db_path)  # raises SchemaOutOfDate on an un-migrated database: fail at startup
    ensure_owner(boot, settings.owner_email)
    boot.close()
```

- [ ] **Step 5: Update the existing tests' call sites** (exact edits):
- `tests/conftest.py:69`: `save_score(conn, 1, job_id, ScoreResult(…), "m", "v1", "h")`. `:72`: `app_id = ensure_application(conn, 1, job_id)`.
- `tests/test_db_applications.py:22`: `ensure_application(conn, 1, job_id, NOW)`. `:28`: `ensure_application(conn, 1, job_id)`. `:79`: `ensure_application(conn, 1, job2)`.
- `tests/test_contacts_finder.py:67`: `ensure_application(conn, 1, job_id, NOW)`. `:130`: `ensure_application(conn, 1, job2, NOW)`.
- `tests/test_refilter.py:26,28`: insert `1, ` as the second argument.
- `tests/test_db_jobs.py:56`: `save_score(conn, 1, a, result, …)`. `:136`: `save_score(conn, 1, scored, …)`.
- `tests/test_contacts_setup.py:55`: `b = Budget(conn, 1, contacts_limits(ContactsConfig(tavily_monthly_limit=2, smtp_daily_limit=1, apify_monthly_usd_limit=0.15)), NOW)`. `:64`: `Budget(conn, 1, contacts_limits(ContactsConfig(smtp_daily_limit=1)), NOW.replace(day=9))`. Import `contacts_limits`.
- `tests/test_run.py:46` and `:122`, `tests/test_run_discovery.py:50`: add `user_id=1,` to the `run_daily(` keyword arguments.

- [ ] **Step 6: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no` → all pass. Node: 19 pass.
Also run `uv run jobseeker migrate --dry-run` against a **copy** of the live DB: `mkdir -p /tmp/jsmig/data && sqlite3 "/Users/user/Desktop/untitled folder/job-seeker2.0/data/jobseeker.db" ".backup /tmp/jsmig/data/jobseeker.db" && JOBSEEKER_HOME=/tmp/jsmig OWNER_EMAIL=mkshitij1763@gmail.com uv run jobseeker migrate --dry-run`. Expected: "Applied v1" and unchanged counts for applications/scores/drafts/events/jobs. Paste the report into the task notes. This is read-only on the live DB, through `.backup`.

- [ ] **Step 7: Commit**

```bash
git add src/jobseeker/db/schema.sql src/jobseeker/db/migrations.py src/jobseeker/db/core.py src/jobseeker/db/users.py \
  src/jobseeker/db/applications.py src/jobseeker/db/jobs.py src/jobseeker/db/usage.py src/jobseeker/pipeline/run.py \
  src/jobseeker/contacts/finder.py src/jobseeker/web/contacts.py src/jobseeker/web/app.py src/jobseeker/cli.py \
  tests/conftest.py tests/test_db_applications.py tests/test_contacts_finder.py tests/test_refilter.py tests/test_db_jobs.py \
  tests/test_contacts_setup.py tests/test_run.py tests/test_run_discovery.py tests/test_migrations.py tests/test_users.py
git commit -m "feat(db): v1 schema live; writers take user_id; budgets per user with a global cap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 4: Per-user verdicts move to `user_jobs`

**Files:**
- Modify: `src/jobseeker/db/jobs.py:70-82, 98-138` (`set_filter_reason`, `set_prescore`, `expire_unscored`, `jobs_missing_prescore`, `jobs_needing_score`; add `get_user_job`)
- Modify: `src/jobseeker/pipeline/run.py` (`_rank`, `_fetch`, `_select`, `_fill_linkedin_descriptions` get `user_id`)
- Modify: `src/jobseeker/pipeline/refilter.py:14-37` (`refilter(conn, user_id, prefs, now, apply)`)
- Modify: `src/jobseeker/cli.py:89-90` (`run_refilter(connect(...), OWNER_ID, prefs, …)`)
- Modify tests: `tests/test_db_jobs.py:52-59, 110-112, 138-143`, `tests/test_refilter.py:32,36,42`
- Test: `tests/test_db_jobs.py` (append)

**Interfaces:**
- Consumes: `user_jobs` (Task 3 schema).
- Produces:
  - `set_filter_reason(conn, user_id, job_id, reason)`, `set_prescore(conn, user_id, job_id, score)`, `get_user_job(conn, user_id, job_id) -> dict | None`;
  - `expire_unscored(conn, user_id, now, max_age_days) -> int`, `jobs_missing_prescore(conn, user_id) -> list[dict]`;
  - `jobs_needing_score(conn, user_id, rubric_version, limit, force=False, with_jd=False) -> list[dict]` (rows are `j.*` plus `uj_prescore`);
  - `refilter(conn, user_id, prefs, now, apply) -> list[dict]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_db_jobs.py`):

```python
def test_verdicts_are_per_user(tmp_path):
    from jobseeker.db.jobs import get_user_job, jobs_needing_score, set_filter_reason, set_prescore
    conn = connect(tmp_path / "db.sqlite")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    a, _ = upsert_job(conn, make_job(source_job_id="a", fingerprint="fa"))
    set_filter_reason(conn, 1, a, "title: sde")
    set_prescore(conn, 2, a, 55)
    assert get_user_job(conn, 1, a)["filter_reason"] == "title: sde"
    assert get_user_job(conn, 2, a)["prescore"] == 55 and get_user_job(conn, 2, a)["filter_reason"] is None
    assert jobs_needing_score(conn, 1, "v1", 10) == []
    assert [r["id"] for r in jobs_needing_score(conn, 2, "v1", 10)] == [a]
    assert conn.execute("SELECT filter_reason, prescore FROM jobs WHERE id = ?", (a,)).fetchone()[:] == (None, None)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_db_jobs.py -k per_user` → FAIL (TypeError: wrong arguments).

- [ ] **Step 3: Implement** (`src/jobseeker/db/jobs.py`):

```python
def _upsert_verdict(conn, user_id: int, job_id: int, column: str, value) -> None:
    conn.execute(
        f"""INSERT INTO user_jobs (user_id, job_id, {column}, jd_hash, evaluated_at)
            SELECT ?, id, ?, jd_hash, ? FROM jobs WHERE id = ?
            ON CONFLICT (user_id, job_id) DO UPDATE SET {column} = excluded.{column},
              jd_hash = excluded.jd_hash, evaluated_at = excluded.evaluated_at""",
        (user_id, value, utcnow(), job_id))
    conn.commit()


def set_filter_reason(conn: sqlite3.Connection, user_id: int, job_id: int, reason: str) -> None:
    _upsert_verdict(conn, user_id, job_id, "filter_reason", reason)


def set_prescore(conn: sqlite3.Connection, user_id: int, job_id: int, score: int) -> None:
    _upsert_verdict(conn, user_id, job_id, "prescore", score)


def get_user_job(conn: sqlite3.Connection, user_id: int, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM user_jobs WHERE user_id = ? AND job_id = ?", (user_id, job_id)).fetchone()
    return dict(row) if row else None


def expire_unscored(conn: sqlite3.Connection, user_id: int, now: datetime, max_age_days: int) -> int:
    cutoff = iso(now - timedelta(days=max_age_days))
    cur = conn.execute(
        """UPDATE user_jobs SET filter_reason = 'stale: never scored'
           WHERE user_id = ? AND filter_reason IS NULL
           AND job_id IN (SELECT id FROM jobs WHERE COALESCE(posted_at, first_seen_at) < ?)
           AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = user_jobs.user_id AND s.job_id = user_jobs.job_id)""",
        (user_id, cutoff))
    conn.commit()
    return cur.rowcount


_UJ = "LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u"


def jobs_missing_prescore(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        f"""SELECT j.* FROM jobs j {_UJ} WHERE uj.filter_reason IS NULL AND uj.prescore IS NULL
            AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id) ORDER BY j.id""",
        {"u": user_id}).fetchall()
    return [dict(r) for r in rows]


def jobs_needing_score(conn: sqlite3.Connection, user_id: int, rubric_version: str, limit: int,
                       force: bool = False, with_jd: bool = False) -> list[dict]:
    tail = ("AND TRIM(j.jd_text) != '' " if with_jd else "") + \
        "ORDER BY COALESCE(uj.prescore, -1) DESC, j.first_seen_at DESC, j.id DESC LIMIT :limit"
    fresh = "" if force else """AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id
                                    AND s.rubric_version = :rv AND s.jd_hash = j.jd_hash)"""
    sql = f"SELECT j.*, uj.prescore AS uj_prescore FROM jobs j {_UJ} WHERE uj.filter_reason IS NULL {fresh} {tail}"
    return [dict(r) for r in conn.execute(sql, {"u": user_id, "rv": rubric_version, "limit": limit}).fetchall()]
```

`src/jobseeker/pipeline/run.py`:
- `_rank(conn, user_id, stats, job_id, facts, prefs, cutoff)`: replace `row["filter_reason"] is not None` with
  ```python
  verdict = get_user_job(conn, user_id, job_id)
  if row is None or (verdict and verdict["filter_reason"] is not None):
      return
  ```
  and the writes with `set_prescore(conn, user_id, job_id, points)` / `set_filter_reason(conn, user_id, job_id, …)`.
- `_fetch`, `_select` and `_fill_linkedin_descriptions` gain `user_id` and pass it to `blocked_companies` (still global until Task 5: keep calling `blocked_companies(conn)` here), `set_filter_reason`, `_rank`, `expire_unscored(conn, user_id, now, …)`, `jobs_missing_prescore(conn, user_id)` and `jobs_needing_score(conn, user_id, …)`.
- `_run` passes `user_id` to all three.

`src/jobseeker/pipeline/refilter.py:14-22`:
```python
def refilter(conn: sqlite3.Connection, user_id: int, prefs: Preferences, now: datetime, apply: bool) -> list[dict]:
    blocked = blocked_companies(conn)
    rows = conn.execute("""SELECT j.*, a.id AS app_id FROM jobs j
                           LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u
                           LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = :u
                           WHERE uj.filter_reason IS NULL ORDER BY j.id""", {"u": user_id}).fetchall()
```
In the apply branch: `set_filter_reason(conn, user_id, row["id"], reason)`.

Test edits:
- `tests/test_db_jobs.py`: `:52` `set_filter_reason(conn, 1, b, …)`; `:53, 57-59, 112` `jobs_needing_score(conn, 1, …)`; `:110-111` `set_prescore(conn, 1, …)`; `:138` `expire_unscored(conn, 1, now, 7)`; `:141, 143` `jobs_missing_prescore(conn, 1)`; `:142` `set_prescore(conn, 1, fresh, 50)`.
- `tests/test_refilter.py:32, 36, 42`: `refilter(conn, 1, prefs, NOW, …)`.
- `src/jobseeker/cli.py:90`: `run_refilter(connect(settings.db_path), OWNER_ID, prefs, …)`.

Any assertion that read `jobs.filter_reason` directly (`grep -n "filter_reason" tests/*.py`) switches to `get_user_job(conn, 1, id)["filter_reason"]`.

- [ ] **Step 4: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no` → all pass. Node: 19.

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/db/jobs.py src/jobseeker/pipeline/run.py src/jobseeker/pipeline/refilter.py src/jobseeker/cli.py tests/
git commit -m "feat(db): filter verdicts and pre-scores live in user_jobs per user

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```
(`tests/` here means only the files edited above; check `git status` and add them by name.)

---

### Task 5: Read-side scoping (queries, nav counts, runs, blocklist)

**Files:**
- Modify: `src/jobseeker/db/queries.py` (all public functions take `user_id`)
- Modify: `src/jobseeker/db/jobs.py:153-157` (`latest_score(conn, user_id, job_id)`)
- Modify: `src/jobseeker/db/runs.py` (`start_run(conn, now, user_id=None, kind="legacy")`, `last_run(conn, user_id)`)
- Modify: `src/jobseeker/db/applications.py:121-156` (`blocked_companies(conn, user_id)`; `save_contact` checks only the app's user's blocklist)
- Modify: `src/jobseeker/db/contacts_repo.py:156-201` (`blocked_profile_urls(conn, user_id, company)`, `blocked_names(conn, user_id, company)`, `upsert_contact(conn, user_id, company, …)`)
- Modify: `src/jobseeker/contacts/finder.py` (pass `user_id`; the `role_family` query is scoped)
- Modify: `src/jobseeker/web/view.py:83-91` (`nav_counts(conn, user_id)`)
- Modify: `src/jobseeker/web/{deps,inbox,pipeline,application,contacts}.py` (pass `OWNER_ID` for now)
- Modify: `src/jobseeker/pipeline/run.py`, `src/jobseeker/pipeline/refilter.py` (`blocked_companies(conn, user_id)`; `start_run(conn, now, user_id=user_id)`)
- Modify tests (call sites listed in Step 4)
- Create: `tests/conftest.py` fixture `seeded_two`
- Test: `tests/test_isolation.py` (new; data layer)

**Interfaces:**
- Consumes: `OWNER_ID` (Task 3).
- Produces (all with `user_id` second):
  - `inbox`, `inbox_facets`, `application_detail` (returns `None` when the app isn't the user's), `pipeline`, `stats`, `today`;
  - `nav_counts`, `last_run`, `latest_score`, `blocked_companies`, `blocked_profile_urls`, `blocked_names`, `upsert_contact`.
- Produces the fixture `seeded_two(settings) -> dict`: `{"owner_apps": (apply_id, review_id), "roommate_app": id, "j1": job_id}`.

- [ ] **Step 1: Write the `seeded_two` fixture** (append to `tests/conftest.py`):

```python
@pytest.fixture
def seeded_two(settings, seeded):
    """The owner's `seeded` data, plus user 2 with their own score and application on the owner's first job (J1),
    a blocklist row and a usage row: everything isolation tests try to leak."""
    conn = connect(settings.db_path)
    j1 = conn.execute("SELECT job_id FROM applications WHERE id = ?", (seeded[0],)).fetchone()[0]
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (2, 'roomie@example.com', 'Roomie', 't')")
    save_score(conn, 2, j1, ScoreResult(score=91, breakdown={}, matches=["Excel"], gaps=[], recommendation="apply",
                                        role_family="growth_analyst"), "m", "v1", "h")
    app2 = ensure_application(conn, 2, j1)
    transition(conn, app2, "shortlisted")
    conn.execute("INSERT INTO blocklist (user_id, company, reason, at) VALUES (2, 'cred', 'not interested', 't')")
    from datetime import UTC, datetime
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (2, ?, 'tavily', 7)",
                 (datetime.now(UTC).strftime("%Y-%m"),))
    conn.commit()
    conn.close()
    return {"owner_apps": seeded, "roommate_app": app2, "j1": j1}
```

- [ ] **Step 2: Write the failing tests** (`tests/test_isolation.py`):

```python
from datetime import UTC, datetime

from jobseeker.db import queries
from jobseeker.db.applications import blocked_companies
from jobseeker.db.core import connect
from jobseeker.db.jobs import latest_score
from jobseeker.db.runs import last_run, start_run
from jobseeker.web.view import nav_counts

NOW = datetime.now(UTC)


def test_inbox_and_facets_are_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    owner_ids = {r["app_id"] for r in queries.inbox(conn, 1, band="all")}
    assert seeded_two["roommate_app"] not in owner_ids
    assert {r["app_id"] for r in queries.inbox(conn, 2, band="all")} == {seeded_two["roommate_app"]}
    assert "growth_analyst" not in queries.inbox_facets(conn, 1)["families"]


def test_latest_score_and_detail_are_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    assert latest_score(conn, 1, seeded_two["j1"])["score"] == 88
    assert latest_score(conn, 2, seeded_two["j1"])["score"] == 91
    assert queries.application_detail(conn, 2, seeded_two["owner_apps"][0]) is None


def test_boards_counts_and_stats_are_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    assert all(c["app_id"] != seeded_two["roommate_app"] for cards in queries.pipeline(conn, 1, NOW).values() for c in cards)
    assert [c["app_id"] for c in queries.pipeline(conn, 2, NOW)["shortlisted"]] == [seeded_two["roommate_app"]]
    assert nav_counts(conn, 2)["jobs"] == 1
    t = queries.today(conn, 2, NOW)
    assert all(r["app_id"] == seeded_two["roommate_app"] for k in ("send", "ready", "find_contacts") for r in t[k])
    assert queries.stats(conn, 2, NOW)["drafted"] == 0


def test_blocklist_is_per_user(settings, seeded_two):
    conn = connect(settings.db_path)
    assert "cred" in blocked_companies(conn, 2)
    assert "cred" not in blocked_companies(conn, 1)


def test_last_run_shows_own_and_shared_runs(settings, seeded_two):
    conn = connect(settings.db_path)
    start_run(conn, NOW, user_id=2)
    shared = start_run(conn, NOW, user_id=None, kind="fetch")
    assert last_run(conn, 1)["id"] == shared
    mine = start_run(conn, NOW, user_id=1)
    assert last_run(conn, 1)["id"] == mine
```

- [ ] **Step 3: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_isolation.py` → FAIL (TypeError: unexpected arguments).

- [ ] **Step 4: Implement**

`src/jobseeker/db/queries.py`:
- `_LATEST_SCORE = "s.id = (SELECT id FROM scores WHERE job_id = j.id AND user_id = a.user_id ORDER BY id DESC LIMIT 1)"`.
- `inbox(conn, user_id, band="apply", …)`: replace `WHERE 1 = 1` with `WHERE a.user_id = ?` and start `params` as `[user_id]`. `band="all"` (as used by the tests) means no recommendation filter, as any other value outside apply/review/hide already does.
- `inbox_facets(conn, user_id)`: families come from `SELECT DISTINCT role_family FROM scores WHERE user_id = ? ORDER BY 1`. Cities and sources stay from `jobs` (shared).
- `application_detail(conn, user_id, app_id)`: return `None` if `not app or app["user_id"] != user_id`; `"score": latest_score(conn, user_id, app["job_id"])`.
- `pipeline(conn, user_id, now)` and `today(conn, user_id, now)`: add `AND a.user_id = ?` to the `WHERE`, with the parameter first (`[user_id, *PIPELINE_COLUMNS]`, `(user_id,)`).
- `stats(conn, user_id, now, days=30)`: in `moved_to`, `FROM events e JOIN applications a ON a.id = e.application_id WHERE a.user_id = ? AND e.type = 'status' …`, with parameters `(user_id, status, since, status)`. `per_source` stays shared.

`src/jobseeker/db/jobs.py:153-157`:
```python
def latest_score(conn: sqlite3.Connection, user_id: int, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM scores WHERE user_id = ? AND job_id = ? ORDER BY id DESC LIMIT 1",
                       (user_id, job_id)).fetchone()
    return dict(row) if row else None
```

`src/jobseeker/db/runs.py`:
```python
def start_run(conn: sqlite3.Connection, now: datetime, user_id: int | None = None, kind: str = "legacy") -> int:
    cur = conn.execute("INSERT INTO runs (started_at, user_id, kind) VALUES (?, ?, ?)", (iso(now), user_id, kind))
    conn.commit()
    return cur.lastrowid


def last_run(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE user_id = ? OR user_id IS NULL ORDER BY id DESC LIMIT 1",
                       (user_id,)).fetchone()
    return dict(row) if row else None
```

`src/jobseeker/db/applications.py`:
- `blocked_companies(conn, user_id)`: `SELECT company FROM blocklist WHERE user_id = ? AND company != ''`.
- `save_contact`: after `company = _company_of(...)`, add `user_id = get_application(conn, app_id)["user_id"]`. The block check becomes `SELECT 1 FROM blocklist WHERE contact_id = ? AND user_id = ?`.

`src/jobseeker/db/contacts_repo.py`:
- `blocked_profile_urls(conn, user_id, company)` and `blocked_names(conn, user_id, company)`: add `AND b.user_id = ?` to their `WHERE`;
- `upsert_contact(conn, user_id, company, name, role, linkedin_url, email, email_status, domain=None)`: the block check becomes `SELECT 1 FROM blocklist WHERE contact_id = ? AND user_id = ?`.

`src/jobseeker/contacts/finder.py`:
- `blocked_profile_urls(conn, user_id, company)`, `blocked_names(conn, user_id, company)`, `upsert_contact(conn, user_id, company, …)`;
- the `role_family` query (`:62-63`) becomes `… FROM scores WHERE user_id = ? AND job_id = ? …` with `(user_id, job["id"])`.

`src/jobseeker/pipeline/run.py` and `src/jobseeker/pipeline/refilter.py`: `blocked_companies(conn, user_id)`. `run_daily`: `start_run(conn, now, user_id=user_id)`.

`src/jobseeker/web/view.py:83-91`: `nav_counts(conn, user_id)`. Both `COUNT(*)` queries add `AND user_id = ?`, and it calls `inbox(conn, user_id)`.

Web callers (temporary, until Task 8): in `src/jobseeker/web/deps.py:render`, `last_run(conn, OWNER_ID)` and `nav_counts(conn, OWNER_ID)`. Pass `OWNER_ID` in:
- `web/inbox.py` (`queries.inbox`, `inbox_facets`);
- `web/pipeline.py` (`pipeline`, `stats`, `today`);
- `web/application.py:41, 137` (`application_detail(conn, OWNER_ID, app_id)`);
- `web/contacts.py:98` (`upsert_contact(conn, OWNER_ID, …)`).

Each file imports `from jobseeker.db.users import OWNER_ID`.

Test call-site edits:
- `tests/test_web_contacts_outreach.py:50, 114, 123, 132, 143, 251`: `upsert_contact(conn, 1, "CRED", …)`, `queries.pipeline(conn, 1, …)`, `blocked_profile_urls(conn, 1, "CRED")`, `queries.application_detail(connect(…), 1, a)`;
- `tests/test_run_discovery.py:165`, `tests/test_run.py:55, 124`: `last_run(conn, 1)`;
- `tests/test_web_pipeline.py:17, 20, 37, 40`: `queries.pipeline(conn, 1, …)`, `queries.stats(conn, 1, …)`;
- `tests/test_db_applications.py:77`: `blocked_companies(conn, 1)`;
- `tests/test_web_redesign.py:193, 270`, `tests/test_web_today.py:13, 24, 30, 39`, `tests/test_web_mobile.py:139`: `upsert_contact(conn, 1, …)`, `queries.today(conn, 1, …)`;
- `tests/test_web_view.py:54`: `nav_counts(conn, 1)`;
- `tests/test_db_jobs.py:60`: `latest_score(conn, 1, a)`;
- `tests/test_contacts_finder.py`: any direct `upsert_contact`/`blocked_*` calls get `1,` (`grep -n "upsert_contact\|blocked_" tests/test_contacts_finder.py`).

- [ ] **Step 5: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no` → all pass. Node: 19.

- [ ] **Step 6: Commit** (add the edited files by name)

```bash
git commit -m "feat(db): per-user reads for inbox, boards, stats, scores, runs and blocklists

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 6: Auth settings, OAuth primitives, users and invites

**Files:**
- Modify: `pyproject.toml` (`uv add google-auth`), `uv.lock`
- Modify: `src/jobseeker/config.py:11-22` (`Settings` auth fields)
- Create: `src/jobseeker/web/oauth.py`
- Modify: `src/jobseeker/db/users.py` (`User`, `resolve_sign_in`, `owner_first_name`, invites, enable/disable, `list_users`)
- Test: `tests/test_users.py` (append), `tests/test_oauth.py` (new)

**Interfaces:**
- Produces:
  - `Settings.google_client_id`, `google_client_secret`, `base_url`, `secret_key` (str, default `""`), `cookie_secure: bool = True`;
  - `oauth.sign(payload: dict, key: str, now: datetime, ttl: timedelta) -> str`, `oauth.unsign(token: str, key: str, now: datetime) -> dict`, raising `oauth.BadSignature`;
  - `oauth.pkce_pair() -> tuple[str, str]`;
  - `oauth.auth_url(client_id, redirect_uri, state, nonce, challenge, scope="openid email profile", **extra) -> str`;
  - `oauth.local_path(next_: str | None) -> str | None`;
  - `oauth.SESSION_COOKIE = "__Host-js_session"`, `oauth.OAUTH_COOKIE = "__Host-js_oauth"`;
  - `User(id: int, email: str, name: str, is_admin: bool, google_sub: str | None)`;
  - `user_by_id(conn, user_id) -> User | None`, `resolve_sign_in(conn, sub, email, name, now) -> User | None`, `owner_first_name(conn) -> str`;
  - `add_invite(conn, email, invited_by, now)`, `remove_invite(conn, email)`, `list_invites(conn) -> list[dict]`;
  - `list_users(conn) -> list[dict]`, `set_disabled(conn, user_id, disabled: bool, now) -> None` (raises `LastAdmin`).

- [ ] **Step 1: Add the dependency**

Run: `uv add google-auth`. Expected: `pyproject.toml` lists `google-auth>=…` and `uv.lock` updates. (It's already installed transitively, so no new download is needed beyond the lock.)

- [ ] **Step 2: Write the failing tests**

`tests/test_oauth.py`:
```python
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from jobseeker.web import oauth

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def test_sign_roundtrip_and_expiry():
    tok = oauth.sign({"state": "s"}, "k" * 32, NOW, timedelta(minutes=10))
    assert oauth.unsign(tok, "k" * 32, NOW + timedelta(minutes=9))["state"] == "s"
    with pytest.raises(oauth.BadSignature):
        oauth.unsign(tok, "k" * 32, NOW + timedelta(minutes=11))


@pytest.mark.parametrize("tamper", [lambda t: t[:-2] + "xx", lambda t: "e30" + t[3:], lambda t: "", lambda t: "nodot"])
def test_unsign_rejects_tampering(tamper):
    tok = oauth.sign({"state": "s"}, "k" * 32, NOW, timedelta(minutes=10))
    with pytest.raises(oauth.BadSignature):
        oauth.unsign(tamper(tok), "k" * 32, NOW)


def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = oauth.pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected and len(verifier) >= 43


def test_auth_url_has_exact_params():
    q = parse_qs(urlsplit(oauth.auth_url("cid", "https://x/auth/callback", "st", "no", "ch")).query)
    assert q["scope"] == ["openid email profile"] and q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["st"] and q["nonce"] == ["no"] and q["response_type"] == ["code"]
    assert q["prompt"] == ["select_account"] and q["redirect_uri"] == ["https://x/auth/callback"]


@pytest.mark.parametrize("value,expected", [("/applications/3?x=1", "/applications/3?x=1"), ("//evil.com", None),
                                            ("https://evil.com", None), ("/\\evil", None), ("", None), (None, None)])
def test_local_path(value, expected):
    assert oauth.local_path(value) == expected
```
Append to `tests/test_users.py`:
```python
from datetime import UTC, datetime

import pytest

from jobseeker.db.users import (LastAdmin, add_invite, owner_first_name, resolve_sign_in, set_disabled,
                                user_by_id)

T = datetime(2026, 10, 8, tzinfo=UTC)


def _db(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    ensure_owner(conn, "owner@example.com")
    return conn


def test_owner_first_login_claims_sub_then_sub_wins(tmp_path):
    conn = _db(tmp_path)
    u = resolve_sign_in(conn, "g-1", "Owner@Example.com", "Kay Em", T)
    assert u.id == 1 and u.is_admin
    assert resolve_sign_in(conn, "g-1", "renamed@example.com", "Kay Em", T).id == 1


def test_uninvited_gets_none_and_no_row(tmp_path):
    conn = _db(tmp_path)
    assert resolve_sign_in(conn, "g-2", "stranger@example.com", "S", T) is None
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_invited_creates_user_and_accepts(tmp_path):
    conn = _db(tmp_path)
    add_invite(conn, "Roomie@Example.com", 1, T)
    u = resolve_sign_in(conn, "g-3", "roomie@example.com", "Roo Mie", T)
    assert u.id == 2 and not u.is_admin
    assert conn.execute("SELECT accepted_at FROM invites").fetchone()[0] is not None


def test_disabled_is_refused_and_last_admin_kept(tmp_path):
    conn = _db(tmp_path)
    add_invite(conn, "r@example.com", 1, T)
    resolve_sign_in(conn, "g-3", "r@example.com", "R", T)
    set_disabled(conn, 2, True, T)
    assert resolve_sign_in(conn, "g-3", "r@example.com", "R", T) is None
    with pytest.raises(LastAdmin):
        set_disabled(conn, 1, True, T)


def test_owner_first_name_fallback(tmp_path):
    conn = _db(tmp_path)
    assert owner_first_name(conn) == "the person who shared this link"
    resolve_sign_in(conn, "g-1", "owner@example.com", "Kay Em", T)
    assert owner_first_name(conn) == "Kay"
    assert user_by_id(conn, 1).name == "Kay Em"
```

- [ ] **Step 3: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_oauth.py tests/test_users.py` → FAIL (ImportError).

- [ ] **Step 4: Implement**

`src/jobseeker/config.py`, in `Settings` after `hunter_api_key`:
```python
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = ""
    secret_key: str = ""
    owner_email: str = ""        # (moved here from Task 1's position; keep one definition)
    cookie_secure: bool = True
```

`src/jobseeker/web/oauth.py`:
```python
"""Pure helpers for the hand-rolled Google sign-in: signed short-lived cookies, PKCE, the auth URL."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SESSION_COOKIE = "__Host-js_session"
OAUTH_COOKIE = "__Host-js_oauth"


class BadSignature(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(body: str, key: str) -> str:
    return _b64(hmac.new(key.encode(), body.encode(), hashlib.sha256).digest())


def sign(payload: dict, key: str, now: datetime, ttl: timedelta) -> str:
    body = _b64(json.dumps({**payload, "exp": int((now + ttl).timestamp())}, separators=(",", ":")).encode())
    return f"{body}.{_mac(body, key)}"


def unsign(token: str, key: str, now: datetime) -> dict:
    body, dot, mac = (token or "").partition(".")
    if not dot or not hmac.compare_digest(mac, _mac(body, key)):
        raise BadSignature("bad signature")
    try:
        data = json.loads(_unb64(body))
    except ValueError as e:
        raise BadSignature("unreadable") from e
    if not isinstance(data, dict) or data.get("exp", 0) < now.timestamp():
        raise BadSignature("expired")
    return data


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    return verifier, _b64(hashlib.sha256(verifier.encode()).digest())


def auth_url(client_id: str, redirect_uri: str, state: str, nonce: str, challenge: str,
             scope: str = "openid email profile", **extra: str) -> str:
    q = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": scope,
         "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
         "prompt": "select_account", **extra}
    return f"{AUTH_URL}?{urlencode(q)}"


def local_path(next_: str | None) -> str | None:
    """Only same-site paths: "//host" and "/\\host" leave the site."""
    if next_ and next_.startswith("/") and not next_.startswith(("//", "/\\")):
        return next_
    return None
```
Also change `_back` in `src/jobseeker/web/application.py:31` to `local = oauth.local_path(next_) is not None` (with an import), so there's one rule.

`src/jobseeker/db/users.py`, adding to the Task 3 content:
```python
import random
from dataclasses import dataclass
from datetime import datetime

from jobseeker.db.core import iso

FALLBACK_OWNER = "the person who shared this link"


class LastAdmin(ValueError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    is_admin: bool
    google_sub: str | None


def _user(row) -> User:
    return User(row["id"], row["email"], row["name"], bool(row["is_admin"]), row["google_sub"])


def user_by_id(conn, user_id: int) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user(row) if row else None


def resolve_sign_in(conn, sub: str, email: str, name: str, now: datetime) -> User | None:
    """A verified Google identity → its user, or None (not invited, or disabled). Identity is `sub` after the first
    sign-in, so a changed Gmail address can't take over an account."""
    email = email.strip().lower()
    row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM users WHERE email = ? AND google_sub IS NULL", (email,)).fetchone()
        if row is not None:
            conn.execute("UPDATE users SET google_sub = ? WHERE id = ?", (sub, row["id"]))
    if row is None:
        invite = conn.execute("SELECT 1 FROM invites WHERE email = ?", (email,)).fetchone()
        if not invite:
            return None
        cur = conn.execute("INSERT INTO users (google_sub, email, name, created_at) VALUES (?, ?, ?, ?)",
                           (sub, email, name, iso(now)))
        conn.execute("UPDATE invites SET accepted_at = ? WHERE email = ?", (iso(now), email))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    if row["disabled_at"]:
        conn.commit()
        return None
    conn.execute("UPDATE users SET last_login_at = ?, name = ? WHERE id = ?", (iso(now), name or row["name"], row["id"]))
    conn.commit()
    return user_by_id(conn, row["id"])


def owner_first_name(conn) -> str:
    row = conn.execute("SELECT name FROM users WHERE id = ?", (OWNER_ID,)).fetchone()
    first = (row["name"] if row else "").split()
    return first[0] if first else FALLBACK_OWNER


def add_invite(conn, email: str, invited_by: int, now: datetime) -> None:
    conn.execute("INSERT OR IGNORE INTO invites (email, invited_by, created_at) VALUES (lower(?), ?, ?)",
                 (email.strip(), invited_by, iso(now)))
    conn.commit()


def remove_invite(conn, email: str) -> None:
    conn.execute("DELETE FROM invites WHERE email = lower(?)", (email.strip(),))
    conn.commit()


def list_invites(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM invites ORDER BY created_at")]


def list_users(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]


def set_disabled(conn, user_id: int, disabled: bool, now: datetime) -> None:
    if disabled:
        admins = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND disabled_at IS NULL AND id != ?",
                              (user_id,)).fetchone()[0]
        is_admin = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        if is_admin and admins == 0:
            raise LastAdmin("There must be at least one admin")
        conn.execute("UPDATE users SET disabled_at = ? WHERE id = ?", (iso(now), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    else:
        conn.execute("UPDATE users SET disabled_at = NULL WHERE id = ?", (user_id,))
    conn.commit()
```
(Drop the unused `random` import if the linter flags it. Session purging lives in `db/sessions.py`, Task 7.)

- [ ] **Step 5: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_oauth.py tests/test_users.py`, then the full pytest and node suites.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/jobseeker/config.py src/jobseeker/web/oauth.py src/jobseeker/web/application.py \
        src/jobseeker/db/users.py tests/test_oauth.py tests/test_users.py
git commit -m "feat(auth): OAuth primitives, users, invites; google-auth as a direct dependency

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 7: Sessions and the sign-in routes

**Files:**
- Create: `src/jobseeker/db/sessions.py`
- Create: `src/jobseeker/web/auth.py`
- Create: `src/jobseeker/web/templates/bare.html`, `auth_message.html`, `not_invited.html`
- Modify: `src/jobseeker/web/deps.py` (`optional_user`, `current_user`, `NotAuthenticated`)
- Modify: `src/jobseeker/web/app.py` (include `auth.router`; the `NotAuthenticated` handler; a session-refresh middleware; the startup env check)
- Modify: `tests/conftest.py:26-27` (`settings` gets the auth fields), `tests/test_web_contacts.py:51` (`**AUTH_TEST`)
- Test: `tests/test_auth.py` (new)

**Interfaces:**
- Consumes: `oauth.*`, `resolve_sign_in`, `owner_first_name`, `User` (Task 6).
- Produces:
  - `create_session(conn, user_id, now) -> str` (the raw token), `user_for_token(conn, token, now) -> tuple[User, bool] | None` (`bool` = refreshed), `delete_session(conn, token)`, `delete_user_sessions(conn, user_id)`, `purge_expired(conn, now) -> int`;
  - `SESSION_DAYS = 30`;
  - `optional_user(request, conn) -> User | None`, `current_user(user=Depends(optional_user)) -> User`;
  - `exchange_code(settings, code, verifier) -> str`, `verify_id_token(token, client_id) -> dict`;
  - the conftest constant `AUTH_TEST: dict`.

- [ ] **Step 1: Give the test settings auth values** (`tests/conftest.py`):

```python
AUTH_TEST = dict(google_client_id="cid.apps.googleusercontent.com", google_client_secret="secret",
                 base_url="https://testserver", secret_key="k" * 32, owner_email="owner@example.com")


@pytest.fixture
def settings(home: Path) -> Settings:
    return Settings(jobseeker_home=home, groq_api_key="test", **AUTH_TEST)
```
`tests/test_web_contacts.py:51`: `s = Settings(jobseeker_home=home, groq_api_key="test", tavily_api_key="", **AUTH_TEST)`, with `from tests.conftest import AUTH_TEST`.

- [ ] **Step 2: Write the failing tests** (`tests/test_auth.py`):

```python
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from jobseeker.db.core import connect
from jobseeker.db.sessions import create_session, user_for_token
from jobseeker.db.users import add_invite
from jobseeker.web import auth, oauth
from jobseeker.web.app import create_app

T = datetime(2026, 10, 8, tzinfo=UTC)


@pytest.fixture
def web(settings):
    return TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)


def _login(web, next_="/"):
    r = web.get(f"/login?next={next_}")
    assert r.status_code == 303
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return q["state"][0], q["nonce"][0]


def _callback(web, monkeypatch, claims, state=None):
    st, nonce = _login(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": nonce, "email_verified": True, **claims})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        return web.get(f"/auth/callback?code=c&state={state or st}")


def test_login_redirect_and_cookie(web):
    r = web.get("/login?next=/pipeline")
    loc = urlsplit(r.headers["location"])
    assert loc.netloc == "accounts.google.com"
    assert "__Host-js_oauth" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


def test_owner_signs_in(web, monkeypatch):
    r = _callback(web, monkeypatch, {"sub": "g1", "email": "owner@example.com", "name": "Kay Em"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "__Host-js_session" in r.headers["set-cookie"]


def test_state_mismatch_is_400(web, monkeypatch):
    assert _callback(web, monkeypatch, {"sub": "g1", "email": "owner@example.com"}, state="wrong").status_code == 400


def test_nonce_or_unverified_email_refused(web, monkeypatch):
    st, _ = _login(web)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": "other", "email_verified": True,
                                                                    "sub": "g1", "email": "owner@example.com"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        assert web.get(f"/auth/callback?code=c&state={st}").status_code == 400
    r = _callback(web, monkeypatch, {"sub": "g1", "email": "owner@example.com", "email_verified": False})
    assert r.status_code == 400


def test_verify_failure_and_token_endpoint_failure(web, monkeypatch):
    st, _ = _login(web)

    def boom(tok, cid):
        raise ValueError("bad aud")
    monkeypatch.setattr(auth, "verify_id_token", boom)
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        assert web.get(f"/auth/callback?code=c&state={st}").status_code == 400
    st, _ = _login(web)
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
        assert web.get(f"/auth/callback?code=c&state={st}").status_code == 502


def test_uninvited_gets_403_with_owner_name_and_no_row(web, monkeypatch, settings):
    r = _callback(web, monkeypatch, {"sub": "g9", "email": "stranger@example.com"})
    assert r.status_code == 403 and "invite-only" in r.text and "Kshitij" not in r.text
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_invited_user_signs_in(web, monkeypatch, settings):
    add_invite(connect(settings.db_path), "roomie@example.com", 1, T)
    assert _callback(web, monkeypatch, {"sub": "g2", "email": "roomie@example.com"}).status_code == 303


@pytest.mark.parametrize("bad", ["//evil.com", "https://evil.com", "/\\evil"])
def test_next_open_redirects_fall_back(web, monkeypatch, bad):
    st, nonce = _login(web, bad)
    monkeypatch.setattr(auth, "verify_id_token", lambda tok, cid: {"nonce": nonce, "email_verified": True,
                                                                    "sub": "g1", "email": "owner@example.com"})
    with respx.mock:
        respx.post(oauth.TOKEN_URL).mock(return_value=httpx.Response(200, json={"id_token": "x"}))
        assert web.get(f"/auth/callback?code=c&state={st}").headers["location"] == "/"


def test_session_sliding_writes_at_most_daily(settings):
    conn = connect(settings.db_path)
    tok = create_session(conn, 1, T)
    assert user_for_token(conn, tok, T + timedelta(hours=1))[1] is False
    user, refreshed = user_for_token(conn, tok, T + timedelta(hours=25))
    assert refreshed and user.id == 1
    assert user_for_token(conn, tok, T + timedelta(days=60)) is None
    assert user_for_token(conn, "forged", T) is None


def test_disabled_user_session_is_signed_out(settings):
    conn = connect(settings.db_path)
    tok = create_session(conn, 1, T)
    conn.execute("UPDATE users SET disabled_at = 't' WHERE id = 1")
    conn.commit()
    assert user_for_token(conn, tok, T) is None


def test_logout_deletes_session(web, settings):
    conn = connect(settings.db_path)
    tok = create_session(conn, 1, datetime.now(UTC))
    web.cookies.set("__Host-js_session", tok)
    r = web.post("/logout", headers={"Origin": "https://testserver"})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_startup_refuses_missing_auth_settings(settings):
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        create_app(settings.model_copy(update={"google_client_id": ""}))
```

- [ ] **Step 3: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_auth.py` → FAIL (ImportError: `jobseeker.db.sessions`).

- [ ] **Step 4: Implement**

`src/jobseeker/db/sessions.py`:
```python
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta

from jobseeker.db.core import iso
from jobseeker.db.users import User, user_by_id

SESSION_DAYS = 30
REFRESH_AFTER = timedelta(hours=24)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_id: int, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?,?,?,?,?)",
                 (_hash(token), user_id, iso(now), iso(now + timedelta(days=SESSION_DAYS)), iso(now)))
    conn.commit()
    return token


def user_for_token(conn: sqlite3.Connection, token: str, now: datetime) -> tuple[User, bool] | None:
    row = conn.execute("""SELECT s.token_hash, s.user_id, s.expires_at, s.last_seen_at, u.disabled_at
                          FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?""",
                       (_hash(token or ""),)).fetchone()
    if not row or row["expires_at"] <= iso(now) or row["disabled_at"]:
        return None
    refreshed = row["last_seen_at"] <= iso(now - REFRESH_AFTER)
    if refreshed:  # at most one write per session per day keeps reads lock-free
        conn.execute("UPDATE sessions SET expires_at = ?, last_seen_at = ? WHERE token_hash = ?",
                     (iso(now + timedelta(days=SESSION_DAYS)), iso(now), row["token_hash"]))
        conn.commit()
    return user_by_id(conn, row["user_id"]), refreshed


def delete_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token or ""),))
    conn.commit()


def delete_user_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()


def purge_expired(conn: sqlite3.Connection, now: datetime) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso(now),))
    conn.commit()
    return cur.rowcount
```

`src/jobseeker/web/deps.py`, adding:
```python
from datetime import UTC, datetime

from fastapi import Depends

from jobseeker.db.sessions import user_for_token
from jobseeker.db.users import User
from jobseeker.web.oauth import SESSION_COOKIE


class NotAuthenticated(Exception):
    pass


def optional_user(request: Request, conn=Depends(get_conn)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    found = user_for_token(conn, token, datetime.now(UTC)) if token else None
    if not found:
        return None
    user, refreshed = found
    if refreshed:
        request.state.refresh_session = token
    request.state.user = user
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise NotAuthenticated()
    return user
```

`src/jobseeker/web/auth.py`:
```python
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from jobseeker.db.sessions import create_session, delete_session, delete_user_sessions, purge_expired
from jobseeker.db.users import owner_first_name, resolve_sign_in
from jobseeker.web.deps import get_conn, optional_user
from jobseeker.web.oauth import (OAUTH_COOKIE, SESSION_COOKIE, TOKEN_URL, BadSignature, auth_url, local_path,
                                 pkce_pair, sign, unsign)

router = APIRouter()
SESSION_MAX_AGE = 30 * 24 * 3600


def exchange_code(settings, code: str, verifier: str) -> str:
    r = httpx.post(TOKEN_URL, timeout=10, data={
        "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
        "redirect_uri": f"{settings.base_url}/auth/callback", "grant_type": "authorization_code",
        "code_verifier": verifier})
    r.raise_for_status()
    return r.json()["id_token"]


def verify_id_token(token: str, client_id: str) -> dict:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, GoogleRequest(), client_id)  # signature, aud, iss, exp


def _page(request, status: int, message: str, conn=None):
    tpl = "not_invited.html" if status == 403 else "auth_message.html"
    ctx = {"message": message, "owner": owner_first_name(conn) if conn is not None else ""}
    return request.app.state.templates.TemplateResponse(request, tpl, ctx, status_code=status)


def _cookie(resp, name: str, value: str, max_age: int, settings) -> None:
    resp.set_cookie(name, value, max_age=max_age, path="/", secure=settings.cookie_secure, httponly=True,
                    samesite="lax")


@router.get("/login")
def login(request: Request, next: str = ""):
    s, now = request.app.state.settings, datetime.now(UTC)
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    resp = RedirectResponse(auth_url(s.google_client_id, f"{s.base_url}/auth/callback", state, nonce, challenge), 303)
    payload = {"state": state, "nonce": nonce, "verifier": verifier, "next": local_path(next) or "/"}
    _cookie(resp, OAUTH_COOKIE, sign(payload, s.secret_key, now, timedelta(minutes=10)), 600, s)
    return resp


@router.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", conn=Depends(get_conn)):
    s, now = request.app.state.settings, datetime.now(UTC)
    if error:
        return _page(request, 200, "Sign-in was cancelled.")
    try:
        data = unsign(request.cookies.get(OAUTH_COOKIE, ""), s.secret_key, now)
    except BadSignature:
        return _page(request, 400, "Sign-in expired, try again.")
    if not state or not secrets.compare_digest(state, data.get("state", "")):
        return _page(request, 400, "Sign-in expired, try again.")
    try:
        token = exchange_code(s, code, data["verifier"])
    except (httpx.HTTPError, KeyError, ValueError):
        return _page(request, 502, "Couldn't reach Google, try again.")
    try:
        claims = verify_id_token(token, s.google_client_id)
    except Exception:  # google-auth raises ValueError and friends for bad tokens
        return _page(request, 400, "Sign-in couldn't be verified.")
    if claims.get("nonce") != data.get("nonce") or claims.get("email_verified") is not True:
        return _page(request, 400, "Sign-in couldn't be verified.")
    user = resolve_sign_in(conn, claims["sub"], claims.get("email", ""), claims.get("name", ""), now)
    if user is None:
        return _page(request, 403, "This app is invite-only.", conn)
    if secrets.randbelow(100) == 0:
        purge_expired(conn, now)
    resp = RedirectResponse(local_path(data.get("next")) or "/", 303)
    _cookie(resp, SESSION_COOKIE, create_session(conn, user.id, now), SESSION_MAX_AGE, s)
    resp.delete_cookie(OAUTH_COOKIE, path="/", secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp


def _signed_out(request):
    resp = RedirectResponse("/login", 303)
    s = request.app.state.settings
    resp.delete_cookie(SESSION_COOKIE, path="/", secure=s.cookie_secure, httponly=True, samesite="lax")
    return resp


@router.post("/logout")
def logout(request: Request, conn=Depends(get_conn)):
    delete_session(conn, request.cookies.get(SESSION_COOKIE, ""))
    return _signed_out(request)


@router.post("/logout/all")
def logout_all(request: Request, user=Depends(optional_user), conn=Depends(get_conn)):
    if user is not None:
        delete_user_sessions(conn, user.id)
    return _signed_out(request)
```

Templates:
- `bare.html`: lines 1-19 of `base.html` (`{% from "_icons.html" import icon %}` through `</head>`), then `<body><main class="main bare">{% block content %}{% endblock %}</main></body></html>`.
- `auth_message.html`: `{% extends "bare.html" %}{% block content %}<div class="card block"><h1>Sign in</h1><p>{{ message }}</p><p><a class="btn btn-primary" href="/login">Try again</a></p></div>{% endblock %}`.
- `not_invited.html`: `{% extends "bare.html" %}{% block content %}<div class="card block"><h1>Job Seeker</h1><p>This app is invite-only. Ask {{ owner }} for an invite.</p></div>{% endblock %}`. Sub-project 6 restyles it on `landing.html`.

`src/jobseeker/web/app.py`, in `create_app`:
```python
    missing = [n for n in ("google_client_id", "google_client_secret", "base_url", "secret_key")
               if not getattr(settings, n)]
    if missing:
        raise RuntimeError("Set " + ", ".join(n.upper() for n in missing) + " in .env before starting the web app")
```
Then `from jobseeker.web import auth` and `app.include_router(auth.router)`, plus:
```python
    from urllib.parse import quote, urlsplit

    from fastapi.responses import RedirectResponse, Response

    from jobseeker.web.deps import NotAuthenticated
    from jobseeker.web.oauth import SESSION_COOKIE

    @app.exception_handler(NotAuthenticated)
    async def _signed_out(request, exc):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if request.headers.get("HX-Request"):
            current = request.headers.get("HX-Current-URL")
            path = urlsplit(current).path if current else target
            return Response(status_code=401, headers={"HX-Redirect": f"/login?next={quote(path)}"})
        return RedirectResponse(f"/login?next={quote(target)}", 303)

    @app.middleware("http")
    async def _refresh_session_cookie(request, call_next):
        response = await call_next(request)
        token = getattr(request.state, "refresh_session", None)
        if token:
            response.set_cookie(SESSION_COOKIE, token, max_age=30 * 24 * 3600, path="/",
                                secure=settings.cookie_secure, httponly=True, samesite="lax")
        return response
```

- [ ] **Step 5: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_auth.py` → PASS. Then the full pytest (no route is guarded yet, so the old web tests still pass) and node.

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/db/sessions.py src/jobseeker/web/auth.py src/jobseeker/web/deps.py src/jobseeker/web/app.py \
  src/jobseeker/web/templates/bare.html src/jobseeker/web/templates/auth_message.html \
  src/jobseeker/web/templates/not_invited.html tests/conftest.py tests/test_web_contacts.py tests/test_auth.py
git commit -m "feat(auth): Google sign-in with PKCE, DB sessions, logout

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 8: Guard every route; requests use the signed-in user

**Files:**
- Modify: `src/jobseeker/web/deps.py` (`owned_app`; `render` adds `user` and uses `user.id`)
- Modify: `src/jobseeker/web/app.py:63-66` (router dependencies)
- Modify: `src/jobseeker/web/inbox.py`, `pipeline.py`, `application.py`, `contacts.py` (replace `OWNER_ID` with `user.id`; `/` uses `optional_user`)
- Modify: `src/jobseeker/contacts/finder.py:233-243` (`run_find(db_path, app_id, user_id, prefs, deps_factory)` re-checks ownership)
- Modify: `src/jobseeker/web/templates/today.html:6` (`user.name`)
- Modify: `tests/conftest.py` (`client_as`, `anon_client` fixtures), and every `TestClient(create_app(...))` site (Step 4 list)
- Test: `tests/test_web_guards.py` (new)

**Interfaces:**
- Consumes: `current_user`, `optional_user`, `NotAuthenticated` (Task 7), `create_session` (Task 7).
- Produces:
  - `owned_app(app_id: int, user=Depends(current_user), conn=Depends(get_conn)) -> int`;
  - `PUBLIC: frozenset[str]` in `jobseeker.web.app`;
  - the fixture `client_as(user_id=1, *, follow_redirects=True, **app_kwargs) -> TestClient`, which sets the session cookie and `Origin: https://testserver`;
  - the fixture `anon_client(**app_kwargs) -> TestClient`.

- [ ] **Step 1: Add the fixtures** (`tests/conftest.py`):

```python
@pytest.fixture
def client_as(settings):
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from jobseeker.db.sessions import create_session
    from jobseeker.web.app import create_app

    def make(user_id: int = 1, *, follow_redirects: bool = True, **app_kwargs) -> TestClient:
        conn = connect(settings.db_path)
        token = create_session(conn, user_id, datetime.now(UTC))
        conn.close()
        return TestClient(create_app(settings, **app_kwargs), base_url="https://testserver",
                          follow_redirects=follow_redirects, headers={"Origin": "https://testserver"},
                          cookies={"__Host-js_session": token})
    return make


@pytest.fixture
def anon_client(settings):
    from fastapi.testclient import TestClient

    from jobseeker.web.app import create_app
    return lambda **kw: TestClient(create_app(settings, **kw), base_url="https://testserver", follow_redirects=False,
                                   headers={"Origin": "https://testserver"})
```

- [ ] **Step 2: Write the failing guard tests** (`tests/test_web_guards.py`):

```python
from fastapi.routing import APIRoute

from jobseeker.web.app import PUBLIC, create_app
from jobseeker.web.deps import current_user, optional_user, owned_app


def _calls(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _calls(d)


def test_every_route_is_guarded(settings):
    for r in create_app(settings).routes:
        if not isinstance(r, APIRoute) or r.path in PUBLIC:
            continue
        calls = set(_calls(r.dependant))
        if r.path == "/":
            assert optional_user in calls
            continue
        assert current_user in calls, f"{r.path} has no current_user"
        if "{app_id}" in r.path:
            assert owned_app in calls, f"{r.path} has no owned_app"


def test_anonymous_requests_are_sent_to_login(settings, seeded, anon_client):
    web, app_id = anon_client(), seeded[0]
    root = web.get("/")
    assert root.status_code == 303 and root.headers["location"] == "/login" and "Senior Product" not in root.text
    for r in create_app(settings).routes:
        if not isinstance(r, APIRoute) or r.path in PUBLIC or r.path == "/":
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
    for r in create_app(settings).routes:
        if isinstance(r, APIRoute) and "{app_id}" in r.path:
            path = r.path.replace("{app_id}", str(a)).replace("{kind}", "email").replace("{rank}", "1")
            for method in r.methods - {"HEAD"}:
                assert web.request(method, path).status_code == 404, (method, path)


def test_owner_still_sees_everything(seeded, client_as):
    web = client_as(1)
    assert web.get("/").status_code == 200
    assert web.get(f"/applications/{seeded[0]}").status_code == 200
```

- [ ] **Step 3: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_web_guards.py` → FAIL (`ImportError: PUBLIC` / `owned_app`).

- [ ] **Step 4: Implement**

`src/jobseeker/web/deps.py`:
```python
from fastapi import HTTPException


def owned_app(app_id: int, user: User = Depends(current_user), conn=Depends(get_conn)) -> int:
    if not conn.execute("SELECT 1 FROM applications WHERE id = ? AND user_id = ?", (app_id, user.id)).fetchone():
        raise HTTPException(404)  # 404, not 403: never confirm another user's ids exist
    return app_id


def render(request: Request, conn, name: str, **ctx):
    user = request.state.user  # set by optional_user/current_user on every guarded route
    run = last_run(conn, user.id)
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("err", request.query_params.get("err"))
    ctx["run_errors"] = json.loads(run["errors"]) if run else []
    ctx["run_notes"] = explain_run(ctx["run_errors"])
    ctx["run_finished"] = run["finished_at"] if run else None
    ctx["nav"] = nav_counts(conn, user.id)
    ctx["user"] = user
    return request.app.state.templates.TemplateResponse(request, name, ctx)
```

`src/jobseeker/web/app.py`:
```python
PUBLIC = frozenset({"/login", "/auth/callback", "/logout", "/logout/all", "/healthz", "/sw.js"})
```
and the includes:
```python
    from fastapi import Depends

    from jobseeker.web.deps import current_user, owned_app

    app.include_router(auth.router)
    app.include_router(inbox.router)  # "/" depends on optional_user itself
    app.include_router(application.router, dependencies=[Depends(owned_app)])
    app.include_router(contacts.router, dependencies=[Depends(owned_app)])
    app.include_router(pipeline.router, dependencies=[Depends(current_user)])
```
(`/static` is a mount, not an `APIRoute`, so the walk skips it.)

`src/jobseeker/web/inbox.py`:
```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from jobseeker.db import queries
from jobseeker.web.deps import get_conn, optional_user, render

router = APIRouter()


@router.get("/")
def inbox(request: Request, band: str = "apply", family: str = "", city: str = "", source: str = "",
          status: str = "", user=Depends(optional_user), conn=Depends(get_conn)):
    if user is None:  # sub-project 6 renders landing.html here
        return RedirectResponse("/login", 303)
    rows = queries.inbox(conn, user.id, band=band, family=family or None, city=city or None,
                         source=source or None, status=status or None)
    f = {"band": band, "family": family, "city": city, "source": source}
    return render(request, conn, "inbox.html", rows=rows, f=f, **queries.inbox_facets(conn, user.id))
```

`web/pipeline.py`: both routes add `user=Depends(current_user)` and pass `user.id` to `queries.pipeline`, `queries.stats` and `queries.today`.

`web/application.py` and `web/contacts.py`: every route that used `OWNER_ID` adds `user=Depends(current_user)` (cached per request, so it's free) and uses `user.id`. `card_context` reads `request.state.user.id` for the `Budget`. In `find` (`web/contacts.py:50`): `background.add_task(run_find, state.settings.db_path, app_id, user.id, state.prefs, deps_factory)`.

`src/jobseeker/contacts/finder.py:233`:
```python
def run_find(db_path: Path | str, app_id: int, user_id: int, prefs: Preferences, deps_factory: Callable[[], Deps]) -> None:
    """Background entry point: own connection, ownership re-checked, status recorded for the page to poll."""
    conn = connect(db_path)
    try:
        if not conn.execute("SELECT 1 FROM applications WHERE id = ? AND user_id = ?", (app_id, user_id)).fetchone():
            return
        ...  # the existing body unchanged
```
`tests/test_contacts_finder.py`: any `run_find(` call gets `1,` after `app_id` (`grep -n "run_find(" tests/`).

`templates/today.html:6`: `{% set first = (user.name or "").split()|first %}`.

**Switch every web test to a signed-in client.** In each file below, add `client_as` to the test function's parameters and replace the `TestClient(create_app(settings[, kwargs]), …)` expression with `client_as(1[, kwargs], follow_redirects=…)`, keeping the same kwargs and `follow_redirects` value. Drop `TestClient`/`create_app` imports that become unused:
- `tests/test_run_notes.py:36`;
- `tests/test_web_contacts_outreach.py:58, 195, 212` (the fixture at `:56` takes `client_as` and returns `client_as(1, gmail_factory=lambda: gmail, follow_redirects=False)`);
- `tests/test_web_inbox.py:17, 26, 32`;
- `tests/test_web_application.py:46, 92`;
- `tests/test_web_pipeline.py:24`;
- `tests/test_web_today.py:47, 56`;
- `tests/test_web_mobile.py:15`;
- `tests/test_web_contacts.py:19` (`client_as(1, contacts_deps_factory=deps, follow_redirects=False)`) and `:52` (it builds its own `Settings` `s`; use `TestClient(create_app(s), base_url="https://testserver", follow_redirects=False, headers={"Origin": "https://testserver"}, cookies={"__Host-js_session": create_session(connect(s.db_path), 1, datetime.now(UTC))})`);
- `tests/test_web_undo.py:70`;
- `tests/test_web_redesign.py` (`grep -n "TestClient(" tests/test_web_redesign.py`; each site the same way);
- `tests/test_web_view.py:64` uses `create_app(settings)` only to read templates: unchanged.

Then: `grep -rn "TestClient(create_app" tests/` must return only `tests/test_auth.py`, `tests/test_web_guards.py` and `tests/test_web_contacts.py:52`.

- [ ] **Step 5: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no` → all pass (the old web tests now run signed in as user 1). Node: 19.

- [ ] **Step 6: Commit** (the edited files by name)

```bash
git commit -m "feat(auth): every route guarded; owned_app 404s; requests act as the signed-in user

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 9: CSRF Origin check

**Files:**
- Create: `src/jobseeker/web/csrf.py`
- Modify: `src/jobseeker/web/app.py` (`app.add_middleware(OriginCheck, base_url=settings.base_url)`)
- Test: `tests/test_csrf.py`

**Interfaces:**
- Consumes: `client_as` (Task 8), which already sends `Origin`.
- Produces: `OriginCheck(app, base_url: str)`, an ASGI middleware.

- [ ] **Step 1: Write the failing tests** (`tests/test_csrf.py`):

```python
import pytest


@pytest.fixture
def web(client_as, seeded):
    c = client_as(1, follow_redirects=False)
    c.headers.pop("Origin")
    return c, seeded[0]


def test_foreign_origin_blocked(web):
    c, a = web
    r = c.post(f"/applications/{a}/notes", data={"notes": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.text == "Request blocked"


def test_missing_both_headers_blocked(web):
    c, a = web
    assert c.post(f"/applications/{a}/notes", data={"notes": "x"}).status_code == 403


def test_same_origin_fetch_metadata_allowed(web):
    c, a = web
    assert c.post(f"/applications/{a}/notes", data={"notes": "x"}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 303


def test_cross_site_fetch_metadata_blocked_even_with_origin(web):
    c, a = web
    r = c.post(f"/applications/{a}/notes", data={"notes": "x"},
               headers={"Origin": "https://testserver", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_get_never_blocked(web):
    c, a = web
    assert c.get(f"/applications/{a}", headers={"Origin": "https://evil.example"}).status_code == 200
```

- [ ] **Step 2: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_csrf.py` → FAIL (303 instead of 403).

- [ ] **Step 3: Implement** (`src/jobseeker/web/csrf.py`):

```python
"""CSRF: SameSite=Lax keeps the session cookie off cross-site POSTs; this refuses any state-changing request that
doesn't prove it came from our own pages (Origin or Fetch-Metadata), so no per-form tokens are needed."""
from __future__ import annotations

SAFE = {"GET", "HEAD", "OPTIONS"}


class OriginCheck:
    def __init__(self, app, base_url: str):
        self.app, self.base_url = app, base_url.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in SAFE:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            site, origin = headers.get("sec-fetch-site"), headers.get("origin")
            blocked = (site in ("cross-site", "same-site") or (origin is not None and origin != self.base_url)
                       or (site != "same-origin" and origin is None))
            if blocked:
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": b"Request blocked"})
                return
        await self.app(scope, receive, send)
```
`src/jobseeker/web/app.py`, after the routers: `app.add_middleware(OriginCheck, base_url=settings.base_url)`, with `from jobseeker.web.csrf import OriginCheck`.

- [ ] **Step 4: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no` → all pass. This includes `test_auth.py::test_logout_deletes_session`, which sends `Origin`. Node: 19.

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/web/csrf.py src/jobseeker/web/app.py tests/test_csrf.py
git commit -m "feat(security): Origin/Fetch-Metadata CSRF check on every state-changing request

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 10: The admin page (invites, users, usage)

**Files:**
- Create: `src/jobseeker/web/admin.py`, `src/jobseeker/web/templates/admin.html`
- Modify: `src/jobseeker/web/deps.py` (`require_admin`)
- Modify: `src/jobseeker/web/app.py` (include `admin.router`)
- Modify: `src/jobseeker/web/templates/base.html:43-47` (an admin link and Sign out in the sidebar foot; Sign out in the phone top bar)
- Modify: `tests/test_web_guards.py` (the admin assertion)
- Test: `tests/test_admin.py`

**Interfaces:**
- Consumes: `list_invites`, `add_invite`, `remove_invite`, `list_users`, `set_disabled`, `LastAdmin` (Task 6).
- Produces: `require_admin(user=Depends(current_user)) -> User`; `usage_table(conn, now) -> dict` with keys `{"services": [...], "rows": [{"user": dict, "values": {service: amount}}]}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_admin.py`):

```python
from urllib.parse import unquote

from jobseeker.db.core import connect


def test_non_admin_gets_404(seeded_two, client_as):
    c = client_as(2, follow_redirects=False)
    assert c.get("/admin").status_code == 404
    assert c.post("/admin/invites", data={"email": "x@example.com"}).status_code == 404


def test_invite_add_remove(seeded_two, client_as, settings):
    c = client_as(1, follow_redirects=False)
    assert c.post("/admin/invites", data={"email": "New@Example.com"}).status_code == 303
    assert connect(settings.db_path).execute("SELECT email FROM invites").fetchone()[0] == "new@example.com"
    c.post("/admin/invites/new@example.com/remove")
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM invites").fetchone()[0] == 0


def test_disable_deletes_sessions_and_last_admin_refused(seeded_two, client_as, settings):
    roomie = client_as(2)
    owner = client_as(1, follow_redirects=False)
    assert owner.post("/admin/users/2/disable").status_code == 303
    assert roomie.get("/today", follow_redirects=False).status_code == 303  # signed out
    r = owner.post("/admin/users/1/disable")
    assert "at least one admin" in unquote(r.headers["location"])


def test_usage_table_per_user(seeded_two, client_as):
    html = client_as(1).get("/admin").text
    assert "roomie@example.com" in html and "tavily" in html.lower()
```
In `tests/test_web_guards.py::test_every_route_is_guarded`, add before the `{app_id}` check:
```python
        if r.path.startswith("/admin"):
            assert require_admin in calls, f"{r.path} has no require_admin"
```
and import `require_admin`.

- [ ] **Step 2: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_admin.py` → FAIL (404 for the owner: no route).

- [ ] **Step 3: Implement**

`src/jobseeker/web/deps.py`:
```python
def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(404)
    return user
```

`src/jobseeker/web/admin.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from jobseeker.db.users import LastAdmin, add_invite, list_invites, list_users, remove_invite, set_disabled
from jobseeker.web.deps import get_conn, render, require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _back(msg: str = "", err: str = ""):
    q = f"?msg={quote(msg)}" if msg else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(f"/admin{q}", 303)


def usage_table(conn, now: datetime) -> dict:
    periods = (now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"))
    rows = conn.execute("SELECT user_id, service, amount FROM usage WHERE period IN (?, ?)", periods).fetchall()
    services = sorted({r["service"] for r in rows})
    by_user = {u["id"]: {"user": u, "values": {}} for u in list_users(conn)}
    for r in rows:
        if r["user_id"] in by_user:
            by_user[r["user_id"]]["values"][r["service"]] = r["amount"]
    return {"services": services, "rows": list(by_user.values())}


@router.get("")
def page(request: Request, conn=Depends(get_conn)):
    return render(request, conn, "admin.html", invites=list_invites(conn), users=list_users(conn),
                  usage=usage_table(conn, datetime.now(UTC)))


@router.post("/invites")
def invite(request: Request, email: str = Form(...), conn=Depends(get_conn)):
    if "@" not in email:
        return _back(err="Enter an email address")
    add_invite(conn, email, request.state.user.id, datetime.now(UTC))
    return _back(msg=f"Invited {email.strip().lower()}. Send them the link yourself")


@router.post("/invites/{email}/remove")
def uninvite(email: str, conn=Depends(get_conn)):
    remove_invite(conn, email)
    return _back(msg="Invite removed")


@router.post("/users/{user_id}/disable")
def disable(user_id: int, conn=Depends(get_conn)):
    try:
        set_disabled(conn, user_id, True, datetime.now(UTC))
    except LastAdmin as e:
        return _back(err=str(e))
    return _back(msg="User disabled and signed out")


@router.post("/users/{user_id}/enable")
def enable(user_id: int, conn=Depends(get_conn)):
    set_disabled(conn, user_id, False, datetime.now(UTC))
    return _back(msg="User enabled")
```

`templates/admin.html` (`ui.css` cards). It extends `base.html` and has three cards:
- **Invites:** a table of email / invited / accepted with a Remove `<form method="post">`, plus the add form with `<input type="email" name="email" required>` and an "Invite" button;
- **Users:** a table of email / name / last login / status, with Disable or Enable forms;
- **Usage:** today's and this month's numbers, with `usage.services` as the columns and each row's `values.get(s, 0)`.

Use the existing classes `card block`, `section-title`, `btn`, `btn-ghost` and `muted`. A footnote reads "Daily services show today, monthly services this month." Sub-project 6 adds a "Backups" card here.

`templates/base.html`, the sidebar foot (`:46`) becomes:
```html
    <div class="sidebar-foot">{{ run_notes_box() }}
      {% if user and user.is_admin %}<a class="nav-item" href="/admin">{{ icon("people") }}<span>Admin</span></a>{% endif %}
      {% if user %}<form method="post" action="/logout"><button class="btn-ghost">Sign out</button></form>{% endif %}
    </div>
```
and the top bar (`:49`) gets `{% if user %}<form method="post" action="/logout" class="topbar-signout"><button class="btn-ghost" aria-label="Sign out">Sign out</button></form>{% endif %}` after `run_notes_box()`. Spec 2 asks for Sign out "under the existing More menu", but there's no app-level More menu, so it goes in the sidebar foot and the phone top bar until sub-project 3's Settings tab takes over.

`src/jobseeker/web/app.py`: `from jobseeker.web import admin` and `app.include_router(admin.router)`.

- [ ] **Step 4: Run the suites**

Run: `FORCE_COLOR= uv run pytest --color=no` → all pass (including `tests/test_web_mobile.py`'s phone-layout checks). Node: 19.

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/web/admin.py src/jobseeker/web/templates/admin.html src/jobseeker/web/deps.py \
        src/jobseeker/web/app.py src/jobseeker/web/templates/base.html tests/test_admin.py tests/test_web_guards.py
git commit -m "feat(admin): invites, users and per-user usage; sign-out controls

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 11: Web isolation tests, acceptance checks and handoff

**Files:**
- Modify: `tests/test_isolation.py` (append the web-level tests)
- Modify: `HANDOFF.md` (a sub-project 2 status line, the new env vars, `jobseeker migrate`)

- [ ] **Step 1: Write the tests** (append to `tests/test_isolation.py`):

```python
def test_roommate_pages_show_only_their_rows(seeded_two, client_as):
    web = client_as(2)
    inbox = web.get("/?band=all").text
    assert f"/applications/{seeded_two['roommate_app']}" in inbox
    assert f"/applications/{seeded_two['owner_apps'][0]}" not in inbox
    assert f"/applications/{seeded_two['owner_apps'][0]}" not in web.get("/pipeline").text
    assert f"/applications/{seeded_two['owner_apps'][0]}" not in web.get("/today").text


def test_owner_pages_unchanged_by_roommate(seeded_two, client_as):
    web = client_as(1)
    assert f"/applications/{seeded_two['roommate_app']}" not in web.get("/?band=all").text
    assert web.get(f"/applications/{seeded_two['owner_apps'][0]}").status_code == 200


def test_owner_find_contacts_ignores_roommate_blocklist(seeded_two, settings):
    from jobseeker.db.contacts_repo import blocked_profile_urls
    conn = connect(settings.db_path)
    cid = conn.execute("INSERT INTO contacts (company, name, linkedin_url) VALUES ('CRED', 'A', 'https://li/a')").lastrowid
    conn.execute("INSERT INTO blocklist (user_id, contact_id, reason, at) VALUES (2, ?, 'not interested', 't')", (cid,))
    conn.commit()
    assert blocked_profile_urls(conn, 2, "CRED") == {"https://li/a"}
    assert blocked_profile_urls(conn, 1, "CRED") == set()
```

- [ ] **Step 2: Run them**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_isolation.py`. Expected: PASS. If a page leaks, fix the query that renders it, not the test.

- [ ] **Step 3: The acceptance checks** (manual; no commit for the data):
1. `mkdir -p /tmp/jsacc/data && sqlite3 "/Users/user/Desktop/untitled folder/job-seeker2.0/data/jobseeker.db" ".backup /tmp/jsacc/data/jobseeker.db"`.
2. `JOBSEEKER_HOME=/tmp/jsacc OWNER_EMAIL=mkshitij1763@gmail.com uv run jobseeker migrate`. Expected: "Applied v1", unchanged counts.
3. `JOBSEEKER_HOME=/tmp/jsacc uv run python -c "from jobseeker.db.core import connect; c=connect('/tmp/jsacc/data/jobseeker.db'); print(c.execute('PRAGMA foreign_key_check').fetchall())"` → `[]`.
4. Starting the web app against the **un-migrated** live copy must fail: `JOBSEEKER_HOME=/tmp/jsv0 …` with a fresh `.backup` → `SchemaOutOfDate`.
5. Temporarily add a route without guards to `web/inbox.py` and run `tests/test_web_guards.py`: it must FAIL. Then remove the route.
6. **Real Google sign-in** needs the Web OAuth client (hosting checklist). It's checked at deploy time, not here.

- [ ] **Step 4: Full suites, then update `HANDOFF.md`**

Run: `FORCE_COLOR= uv run pytest --color=no` and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`. Record the new pytest count.
In `HANDOFF.md`, add under §8 a "Sub-project 2 built" bullet list:
- the new env vars;
- `jobseeker migrate` (stop the web service and timer first);
- the fact that the live Mac app stays on `main` until cutover;
- the new test count.

- [ ] **Step 5: Commit**

```bash
git add tests/test_isolation.py HANDOFF.md
git commit -m "test(auth): web-level isolation; handoff for sub-project 2

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

Then hand off for the whole-branch review (Native method: one fresh reviewer on the most capable model checks `git diff 4a029ff..HEAD`).

---

## Spec coverage (self-review)

| Spec 2 section | Task |
|---|---|
| §3 decisions; `google-auth` direct | 6 |
| §4.1 config + startup refusal | 6, 7 |
| §4.2 sign-in flow | 6 (primitives), 7 (routes) |
| §4.3 resolver, invites, admin, last admin | 6, 10 |
| §4.4 sessions, sliding expiry, purge | 7 |
| §4.5 CSRF | 9 |
| §4.6 logout, unauthenticated 303/401 | 7, 8 |
| §4.7 guards, PUBLIC, `/` mixed route, `run_find` re-check, `render` user | 8 |
| §4.8 data access takes `user_id` | 3, 4, 5 |
| §4.9 migrate framework, SchemaOutOfDate, startup check | 1, 3 |
| §4.10 migration v1 and post-checks | 2, 3 |
| §5 data model | 2, 3 |
| §6 errors | 1, 2, 7, 9, 10 |
| §7 testing | every task; isolation 5 and 11; guards 8 |
| §8 acceptance | 11 |

**Clarifications this plan adds to the spec** (flagged to the coordinator):
1. A fresh DB seeds a placeholder owner `users(1, email='')`, filled by `ensure_owner` from `OWNER_EMAIL` at web/CLI start. Without it, foreign keys would reject the owner's first application on a new database.
2. `schema_v0.sql` lives in `src/jobseeker/db/` (needed at runtime for the v0 catch-up), not under `tests/fixtures/`.
3. `db/backup.py` gains `snapshot(db_path, out)`, which devops-lead's nightly backup should reuse.
4. Sign out goes in the sidebar foot and the phone top bar (there's no app-level More menu) until spec 3's Settings.
5. A cancelled Google consent shows `auth_message.html`, because `/login` redirects straight to Google and couldn't show a message itself.
6. `set_filter_reason` and `set_prescore` keep their names (now on `user_jobs`) instead of the spec's single `set_user_job`, which means less churn for the same behaviour.
