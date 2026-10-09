import threading

from jobseeker.db.core import connect
from jobseeker.db.usage import Budget, Limit

from datetime import UTC, datetime

NOW = datetime(2026, 10, 9, tzinfo=UTC)


def test_review_12_concurrent_takes_never_overshoot_a_cap(settings):
    connect(settings.db_path).close()
    limits = {"tavily": Limit("month", 3, 3)}
    barrier, won = threading.Barrier(12), []

    def worker():
        conn = connect(settings.db_path)
        barrier.wait()
        if Budget(conn, 1, limits, NOW).take("tavily"):
            won.append(1)
        conn.close()
    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    conn = connect(settings.db_path)
    assert len(won) == 3 and Budget(conn, 1, limits, NOW).used("tavily") == 3


def test_take_and_refund(settings):
    conn = connect(settings.db_path)
    b = Budget(conn, 1, {"draft": Limit("day", 2, 1)}, NOW)
    assert b.take("draft") and not b.take("draft")
    b.refund("draft")
    assert b.used("draft") == 0 and b.take("draft")
