from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.migrations import MIGRATIONS, latest
from jobseeker.db.runs import start_run


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_v4_registered():
    assert [m.name for m in MIGRATIONS if m.version == 4] == ["pipeline"] and latest() >= 4


def test_fresh_shape(tmp_path):
    conn = connect(tmp_path / "f.db")
    assert {"trigger", "parent_id", "kind", "user_id"} <= _cols(conn, "runs")
    assert "profile_hash" in _cols(conn, "scores")
    assert _cols(conn, "locks") == {"name", "holder", "acquired_at", "heartbeat_at"}
    assert _cols(conn, "run_requests") == {"id", "user_id", "requested_at", "status", "run_id", "finished_at",
                                         "trigger"}


def test_start_run_records_trigger_and_parent(tmp_path):
    conn = connect(tmp_path / "f.db")
    now = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)
    fetch = start_run(conn, now, None, kind="fetch", trigger="schedule")
    user = start_run(conn, now, 1, kind="user", trigger="schedule", parent_id=fetch)
    row = conn.execute("SELECT kind, trigger, parent_id, user_id FROM runs WHERE id = ?", (user,)).fetchone()
    assert tuple(row) == ("user", "schedule", fetch, 1)


def test_backfill_keeps_owner_scores_fresh(migrated_owner_db):
    """`migrated_owner_db` is spec 2/3's fixture that migrates the v0 fixture DB plus the fixture profile/ to latest.
    The v4 back-fill must equal the runtime hash, so the owner's existing scores aren't all stale at once."""
    from jobseeker.config import load_app_config
    from jobseeker.db.profile import load_user_context
    from jobseeker.pipeline.profile_hash import profile_hash

    conn, home = migrated_owner_db
    prefs, facts = load_user_context(conn, 1, load_app_config(home / "config" / "app.yaml"))
    hashes = {r[0] for r in conn.execute("SELECT profile_hash FROM scores WHERE user_id = 1")}
    assert hashes == {profile_hash(prefs, facts)}
