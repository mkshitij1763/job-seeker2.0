from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from jobseeker.db.core import iso, utcnow
from jobseeker.pipeline.normalize import normalize_company

CATCH_ALL_TTL = timedelta(days=30)
STALE_AFTER = timedelta(minutes=20)  # worst case: Apify search + 3 profile lookups at 180 s each, plus SMTP


def set_find_status(conn: sqlite3.Connection, app_id: int, status: str, note: str = "") -> None:
    started = utcnow() if status == "running" else None
    if started:
        conn.execute("UPDATE applications SET find_status = ?, find_error = ?, find_started_at = ? WHERE id = ?",
                     (status, note, started, app_id))
    else:
        conn.execute("UPDATE applications SET find_status = ?, find_error = ? WHERE id = ?", (status, note, app_id))
    conn.commit()


def claim_find(conn: sqlite3.Connection, app_id: int, now: datetime) -> bool:
    """Atomically mark a find as running; False when another live run already holds it."""
    cur = conn.execute("""UPDATE applications SET find_status = 'running', find_error = '', find_started_at = ?
                          WHERE id = ? AND (find_status != 'running' OR find_started_at IS NULL
                                            OR find_started_at < ?)""", (iso(now), app_id, iso(now - STALE_AFTER)))
    conn.commit()
    return cur.rowcount == 1


def find_state(conn: sqlite3.Connection, app_id: int, now: datetime) -> dict:
    row = conn.execute("SELECT find_status, find_error, find_started_at FROM applications WHERE id = ?",
                       (app_id,)).fetchone()
    status, note = row["find_status"], row["find_error"]
    if status == "running" and row["find_started_at"] and row["find_started_at"] < iso(now - STALE_AFTER):
        return {"status": "failed", "note": "Finding contacts timed out (the Mac may have slept). Try again."}
    return {"status": status, "note": note}


def save_candidates(conn: sqlite3.Connection, app_id: int, ranked) -> None:
    conn.execute("DELETE FROM contact_candidates WHERE application_id = ?", (app_id,))
    conn.executemany(
        """INSERT INTO contact_candidates (application_id, position, name, headline, linkedin_url, label, reason, used)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(app_id, i + 1, c.name, c.headline, c.linkedin_url, label, reason, int(i < 3))
         for i, (c, label, reason) in enumerate(ranked)])
    conn.commit()


def next_candidate(conn: sqlite3.Connection, app_id: int) -> dict | None:
    row = conn.execute("""SELECT * FROM contact_candidates WHERE application_id = ? AND used = 0
                          ORDER BY position LIMIT 1""", (app_id,)).fetchone()
    if not row:
        return None
    conn.execute("UPDATE contact_candidates SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    return dict(row)


def link_contact(conn: sqlite3.Connection, app_id: int, rank: int, contact_id: int, label: str, reason: str,
                 email_source: str) -> None:
    conn.execute(
        """INSERT INTO application_contacts (application_id, contact_id, rank, label, reason, wave, email_source,
                                             created_at)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT (application_id, rank) DO UPDATE SET contact_id = excluded.contact_id,
             label = excluded.label, reason = excluded.reason, email_source = excluded.email_source,
             gmail_draft_id = NULL, emailed_at = NULL""",
        (app_id, contact_id, rank, label, reason, 1 if rank <= 2 else 2, email_source, utcnow()))
    if rank == 1:
        conn.execute("UPDATE applications SET contact_id = ? WHERE id = ?", (contact_id, app_id))
    conn.commit()


def people(conn: sqlite3.Connection, app_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT ac.rank, ac.label, ac.reason, ac.wave, ac.email_source, ac.gmail_draft_id, ac.emailed_at,
                  ac.nudged_at,
                  c.id AS contact_id, c.name, c.role, c.linkedin_url, c.email, c.email_status
           FROM application_contacts ac JOIN contacts c ON c.id = ac.contact_id
           WHERE ac.application_id = ? ORDER BY ac.rank""", (app_id,)).fetchall()
    return [dict(r) for r in rows]


def get_domain(conn: sqlite3.Connection, name_norm: str) -> dict | None:
    row = conn.execute("SELECT * FROM company_domains WHERE name_norm = ?", (name_norm,)).fetchone()
    return dict(row) if row else None


def save_domain(conn: sqlite3.Connection, name_norm: str, **fields) -> None:
    """Pass catch_all_at only when catch_all was just learned from the mail server."""
    current = get_domain(conn, name_norm) or {}
    merged = {k: fields.get(k, current.get(k)) for k in ("domain", "pattern", "catch_all", "mx_host", "catch_all_at")}
    if merged["catch_all"] is None:
        merged["catch_all_at"] = None
    elif not merged["catch_all_at"]:  # pre-migration rows: date the answer from the last check, not from now on
        merged["catch_all_at"] = current.get("checked_at") or utcnow()
    conn.execute(
        """INSERT INTO company_domains (name_norm, domain, pattern, catch_all, mx_host, checked_at, catch_all_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT (name_norm) DO UPDATE SET domain = excluded.domain, pattern = excluded.pattern,
             catch_all = excluded.catch_all, mx_host = excluded.mx_host, checked_at = excluded.checked_at,
             catch_all_at = excluded.catch_all_at""",
        (name_norm, merged["domain"], merged["pattern"],
         None if merged["catch_all"] is None else int(merged["catch_all"]), merged["mx_host"], utcnow(),
         merged["catch_all_at"]))
    conn.commit()


def known_catch_all(dom: dict, now: datetime) -> int | None:
    """The remembered catch-all/refusal answer, or None once it is a month old (servers and our IP change)."""
    if dom.get("catch_all") is None:
        return None
    at = dom.get("catch_all_at") or dom.get("checked_at")
    return dom["catch_all"] if at and at >= iso(now - CATCH_ALL_TTL) else None


def emailed_count(conn: sqlite3.Connection, app_id: int) -> int:
    return conn.execute("""SELECT COUNT(*) FROM application_contacts WHERE application_id = ?
                           AND (emailed_at IS NOT NULL OR gmail_draft_id IS NOT NULL)""", (app_id,)).fetchone()[0]


def bounced_emails(conn: sqlite3.Connection, company: str) -> set[str]:
    norm = normalize_company(company)
    rows = conn.execute("SELECT company, email FROM contacts WHERE email_status = 'bounced' AND email != ''").fetchall()
    return {r["email"].lower() for r in rows if normalize_company(r["company"]) == norm}


def _followup_window(conn: sqlite3.Connection, app_id: int, now: datetime) -> bool:
    """Sent, 5+ days with no newer event (a reply, a follow-up), and fewer than 2 follow-ups so far."""
    app = conn.execute("SELECT status, followups_sent FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not app or app["status"] != "sent" or app["followups_sent"] >= 2:
        return False
    last = conn.execute("SELECT at FROM events WHERE application_id = ? ORDER BY id DESC LIMIT 1", (app_id,)).fetchone()
    return bool(last) and datetime.fromisoformat(last["at"]) <= now - timedelta(days=5)


def nudge_due(conn: sqlite3.Connection, app_id: int, now: datetime) -> list[dict]:
    """#1/#2 who were emailed, haven't bounced and haven't had a follow-up yet, once the follow-up window opens."""
    if not _followup_window(conn, app_id, now):
        return []
    return [p for p in people(conn, app_id) if p["rank"] in (1, 2) and p["emailed_at"] and not p["nudged_at"]
            and p["email"] and p["email_status"] != "bounced"]


def third_due(conn: sqlite3.Connection, app_id: int, now: datetime) -> bool:
    """#3 is offered only in the follow-up window, and only when #3 has a usable email."""
    if not _followup_window(conn, app_id, now):
        return False
    return conn.execute("""SELECT 1 FROM application_contacts ac JOIN contacts c ON c.id = ac.contact_id
                           WHERE ac.application_id = ? AND ac.rank = 3 AND ac.emailed_at IS NULL
                           AND c.email != '' AND c.email_status != 'bounced'""", (app_id,)).fetchone() is not None


def blocked_profile_urls(conn: sqlite3.Connection, company: str) -> set[str]:
    norm = normalize_company(company)
    rows = conn.execute("""SELECT c.company, c.linkedin_url FROM blocklist b JOIN contacts c ON c.id = b.contact_id
                           WHERE c.linkedin_url != ''""").fetchall()
    return {r["linkedin_url"] for r in rows if normalize_company(r["company"]) == norm}


def blocked_names(conn: sqlite3.Connection, company: str) -> set[tuple[str, str]]:
    """(first, last) of blocked people at this company who have no LinkedIn URL to match on."""
    from jobseeker.contacts.names import clean_name

    norm = normalize_company(company)
    rows = conn.execute("""SELECT c.company, c.name FROM blocklist b JOIN contacts c ON c.id = b.contact_id
                           WHERE c.linkedin_url = '' AND c.name != ''""").fetchall()
    out = set()
    for r in rows:
        nm = clean_name(r["name"]) if normalize_company(r["company"]) == norm else None
        if nm and nm.last:  # a first name alone is too common to block on
            out.add((nm.first, nm.last))
    return out


def upsert_contact(conn: sqlite3.Connection, company: str, name: str, role: str, linkedin_url: str, email: str,
                   email_status: str, domain: str | None = None) -> int | None:
    row = conn.execute("SELECT id, email, email_status FROM contacts WHERE linkedin_url = ? AND linkedin_url != ''",
                       (linkedin_url,)).fetchone()
    if not row and email:  # only adopt an email-matched row that isn't someone else's profile
        row = conn.execute("""SELECT id, email, email_status FROM contacts
                              WHERE lower(email) = lower(?) AND linkedin_url = ''""", (email,)).fetchone()
    if row:
        if conn.execute("SELECT 1 FROM blocklist WHERE contact_id = ?", (row["id"],)).fetchone():
            return None
        on_domain = not domain or (row["email"] or "").lower().endswith("@" + domain)
        if row["email_status"] == "verified" and email_status != "verified" and row["email"] and on_domain:
            email, email_status = row["email"], "verified"  # never downgrade a verified address
        elif row["email_status"] == "bounced" and email.lower() == (row["email"] or "").lower():
            email_status = "bounced"
        conn.execute("UPDATE contacts SET name=?, role=?, linkedin_url=?, email=?, email_status=? WHERE id=?",
                     (name, role, linkedin_url, email, email_status, row["id"]))
        conn.commit()
        return row["id"]
    cid = conn.execute(
        """INSERT INTO contacts (company, name, role, linkedin_url, email, email_status, source)
           VALUES (?,?,?,?,?,?, 'finder')""", (company, name, role, linkedin_url, email, email_status)).lastrowid
    conn.commit()
    return cid
