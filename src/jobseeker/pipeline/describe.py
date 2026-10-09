"""Stage 4: fetch LinkedIn descriptions for the jobs users most likely want, shared and interleaved."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from jobseeker.db.jobs import record_jd_attempt, set_jd_text

MAX_CONSECUTIVE_FAILURES = 2


@dataclass
class DescribeStats:
    attempted: int = 0
    described: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def describe_shared(conn, picks: list[list[int]], cap: int, describe: Callable[[str, str], str],
                    heartbeat: Callable[[], None] = lambda: None) -> DescribeStats:
    order: list[int] = []
    for rank in range(max((len(p) for p in picks), default=0)):
        for p in picks:
            if rank < len(p) and p[rank] not in order:
                order.append(p[rank])
    stats, consecutive, last = DescribeStats(), 0, ""
    for job_id in order:
        if stats.attempted >= cap or consecutive >= MAX_CONSECUTIVE_FAILURES:
            break
        row = conn.execute("SELECT source, source_job_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        stats.attempted += 1
        try:
            text = describe(row["source"], row["source_job_id"])
            error = "" if text else "empty description"
        except Exception as e:
            text, error = "", f"{type(e).__name__}: {e}"
        if text:
            set_jd_text(conn, job_id, text)
            stats.described += 1
            consecutive = 0
        else:
            record_jd_attempt(conn, job_id)
            stats.failed += 1
            consecutive += 1
            last = error
        heartbeat()
    if stats.failed:
        stats.errors.append(f"linkedin descriptions: {stats.failed} failed (last: {last})")
    return stats
