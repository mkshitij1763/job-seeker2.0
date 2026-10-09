from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.pipeline.describe import describe_shared


def _jobs(conn, n):
    ids = []
    for i in range(n):
        cur = conn.execute("""INSERT INTO jobs (source, source_job_id, company, title, location, location_city, remote,
                              jd_text, jd_hash, apply_url, fingerprint, first_seen_at)
                              VALUES ('linkedin', ?, 'C', 'PA', 'B', 'B', 0, '', 'h', 'u', ?, 't')""", (f"li-{i}", f"fp{i}"))
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def test_interleaves_dedups_and_caps(tmp_path):
    conn = connect(tmp_path / "db")
    a, b, c, d = _jobs(conn, 4)
    asked = []
    stats = describe_shared(conn, [[a, b, c], [c, d]], cap=3, describe=lambda s, i: asked.append(i) or "JD text")
    assert asked == ["li-0", "li-2", "li-1"] and stats.described == 3  # u1#1, u2#1, u1#2 (u2#2 = dup of c is skipped)
    assert conn.execute("SELECT jd_text FROM jobs WHERE id = ?", (a,)).fetchone()[0] == "JD text"


def test_stops_after_two_consecutive_failures(tmp_path):
    conn = connect(tmp_path / "db")
    ids = _jobs(conn, 4)
    stats = describe_shared(conn, [ids], cap=10, describe=lambda s, i: "")
    assert stats.attempted == 2 and stats.failed == 2
    assert stats.errors == ["linkedin descriptions: 2 failed (last: empty description)"]
    assert conn.execute("SELECT jd_attempts FROM jobs WHERE id = ?", (ids[0],)).fetchone()[0] == 1
