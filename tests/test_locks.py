from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.db.core import connect
from jobseeker.db.locks import LockLost, acquire, heartbeat, held_since, release

T0 = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def test_second_acquire_fails_while_fresh(tmp_path):
    conn = connect(tmp_path / "db")
    assert acquire(conn, "run", "a:1", T0, 15)
    assert not acquire(conn, "run", "b:2", T0 + timedelta(minutes=14), 15)
    heartbeat(conn, "run", "a:1", T0 + timedelta(minutes=10))
    assert not acquire(conn, "run", "b:2", T0 + timedelta(minutes=24), 15)  # heartbeat refreshed at +10
    assert held_since(conn, "run") == "2026-10-11T05:45:00+00:00"


def test_takeover_after_silence_and_lock_lost(tmp_path):
    conn = connect(tmp_path / "db")
    acquire(conn, "run", "a:1", T0, 15)
    assert acquire(conn, "run", "b:2", T0 + timedelta(minutes=16), 15)
    with pytest.raises(LockLost):
        heartbeat(conn, "run", "a:1", T0 + timedelta(minutes=17))
    release(conn, "run", "a:1")  # the old holder's release is a no-op
    assert held_since(conn, "run") is not None
    release(conn, "run", "b:2")
    assert held_since(conn, "run") is None and acquire(conn, "run", "c:3", T0 + timedelta(minutes=18), 15)
