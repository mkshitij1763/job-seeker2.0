from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobseeker.db.core import iso, utcnow
from jobseeker.pipeline.normalize import normalize_company
from jobseeker.status import ACTIVE, InvalidTransition, can_transition


class BlockedContact(ValueError):
    pass


def _now(now: datetime | None) -> str:
    return iso(now) if now else utcnow()


def add_event(conn: sqlite3.Connection, app_id: int, type_: str, payload: dict | None = None,
              now: datetime | None = None) -> None:
    conn.execute("INSERT INTO events (application_id, at, type, payload) VALUES (?,?,?,?)",
                 (app_id, _now(now), type_, json.dumps(payload or {})))


def get_events(conn: sqlite3.Connection, app_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM events WHERE application_id = ? ORDER BY id", (app_id,))
    return [dict(r) for r in rows.fetchall()]


def ensure_application(conn: sqlite3.Connection, job_id: int, now: datetime | None = None) -> int:
    ts = _now(now)
    conn.execute(
        "INSERT OR IGNORE INTO applications (job_id, created_at, updated_at) VALUES (?,?,?)",
        (job_id, ts, ts),
    )
    conn.commit()
    return conn.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,)).fetchone()["id"]


def get_application(conn: sqlite3.Connection, app_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    return dict(row) if row else None


def get_status(conn: sqlite3.Connection, app_id: int) -> str:
    return conn.execute("SELECT status FROM applications WHERE id = ?", (app_id,)).fetchone()["status"]


def transition(conn: sqlite3.Connection, app_id: int, new_status: str,
               payload: dict | None = None, now: datetime | None = None) -> None:
    if new_status == "snoozed":
        raise InvalidTransition("use snooze() to snooze")
    cur = get_status(conn, app_id)
    if not can_transition(cur, new_status):
        raise InvalidTransition(f"{cur} -> {new_status}")
    conn.execute(
        """UPDATE applications SET status = ?, updated_at = ?,
           applied_via_portal = CASE WHEN ? = 'applied_via_portal' THEN 1 ELSE applied_via_portal END
           WHERE id = ?""",
        (new_status, _now(now), new_status, app_id),
    )
    add_event(conn, app_id, "status", {"from": cur, "to": new_status, **(payload or {})}, now)
    conn.commit()


def snooze(conn: sqlite3.Connection, app_id: int, until: datetime, now: datetime | None = None) -> None:
    cur = get_status(conn, app_id)
    if cur not in ACTIVE:
        raise InvalidTransition(f"cannot snooze from {cur}")
    conn.execute(
        "UPDATE applications SET status='snoozed', snoozed_from=?, snoozed_until=?, updated_at=? WHERE id=?",
        (cur, iso(until), _now(now), app_id),
    )
    add_event(conn, app_id, "status", {"from": cur, "to": "snoozed", "until": iso(until)}, now)
    conn.commit()


def wake_snoozed(conn: sqlite3.Connection, now: datetime) -> int:
    rows = conn.execute(
        "SELECT id, snoozed_from FROM applications WHERE status='snoozed' AND snoozed_until <= ?",
        (iso(now),),
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE applications SET status=?, snoozed_from=NULL, snoozed_until=NULL, updated_at=? WHERE id=?",
            (r["snoozed_from"], iso(now), r["id"]),
        )
        add_event(conn, r["id"], "status", {"from": "snoozed", "to": r["snoozed_from"]}, now)
    conn.commit()
    return len(rows)


def record_followup(conn: sqlite3.Connection, app_id: int, now: datetime | None = None) -> None:
    app = get_application(conn, app_id)
    if app["status"] != "sent":
        raise ValueError("follow-ups are only recorded for sent applications")
    if app["followups_sent"] >= 2:
        raise ValueError("already sent 2 follow-ups")
    conn.execute("UPDATE applications SET followups_sent = followups_sent + 1, updated_at=? WHERE id=?",
                 (_now(now), app_id))
    add_event(conn, app_id, "followup", {"n": app["followups_sent"] + 1}, now)
    conn.commit()


def set_notes(conn: sqlite3.Connection, app_id: int, notes: str) -> None:
    conn.execute("UPDATE applications SET notes = ?, updated_at = ? WHERE id = ?", (notes, utcnow(), app_id))
    conn.commit()


def set_suggestion(conn: sqlite3.Connection, app_id: int, role: str, reason: str, url: str,
                   warnings: list[str]) -> None:
    conn.execute(
        """UPDATE applications SET suggested_contact_role=?, suggested_contact_reason=?,
           linkedin_search_url=?, draft_warnings=?, updated_at=? WHERE id=?""",
        (role, reason, url, json.dumps(warnings), utcnow(), app_id),
    )
    conn.commit()


def blocked_companies(conn: sqlite3.Connection) -> set[str]:
    return {r["company"] for r in conn.execute("SELECT company FROM blocklist WHERE company != ''")}


def _company_of(conn: sqlite3.Connection, app_id: int) -> str:
    return conn.execute(
        "SELECT j.company FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = ?", (app_id,)
    ).fetchone()["company"]


def save_contact(conn: sqlite3.Connection, app_id: int, *, name: str, role: str, linkedin_url: str,
                 email: str, email_status: str) -> int:
    company = _company_of(conn, app_id)
    existing = None
    if email:
        existing = conn.execute("SELECT id FROM contacts WHERE lower(email) = lower(?)", (email,)).fetchone()
    if not existing and linkedin_url:
        existing = conn.execute("SELECT id FROM contacts WHERE linkedin_url = ?", (linkedin_url,)).fetchone()
    if existing:
        cid = existing["id"]
        if conn.execute("SELECT 1 FROM blocklist WHERE contact_id = ?", (cid,)).fetchone():
            raise BlockedContact(f"{name or email} said not interested; not attaching")
        conn.execute(
            "UPDATE contacts SET name=?, role=?, linkedin_url=?, email=?, email_status=? WHERE id=?",
            (name, role, linkedin_url, email, email_status, cid),
        )
    else:
        cid = conn.execute(
            """INSERT INTO contacts (company, name, role, linkedin_url, email, email_status)
               VALUES (?,?,?,?,?,?)""",
            (company, name, role, linkedin_url, email, email_status),
        ).lastrowid
    conn.execute("UPDATE applications SET contact_id = ?, updated_at = ? WHERE id = ?", (cid, utcnow(), app_id))
    add_event(conn, app_id, "contact", {"contact_id": cid, "email_status": email_status})
    conn.commit()
    return cid


def mark_not_interested(conn: sqlite3.Connection, app_id: int, block_company: bool,
                        now: datetime | None = None) -> None:
    app = get_application(conn, app_id)
    company = normalize_company(_company_of(conn, app_id))
    transition(conn, app_id, "not_interested", {"block_company": block_company}, now)
    if app["contact_id"]:
        conn.execute("INSERT INTO blocklist (contact_id, company, reason, at) VALUES (?, '', 'not interested', ?)",
                     (app["contact_id"], _now(now)))
    if block_company:
        conn.execute("INSERT INTO blocklist (contact_id, company, reason, at) VALUES (NULL, ?, 'not interested', ?)",
                     (company, _now(now)))
    conn.commit()


def save_draft(conn: sqlite3.Connection, app_id: int, kind: str, subject: str, body: str,
               edited: bool = False) -> None:
    conn.execute(
        """INSERT INTO drafts (application_id, kind, subject, body, edited, created_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (application_id, kind) DO UPDATE SET
             subject = excluded.subject, body = excluded.body, edited = excluded.edited""",
        (app_id, kind, subject, body, int(edited), utcnow()),
    )
    conn.commit()


def get_drafts(conn: sqlite3.Connection, app_id: int) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM drafts WHERE application_id = ?", (app_id,)).fetchall()
    return {r["kind"]: dict(r) for r in rows}


def set_gmail_draft_id(conn: sqlite3.Connection, app_id: int, draft_id: str) -> None:
    conn.execute("UPDATE drafts SET gmail_draft_id = ? WHERE application_id = ? AND kind = 'email'",
                 (draft_id, app_id))
    conn.commit()


UNDO_BLOCKED = {"not_interested"}  # its blocklist entries are not reverted


def last_status_event(conn: sqlite3.Connection, app_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM events WHERE application_id = ? AND type IN ('status', 'undo') ORDER BY id DESC LIMIT 1",
        (app_id,),
    ).fetchone()
    return dict(row) if row else None


def _undo_target(conn: sqlite3.Connection, app_id: int) -> tuple[str, str]:
    """(current status, status to restore) for an undoable latest change; raises InvalidTransition otherwise."""
    ev = last_status_event(conn, app_id)
    if not ev or ev["type"] != "status":
        raise InvalidTransition("nothing to undo")
    payload = json.loads(ev["payload"])
    frm, to = payload.get("from"), payload.get("to")
    if to in UNDO_BLOCKED:
        raise InvalidTransition(f"{to.replace('_', ' ')} can't be undone")
    if not frm or frm == "snoozed":
        raise InvalidTransition("that change can't be undone")
    if get_status(conn, app_id) != to:
        raise InvalidTransition("the status has changed since")
    return to, frm


def can_undo(conn: sqlite3.Connection, app_id: int) -> bool:
    try:
        _undo_target(conn, app_id)
    except InvalidTransition:
        return False
    return True


def undo_last_status(conn: sqlite3.Connection, app_id: int, now: datetime | None = None) -> str:
    current, restored = _undo_target(conn, app_id)
    conn.execute(
        """UPDATE applications SET status = ?, snoozed_until = NULL, snoozed_from = NULL, updated_at = ?,
           applied_via_portal = CASE WHEN ? = 'applied_via_portal' THEN 0 ELSE applied_via_portal END
           WHERE id = ?""",
        (restored, _now(now), current, app_id),
    )
    add_event(conn, app_id, "undo", {"from": current, "to": restored}, now)
    conn.commit()
    return restored
