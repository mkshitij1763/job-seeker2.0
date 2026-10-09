"""Who shares the daily AI caps. A share is global // eligible users, whoever is in this run (a Fetch now run of one
user still gets only their slice), so this is the one place that counts them."""
from __future__ import annotations

from jobseeker.db.users import user_by_id


def active_users(conn) -> list:
    """Onboarded and not disabled: everyone the scheduled run serves and the score share is split between."""
    rows = conn.execute("""SELECT u.id FROM users u JOIN user_prefs p ON p.user_id = u.id
                           WHERE p.onboarded_at IS NOT NULL AND u.disabled_at IS NULL ORDER BY u.id""").fetchall()
    return [user_by_id(conn, r["id"]) for r in rows]


def drafts_enabled(user) -> bool:
    """Until sub-project 5 adds users.outreach_enabled, only the owner (admin) gets AI drafts."""
    return bool(user.is_admin)


def eligible_count(conn, stage: str) -> int:
    """Active users for "score"; active users with drafts enabled for "draft"."""
    users = active_users(conn)
    if stage == "draft":
        users = [u for u in users if drafts_enabled(u)]
    elif stage != "score":
        raise ValueError(f"unknown stage {stage!r}")
    return len(users)


def share_divisor(conn, stage: str, in_run: int) -> int:
    """At least the users in this run (a test or a `run --email` may include someone not yet counted), never 0."""
    return max(1, in_run, eligible_count(conn, stage))
