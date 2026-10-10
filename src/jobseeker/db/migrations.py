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


MIGRATIONS: list[Migration] = []


def latest(migrations: list[Migration] | None = None) -> int:
    ms = MIGRATIONS if migrations is None else migrations
    return ms[-1].version if ms else 0


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def _version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _check_not_busy(db_path: Path, busy_timeout: float) -> None:
    probe = sqlite3.connect(db_path, timeout=busy_timeout)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.rollback()
    except sqlite3.OperationalError as e:
        raise DatabaseBusy("Database is busy: stop jobseeker-web and the tick timer first") from e
    finally:
        probe.close()


def migrate(db_path: Path, ctx: MigrationContext, backup_dir: Path, *, migrations: list[Migration] | None = None,
            dry_run: bool = False, busy_timeout: float = 5.0) -> list[str]:
    """Back up, then apply every pending migration in its own transaction with foreign keys off; a failed
    foreign_key_check rolls that migration back. dry_run migrates a temporary copy and leaves the file untouched."""
    from jobseeker.db.backup import snapshot
    from jobseeker.db.core import connect

    ms = MIGRATIONS if migrations is None else migrations
    db_path = Path(db_path)
    _check_not_busy(db_path, busy_timeout)
    if dry_run:
        tmp = Path(tempfile.mkdtemp())
        try:
            work = snapshot(db_path, tmp / db_path.name)
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
            conn.execute("PRAGMA foreign_keys = OFF")  # only takes effect outside a transaction
            conn.execute("BEGIN IMMEDIATE")
            try:
                notes = mig.apply(conn, ctx) or []
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
            report += [f"  v{mig.version}: {n}" for n in notes]
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("integrity_check failed after migrating")
        after = table_counts(conn)
        report += [f"  {t}: {before.get(t, '-')} -> {after.get(t, '-')}" for t in sorted(set(before) | set(after))]
        return report
    finally:
        conn.close()


# ---- v1: users and per-user scoping. Frozen: schema.sql moves on, this DDL never changes. ----
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

# user_id NOT NULL with no DEFAULT on purpose: an INSERT that forgets it must fail, never file the row under the owner.
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
V1_INDEXES = "CREATE INDEX idx_scores_user_job ON scores (user_id, job_id, id)"
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


MIGRATIONS.append(Migration(1, "users and scoping", migrate_v1))


V2_DDL = """
CREATE TABLE user_prefs (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  data TEXT NOT NULL,
  version INTEGER NOT NULL,
  onboarding_step TEXT,
  onboarded_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE user_facts (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  resume_sha256 TEXT,
  facts TEXT,
  edited INTEGER NOT NULL DEFAULT 0,
  extract_status TEXT NOT NULL DEFAULT 'idle' CHECK (extract_status IN ('idle', 'running', 'done', 'failed')),
  extract_error TEXT NOT NULL DEFAULT '',
  extract_started_at TEXT,
  resume_uploaded_at TEXT,
  updated_at TEXT NOT NULL
);
"""


def migrate_v2(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    """Per-user preferences and facts; the owner's profile/ files are imported (golden-checked) when present."""
    from jobseeker.profile.importer import import_profile  # the importer needs MigrationError from here

    for stmt in V2_DDL.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    import_profile(conn, 1, ctx.home / "profile", ctx.home, ctx.now)


MIGRATIONS.append(Migration(2, "preferences, facts and resume", migrate_v2))


def migrate_v3(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    """Push subscriptions, the per-user daily alert marker and the backup log (extras)."""
    conn.execute("""CREATE TABLE push_subscriptions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        user_agent TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_success_at TEXT,
        failures INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("CREATE INDEX idx_push_subscriptions_user ON push_subscriptions (user_id)")
    conn.execute("ALTER TABLE users ADD COLUMN notified_on TEXT")
    conn.execute("""CREATE TABLE backups (
        day TEXT PRIMARY KEY,
        local_path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        uploaded_at TEXT,
        upload_error TEXT,
        created_at TEXT NOT NULL)""")


MIGRATIONS.append(Migration(3, "extras", migrate_v3))


def migrate_v4(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    """Run triggers and parents, the heartbeat lock, Fetch-now requests, and scores.profile_hash (back-filled)."""
    conn.execute("ALTER TABLE runs ADD COLUMN trigger TEXT NOT NULL DEFAULT 'cli'")
    conn.execute("ALTER TABLE runs ADD COLUMN parent_id INTEGER REFERENCES runs(id)")
    conn.execute("ALTER TABLE scores ADD COLUMN profile_hash TEXT")
    conn.execute("""CREATE TABLE locks (name TEXT PRIMARY KEY, holder TEXT NOT NULL, acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE run_requests (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    requested_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
                    run_id INTEGER REFERENCES runs(id), finished_at TEXT)""")
    conn.execute("CREATE INDEX idx_run_requests_status ON run_requests (status, requested_at)")
    # One queued-or-running request per user (security review #2; added to v4 in place, before v4 shipped anywhere).
    conn.execute("CREATE UNIQUE INDEX idx_run_requests_one_pending ON run_requests (user_id) "
                 "WHERE status IN ('queued', 'running')")
    conn.execute("CREATE INDEX idx_runs_kind ON runs (kind, trigger, started_at)")
    # When each ATS board last fetched OK, so Fetch now can skip fresh ones (trial run fix 3; added to v4 in place).
    conn.execute("CREATE TABLE board_fetches (board TEXT PRIMARY KEY, last_fetched_at TEXT NOT NULL)")
    from jobseeker.config import load_app_config
    from jobseeker.db.profile import load_user_context
    from jobseeker.pipeline.profile_hash import profile_hash

    prefs, facts = load_user_context(conn, 1, load_app_config(ctx.home / "config" / "app.yaml"))
    if facts is not None:  # an owner who hasn't onboarded has nothing to back-fill
        conn.execute("UPDATE scores SET profile_hash = ? WHERE user_id = 1", (profile_hash(prefs, facts),))


MIGRATIONS.append(Migration(4, "pipeline", migrate_v4))


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
CREATE TABLE user_company_domains (
  user_id INTEGER NOT NULL REFERENCES users (id),
  name_norm TEXT NOT NULL,
  domain TEXT NOT NULL,
  set_at TEXT NOT NULL,
  PRIMARY KEY (user_id, name_norm)
);
"""


def migrate_v5(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    """Per-user outreach: the switch, private vs shared contacts, the people-search cache, Gmail tokens and
    per-user email-domain overrides."""
    before = conn.execute("SELECT COUNT(*) FROM application_contacts").fetchone()[0]
    for stmt in V5_DDL.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    dangling = conn.execute("""SELECT COUNT(*) FROM application_contacts ac LEFT JOIN contacts c ON c.id = ac.contact_id
                               WHERE c.id IS NULL""").fetchone()[0]
    if dangling or conn.execute("SELECT COUNT(*) FROM application_contacts").fetchone()[0] != before:
        raise MigrationError("v5: an application_contacts row lost its contact")


MIGRATIONS.append(Migration(5, "per-user outreach", migrate_v5))


# ---- v6: run request trigger; seniority words for users still on the old default exclusions ----
# The default title exclusions before v6, exactly as config/app.example.yaml shipped them (frozen).
OLD_DEFAULT_TITLE_DENY = ("sales", "sde", "software engineer", "intern", "internship", "director", "head of", "vp",
                          "vice president", "account executive", "recruiter", "designer", "design lead", "engineer",
                          "engineering", "developer", "architect", "product marketing")
SENIORITY_DENY = ("senior", "sr", "lead", "principal", "staff", "head")


def migrate_v6(conn: sqlite3.Connection, ctx: MigrationContext) -> list[str]:
    """Onboarding's first scoring run is a run request too ('onboarding' skips the fetch and is exempt from Fetch
    now's spacing and daily cap). Users whose saved exclusions are still exactly the old default get the new
    seniority words; a customised list, or none saved (it follows app.yaml), is left alone. The owner is never
    touched: the old default was copied from their list, and their target roles include senior ones (ruling by
    manager). Idempotent: an extended list no longer equals the old default."""
    import json

    conn.execute("ALTER TABLE run_requests ADD COLUMN trigger TEXT NOT NULL DEFAULT 'fetch_now' "
                 "CHECK (trigger IN ('fetch_now', 'onboarding'))")
    old, extended, kept, notes = sorted(OLD_DEFAULT_TITLE_DENY), 0, 0, []
    owners = {r[0] for r in conn.execute("SELECT id FROM users WHERE id = 1 OR lower(email) = ?",
                                         (ctx.owner_email.lower(),))}
    for row in conn.execute("SELECT user_id, data FROM user_prefs").fetchall():
        if row["user_id"] in owners:
            notes.append("owner skipped: customised by intent")
            continue
        data = json.loads(row["data"])
        deny = data.get("title_deny")
        if deny is None:
            continue
        if sorted(w.strip().lower() for w in deny) != old:
            kept += 1
            continue
        data["title_deny"] = list(deny) + [w for w in SENIORITY_DENY if w not in deny]
        conn.execute("UPDATE user_prefs SET data = ? WHERE user_id = ?", (json.dumps(data), row["user_id"]))
        extended += 1
    return notes + [f"seniority exclusions added for {extended} user{'' if extended == 1 else 's'} on the old default list "
            f"({kept} customised list{'' if kept == 1 else 's'} kept)"]


MIGRATIONS.append(Migration(6, "run request trigger, seniority exclusions", migrate_v6))
