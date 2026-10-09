import sqlite3

import pytest

from jobseeker.db.core import connect
from jobseeker.db.migrations import MIGRATIONS, latest


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_v3_is_registered_as_extras():
    assert any(m.version == 3 and m.name == "extras" for m in MIGRATIONS)
    assert latest() >= 3


def test_fresh_db_has_v3_shapes(tmp_path):
    conn = connect(tmp_path / "f.db")
    assert _cols(conn, "push_subscriptions") == {"id", "user_id", "endpoint", "p256dh", "auth", "user_agent",
                                                 "created_at", "last_success_at", "failures"}
    assert "notified_on" in _cols(conn, "users")
    assert _cols(conn, "backups") == {"day", "local_path", "size_bytes", "uploaded_at", "upload_error", "created_at"}


def test_endpoint_unique_and_user_required(tmp_path):
    conn = connect(tmp_path / "f.db")
    # a fresh DB already has the placeholder owner, user 1
    row = ("https://p/1", "k", "a", "now")
    conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) VALUES (1,?,?,?,?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) VALUES (1,?,?,?,?)",
                     row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) VALUES ('https://p/2','k','a','n')")
