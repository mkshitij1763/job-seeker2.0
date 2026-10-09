from datetime import UTC, datetime, timedelta

from jobseeker.config import AppConfig
from jobseeker.db.core import connect
from jobseeker.db.locks import acquire
from jobseeker.db.runs import finish_run, start_run
from jobseeker.web.fetch_now import fetch_now_state

CFG = AppConfig()
NOW = datetime(2026, 10, 11, 8, 35, tzinfo=UTC)  # 14:05 IST


def test_queue_then_already_queued(client_as, settings):
    c = client_as(1, follow_redirects=False)
    r = c.post("/fetch-now")
    assert r.status_code == 303 and "Queued" in r.headers["location"] or "queued" in r.headers["location"].lower()
    r = c.post("/fetch-now")
    assert "Already%20queued" in r.headers["location"] or "Already queued" in r.headers["location"]
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM run_requests").fetchone()[0] == 1


def test_wait_two_hours_since_last_start(settings):
    conn = connect(settings.db_path)
    rid = start_run(conn, NOW - timedelta(minutes=30), 1, kind="user", trigger="fetch_now")
    finish_run(conn, rid, {}, [], NOW)
    s = fetch_now_state(conn, 1, NOW, CFG)
    assert s["state"] == "wait" and s["text"] == "Next possible at 15:35"


def test_global_daily_limit(settings):
    conn = connect(settings.db_path)
    for i in range(6):
        start_run(conn, NOW - timedelta(minutes=i), None, kind="fetch", trigger="fetch_now")
    assert fetch_now_state(conn, 2, NOW, CFG)["state"] == "used_up"


def test_queued_while_locked_says_after_current_run(client_as, settings):
    conn = connect(settings.db_path)
    acquire(conn, "run", "x:1", datetime.now(UTC), 15)
    r = client_as(1, follow_redirects=False).post("/fetch-now")
    assert "after the current run" in r.headers["location"].replace("%20", " ")


def test_status_fragment_polls_only_while_pending(client_as):
    c = client_as(1)
    assert 'hx-trigger="every 10s"' not in c.get("/fetch-now/status").text
    c.post("/fetch-now")
    assert 'hx-trigger="every 10s"' in c.get("/fetch-now/status").text


def test_requires_session(anon_client):
    assert anon_client().post("/fetch-now", follow_redirects=False).status_code in (303, 401)


def test_pages_load_the_fetch_now_slot(client_as):
    c = client_as(1)
    for page in ("/today", "/settings"):
        assert 'hx-get="/fetch-now/status"' in c.get(page).text, page


def _users(conn, ids):
    for u in ids:
        conn.execute("INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, 't')", (u, f"u{u}@x"))
    conn.commit()


def test_queued_requests_count_toward_the_daily_cap(settings):
    from jobseeker.web.fetch_now import queue_if_allowed
    conn = connect(settings.db_path)
    _users(conn, (2, 3, 4))
    for i in range(5):  # 5 of 6 used today
        start_run(conn, NOW - timedelta(minutes=i), None, kind="fetch", trigger="fetch_now")
    states = [queue_if_allowed(conn, u, NOW, CFG)["state"] for u in (1, 2, 3, 4)]
    assert states == ["ready", "used_up", "used_up", "used_up"]
    assert conn.execute("SELECT COUNT(*) FROM run_requests").fetchone()[0] == 1


def test_concurrent_double_post_queues_one_row(settings, monkeypatch):
    import threading

    from jobseeker.db import run_requests
    from jobseeker.web.fetch_now import queue_if_allowed
    real, gate = run_requests.pending, threading.Barrier(2, timeout=5)

    def slow_pending(conn, user_id):  # both requests read "nothing pending" before either inserts, if unguarded
        row = real(conn, user_id)
        try:
            gate.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass
        return row

    monkeypatch.setattr(run_requests, "pending", slow_pending)
    results = []

    def post():
        c = connect(settings.db_path)
        results.append(queue_if_allowed(c, 1, NOW, CFG)["state"])
        c.close()

    threads = [threading.Thread(target=post) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert sorted(results) == ["queued", "ready"]
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM run_requests").fetchone()[0] == 1


def test_one_pending_request_per_user_in_the_schema(settings):
    import sqlite3

    import pytest
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO run_requests (user_id, requested_at, status) VALUES (1, 't', 'queued')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO run_requests (user_id, requested_at, status) VALUES (1, 't', 'running')")
    conn.execute("INSERT INTO run_requests (user_id, requested_at, status) VALUES (1, 't', 'done')")  # history is fine
