from datetime import UTC, datetime, timedelta

from jobseeker.backup.nightly import BackupResult
from jobseeker.config import AppConfig
from jobseeker.db.core import connect
from jobseeker.db.locks import acquire
from jobseeker.db.runs import finish_run, start_run
from jobseeker.pipeline.run import RunReport
from jobseeker.pipeline.tick import scheduled_due, tick

CFG = AppConfig()
OK = BackupResult(None, True, True, None)


def _db(tmp_path):
    conn = connect(tmp_path / "db")
    conn.execute("UPDATE user_prefs SET onboarded_at = 't' WHERE user_id = 1")  # the owner is active
    conn.commit()
    return conn


def _tick(conn, now, *, report=None, backup=lambda c, s, n: OK, pings=None, runs=None):
    def run(trigger, users, plan_cap):
        (runs if runs is not None else []).append((trigger, [u.id for u in users], plan_cap))
        rid = start_run(conn, now, None, kind="fetch", trigger=trigger)
        finish_run(conn, rid, {}, [], now)
        return report or RunReport(fetch_run_id=rid)
    return tick(conn, settings=None, cfg=CFG, now=now, run=run, backup=backup,
                ping_fn=lambda url, ok: (pings if pings is not None else []).append(ok), holder="me:1")


def test_schedule_due_in_ist(tmp_path):
    conn = _db(tmp_path)
    assert not scheduled_due(conn, CFG, datetime(2026, 10, 11, 5, 44, tzinfo=UTC))
    assert scheduled_due(conn, CFG, datetime(2026, 10, 11, 5, 45, tzinfo=UTC))
    assert scheduled_due(conn, CFG, datetime(2026, 10, 11, 17, 30, tzinfo=UTC))  # catch-up after downtime
    rid = start_run(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), None, kind="fetch", trigger="schedule")
    finish_run(conn, rid, {}, [], datetime(2026, 10, 11, 6, 30, tzinfo=UTC))
    assert not scheduled_due(conn, CFG, datetime(2026, 10, 11, 7, 0, tzinfo=UTC))
    assert scheduled_due(conn, CFG, datetime(2026, 10, 12, 5, 50, tzinfo=UTC))  # next IST day


def test_crashed_attempts_retry_at_most_twice(tmp_path):
    conn = _db(tmp_path)
    t = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)
    start_run(conn, t, None, kind="fetch", trigger="schedule")  # crashed: never finished
    assert scheduled_due(conn, CFG, t + timedelta(minutes=30))
    start_run(conn, t + timedelta(minutes=30), None, kind="fetch", trigger="schedule")
    assert not scheduled_due(conn, CFG, t + timedelta(hours=2))


def test_scheduled_tick_runs_backup_and_pings(tmp_path):
    conn = _db(tmp_path)
    runs, pings = [], []
    assert _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), runs=runs, pings=pings) == "scheduled"
    assert runs == [("schedule", [1], 60)] and pings == [True]


def test_failed_run_still_backs_up_and_pings_fail(tmp_path):
    conn = _db(tmp_path)
    backups, pings = [], []
    _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), report=RunReport(aborted="run aborted: X"),
          backup=lambda c, s, n: backups.append(1) or OK, pings=pings)
    assert backups == [1] and pings == [False]


def test_backup_not_ok_or_raising_pings_fail(tmp_path):
    for backup in (lambda c, s, n: BackupResult(None, False, False, "HTTP 500"),
                   lambda c, s, n: (_ for _ in ()).throw(OSError("disk"))):
        conn = _db(tmp_path / str(id(backup)))
        pings = []
        _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), backup=backup, pings=pings)
        assert pings == [False]


def test_skipped_backup_counts_as_ok(tmp_path):
    conn = _db(tmp_path)
    pings = []
    _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), backup=lambda c, s, n: BackupResult(None, True, True, None, True),
          pings=pings)
    assert pings == [True]


def test_fetch_now_runs_one_user_without_backup_or_ping(tmp_path):
    from jobseeker.db.run_requests import queue
    conn = _db(tmp_path)
    now = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)  # before 11:15 IST, so nothing scheduled
    queue(conn, 1, now)
    runs, pings, backups = [], [], []
    assert _tick(conn, now, runs=runs, pings=pings, backup=lambda c, s, n: backups.append(1) or OK) == "fetch_now"
    assert runs == [("fetch_now", [1], 30)] and pings == [] and backups == []
    assert conn.execute("SELECT status FROM run_requests").fetchone()[0] == "done"


def test_busy_lock_exits_quietly(tmp_path):
    conn = _db(tmp_path)
    acquire(conn, "run", "other:2", datetime(2026, 10, 11, 5, 40, tzinfo=UTC), 15)
    assert _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC)) == "busy"


def test_stuck_running_request_is_failed_after_takeover(tmp_path):
    from jobseeker.db.run_requests import mark, queue
    conn = _db(tmp_path)
    t = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)
    mark(conn, queue(conn, 1, t), "running", t)
    _tick(conn, t + timedelta(minutes=20))
    assert conn.execute("SELECT status FROM run_requests").fetchone()[0] == "failed"
