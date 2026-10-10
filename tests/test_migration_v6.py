import json
from datetime import UTC, datetime

from jobseeker.db import run_requests
from jobseeker.db.core import connect
from jobseeker.db.migrations import MIGRATIONS, MigrationContext, OLD_DEFAULT_TITLE_DENY, SENIORITY_DENY, latest, migrate

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _at_v5(path):
    """A fresh DB rewound to v5: no run_requests.trigger yet."""
    conn = connect(path)
    conn.execute("ALTER TABLE run_requests DROP COLUMN trigger")
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    return conn


def _user(conn, uid, deny):
    if uid != 1:
        conn.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, 't')", (uid, f"u{uid}@x"))
    data = {"roles": ["Product Analyst"]} | ({} if deny is ... else {"title_deny": deny})
    conn.execute("INSERT OR REPLACE INTO user_prefs (user_id, data, version, updated_at) VALUES (?, ?, 1, 't')",
                 (uid, json.dumps(data)))


def _deny(conn, uid):
    return json.loads(conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (uid,)).fetchone()[0]).get(
        "title_deny", ...)


def test_v6_registered_and_fresh_shape(tmp_path):
    assert [m.name for m in MIGRATIONS if m.version == 6] == ["run request trigger, seniority exclusions"]
    assert latest() >= 6
    conn = connect(tmp_path / "f.db")
    assert "trigger" in _cols(conn, "run_requests")
    rid = run_requests.queue(conn, 1, NOW)
    assert conn.execute("SELECT trigger FROM run_requests WHERE id = ?", (rid,)).fetchone()[0] == "fetch_now"


def test_v6_adds_trigger_and_extends_only_untouched_default_lists(tmp_path):
    conn = _at_v5(tmp_path / "f.db")
    conn.execute("INSERT INTO run_requests (user_id, requested_at, status) VALUES (1, 't', 'done')")
    _user(conn, 1, list(OLD_DEFAULT_TITLE_DENY))           # the owner: never touched (ruling by manager)
    _user(conn, 5, ["sales", "intern"])                    # customised: untouched
    _user(conn, 2, list(OLD_DEFAULT_TITLE_DENY))           # the old default, never customised: extended
    _user(conn, 3, ...)                                    # no list saved (follows app.yaml): untouched
    _user(conn, 4, list(reversed(OLD_DEFAULT_TITLE_DENY)))  # same words, other order: still the default
    conn.commit()
    conn.close()
    report = migrate(tmp_path / "f.db", MigrationContext("o@x", NOW, tmp_path), tmp_path / "bk")
    assert "Applied v6: run request trigger, seniority exclusions" in report
    assert "  v6: owner skipped: customised by intent" in report
    assert "  v6: seniority exclusions added for 2 users on the old default list (1 customised list kept)" in report
    conn = connect(tmp_path / "f.db")
    assert conn.execute("SELECT trigger FROM run_requests").fetchone()[0] == "fetch_now"
    assert _deny(conn, 1) == list(OLD_DEFAULT_TITLE_DENY)
    assert _deny(conn, 5) == ["sales", "intern"]
    assert _deny(conn, 2) == list(OLD_DEFAULT_TITLE_DENY) + list(SENIORITY_DENY)
    assert _deny(conn, 3) is ...
    assert _deny(conn, 4)[-len(SENIORITY_DENY):] == list(SENIORITY_DENY)


def test_seniority_words_are_the_new_example_defaults():
    from jobseeker.config import REPO_ROOT, load_app_config
    cfg = load_app_config(REPO_ROOT / "config" / "app.example.yaml")
    assert cfg.default_title_deny == list(OLD_DEFAULT_TITLE_DENY) + list(SENIORITY_DENY)


def test_v6_seniority_step_is_idempotent(tmp_path):
    from jobseeker.db.migrations import migrate_v6
    conn = _at_v5(tmp_path / "f.db")
    _user(conn, 2, list(OLD_DEFAULT_TITLE_DENY))
    conn.commit()
    migrate_v6(conn, MigrationContext("o@x", NOW, tmp_path))
    conn.execute("ALTER TABLE run_requests DROP COLUMN trigger")  # replay the whole step
    again = migrate_v6(conn, MigrationContext("o@x", NOW, tmp_path))
    assert _deny(conn, 2) == list(OLD_DEFAULT_TITLE_DENY) + list(SENIORITY_DENY)
    assert again[-1].startswith("seniority exclusions added for 0 users")
