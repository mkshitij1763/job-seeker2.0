from datetime import UTC, datetime

from jobseeker.db.account import delete_account
from jobseeker.db.core import connect
from jobseeker.db.run_requests import mark, queue
from jobseeker.db.runs import finish_run, start_run

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)


def test_delete_covers_run_requests_and_keeps_fks_clean(seeded_two, settings):
    conn = connect(settings.db_path)
    fetch = start_run(conn, NOW, None, kind="fetch", trigger="fetch_now")
    mine = start_run(conn, NOW, 2, kind="user", trigger="fetch_now", parent_id=fetch)
    finish_run(conn, mine, {}, [], NOW)
    mark(conn, queue(conn, 2, NOW), "done", NOW, run_id=mine)       # points at the roommate's own run
    mark(conn, queue(conn, 1, NOW), "done", NOW, run_id=fetch)      # the owner's request stays
    delete_account(conn, settings.jobseeker_home, 2)
    assert [r[0] for r in conn.execute("SELECT user_id FROM run_requests")] == [1]
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE user_id = 2").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE id = ?", (fetch,)).fetchone()[0] == 1  # shared fetch run stays
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
