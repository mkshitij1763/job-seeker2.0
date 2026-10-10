"""A deploy (or a variables change) SIGTERMs a running tick. The run must close its log, free the lock and fail the
Fetch now request with a reason the user sees, instead of leaving a dead lock that blocks every tick for 15 minutes."""
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.config import AppConfig
from jobseeker.db import run_requests
from jobseeker.db.core import connect
from jobseeker.db.locks import acquire
from jobseeker.db.run_requests import INTERRUPTED
from jobseeker.db.runs import finish_run, start_run
from jobseeker.pipeline.tick import tick
from jobseeker.web.fetch_now import fetch_now_state
from tests.test_run import StaticSource, _run, handler
from tests.fakes import FakeLLM

CFG = AppConfig()
NOW = datetime(2026, 10, 11, 8, 35, tzinfo=UTC)  # 14:05 IST


def _active(conn, now):
    """The owner is onboarded and today's scheduled run is done, so the tick's next job is the Fetch now request."""
    conn.execute("UPDATE user_prefs SET onboarded_at = 't' WHERE user_id = 1")
    conn.commit()
    finish_run(conn, start_run(conn, now, None, kind="fetch", trigger="schedule"), {}, [], now)


def test_run_all_closes_its_runs_as_interrupted_and_reraises(prefs, rubric, facts):
    conn = connect(":memory:")
    with pytest.raises(SystemExit):
        _run(conn, [StaticSource("lever:cred", error=SystemExit(143))], FakeLLM(handler=handler), prefs, rubric, facts)
    row = conn.execute("SELECT finished_at, errors FROM runs WHERE kind = 'fetch'").fetchone()
    assert row["finished_at"] is not None and INTERRUPTED in json.loads(row["errors"])


def test_tick_frees_the_lock_and_fails_the_request_on_sigterm(tmp_path):
    conn = connect(tmp_path / "db")
    _active(conn, NOW)
    req = run_requests.queue(conn, 1, NOW)

    def run(trigger, users, plan_cap):
        rid = start_run(conn, NOW, None, kind="fetch", trigger=trigger)
        finish_run(conn, rid, {}, [INTERRUPTED], NOW)  # what run_all's finally writes on SystemExit
        raise SystemExit(143)

    with pytest.raises(SystemExit):
        tick(conn, settings=None, cfg=CFG, now=NOW, run=run, ping_fn=lambda u, ok: None, holder="me:1")
    assert acquire(conn, "run", "other:2", NOW, 15)  # free at once, not after the 15-minute takeover
    row = conn.execute("SELECT status, run_id, finished_at FROM run_requests WHERE id = ?", (req,)).fetchone()
    assert row["status"] == "failed" and row["run_id"] is not None and row["finished_at"] is not None


def test_an_interrupted_fetch_now_says_why_and_can_be_retried_at_once(settings):
    conn = connect(settings.db_path)
    req = run_requests.queue(conn, 1, NOW - timedelta(minutes=10))
    fetch = start_run(conn, NOW - timedelta(minutes=9), None, kind="fetch", trigger="fetch_now")
    user = start_run(conn, NOW - timedelta(minutes=8), 1, kind="user", trigger="fetch_now", parent_id=fetch)
    for rid in (fetch, user):
        finish_run(conn, rid, {}, [INTERRUPTED], NOW - timedelta(minutes=7))
    run_requests.mark(conn, req, "failed", NOW - timedelta(minutes=7), fetch)
    s = fetch_now_state(conn, 1, NOW, CFG)
    # Neither the 2-hour per-user spacing nor the daily cap counts a run the app itself cut short.
    assert s == {"state": "ready", "text": INTERRUPTED, "poll": False}
    assert run_requests.fetch_now_count_today(conn, NOW) == 0


def test_an_old_interrupted_request_is_not_mentioned_forever(settings):
    conn = connect(settings.db_path)
    req = run_requests.queue(conn, 1, NOW - timedelta(days=2))
    fetch = start_run(conn, NOW - timedelta(days=2), None, kind="fetch", trigger="fetch_now")
    finish_run(conn, fetch, {}, [INTERRUPTED], NOW - timedelta(days=2))
    run_requests.mark(conn, req, "failed", NOW - timedelta(days=2), fetch)
    assert fetch_now_state(conn, 1, NOW, CFG) == {"state": "ready", "text": "", "poll": False}


# The real thing: `jobseeker tick` in a subprocess, mid-run, gets SIGTERM (what start.sh does on a deploy).
CHILD = """
import sys, time
from pathlib import Path
import jobseeker.cli as cli
from jobseeker.db.runs import start_run

def runner(settings, conn, now, holder, *a, **k):
    from jobseeker.config import load_app_config
    def run(trigger, users, plan_cap):
        start_run(conn, now, None, kind="fetch", trigger=trigger)
        Path(sys.argv[1]).write_text("running")
        time.sleep(30)
    return load_app_config(settings.app_config_path), run

cli._runner = runner
cli.app(["tick"])
"""


def test_sigterm_to_a_running_tick_process(settings, tmp_path):
    conn = connect(settings.db_path)
    _active(conn, datetime.now(UTC) - timedelta(seconds=2))
    req = run_requests.queue(conn, 1, datetime.now(UTC) - timedelta(seconds=1))
    conn.close()
    flag = tmp_path / "flag"
    env = {**os.environ, "JOBSEEKER_HOME": str(settings.jobseeker_home)}
    p = subprocess.Popen([sys.executable, "-c", CHILD, str(flag)], env=env, cwd=tmp_path,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    end = time.monotonic() + 20
    while not flag.exists() and time.monotonic() < end and p.poll() is None:
        time.sleep(0.05)
    assert flag.exists(), p.communicate()[0].decode()
    p.send_signal(signal.SIGTERM)
    out = p.communicate(timeout=10)[0].decode()
    assert p.returncode != 0, out
    conn = connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM locks").fetchone()[0] == 0, out
    assert conn.execute("SELECT status FROM run_requests WHERE id = ?", (req,)).fetchone()[0] == "failed"
