from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from jobseeker.clock import app_now
from jobseeker.db.gmail_tokens import token_info
from jobseeker.db.applications import get_drafts, get_events
from jobseeker.db.contacts_repo import people
from jobseeker.db.jobs import latest_score
from jobseeker.db.users import LastAdmin, tombstone_for
from jobseeker.profile.resume import resume_path

SHARED = {"users", "jobs", "contacts", "company_domains", "discovered_companies", "invites"}  # invites: keyed by email


def user_scoped_tables(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every table holding per-user rows, found from the schema (later sub-projects' tables are included
    automatically). `users` itself is handled last."""
    out = []
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if t in SHARED:
            if t == "contacts" and "owner_user_id" in {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}:
                out.append((t, "owner_user_id"))
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if "user_id" in cols:
            out.append((t, "user_id"))
        elif "application_id" in cols:
            out.append((t, "application_id"))
    return out


def delete_account(conn: sqlite3.Connection, home: Path, user_id: int, now: datetime | None = None) -> None:
    row = conn.execute("SELECT is_admin, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if row["is_admin"] and not conn.execute(
            "SELECT 1 FROM users WHERE is_admin = 1 AND disabled_at IS NULL AND id != ?", (user_id,)).fetchone():
        raise LastAdmin("You're the only admin")
    tables = user_scoped_tables(conn)
    now = now or app_now()
    with conn:
        # This period's spend stays counted (on a tombstone user), or the shared free-tier caps would reset;
        # older periods no longer limit anything and go.
        tomb = tombstone_for(conn, user_id, now)
        conn.execute("""INSERT INTO usage (user_id, period, service, amount)
                        SELECT ?, period, service, amount FROM usage WHERE user_id = ? AND period IN (?, ?) AND true
                        ON CONFLICT (user_id, period, service) DO UPDATE SET amount = amount + excluded.amount""",
                     (tomb, user_id, now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")))
        for t, how in [x for x in tables if x[1] == "application_id"]:
            conn.execute(f"DELETE FROM {t} WHERE application_id IN (SELECT id FROM applications WHERE user_id = ?)",
                         (user_id,))
        # contacts.owner_user_id rows go after application_contacts (above), before applications/users;
        # applications.contact_id may point at one of them, so unlink it first
        conn.execute("UPDATE applications SET contact_id = NULL WHERE user_id = ?", (user_id,))
        # private contacts go after blocklist (which can point at them); runs go last: run_requests.run_id can
        # point at the user's own run
        for t, how in sorted([x for x in tables if x[1] != "application_id" and x[0] != "applications"],
                             key=lambda x: {"contacts": 1, "runs": 2}.get(x[0], 0)):
            conn.execute(f"DELETE FROM {t} WHERE {how} = ?", (user_id,))
        conn.execute("DELETE FROM applications WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM invites WHERE email = ?", (row["email"],))
        conn.execute("UPDATE invites SET invited_by = NULL WHERE invited_by = ?", (user_id,))  # their invites stay valid
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    shutil.rmtree(home / "data" / "users" / str(user_id), ignore_errors=True)


def export_zip(conn: sqlite3.Connection, home: Path, user_id: int) -> bytes:
    """The user's own data only: profile, resume, applications (with what's linked to them) and job verdicts."""
    user = conn.execute("SELECT email, name, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    prefs = conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    facts = conn.execute("SELECT facts FROM user_facts WHERE user_id = ?", (user_id,)).fetchone()
    profile = {"user": dict(user), "prefs": json.loads(prefs["data"]) if prefs else None,
               "facts": json.loads(facts["facts"]) if facts and facts["facts"] else None}
    person = ("name", "role", "linkedin_url", "email", "email_status")
    apps = []
    for a in conn.execute("""SELECT a.id, a.status, a.job_id, a.contact_id, j.title, j.company, j.location, j.apply_url
                             FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.user_id = ? ORDER BY a.id""",
                          (user_id,)).fetchall():
        score = latest_score(conn, user_id, a["job_id"])
        apps.append({
            "id": a["id"], "status": a["status"],
            "job": {k: a[k] for k in ("title", "company", "location", "apply_url")},
            "score": {k: score[k] for k in ("score", "recommendation", "role_family")} if score else None,
            "drafts": get_drafts(conn, a["id"]), "events": get_events(conn, a["id"]),
            "people": [{k: p[k] for k in person} for p in people(conn, a["id"])],
            "contact": _contact(conn, a["contact_id"], person)})  # the main contact, including one added by hand
    blocked = [{"company": b["company"] or None, "person": _contact(conn, b["contact_id"], person),
                "reason": b["reason"], "at": b["at"]}
               for b in conn.execute("SELECT * FROM blocklist WHERE user_id = ? ORDER BY id", (user_id,))]
    verdicts = io.StringIO()
    w = csv.writer(verdicts)
    w.writerow(["job_id", "title", "company", "filter_reason", "prescore"])
    for r in conn.execute("""SELECT uj.job_id, j.title, j.company, uj.filter_reason, uj.prescore
                             FROM user_jobs uj JOIN jobs j ON j.id = uj.job_id WHERE uj.user_id = ? ORDER BY uj.job_id""",
                          (user_id,)):
        w.writerow(list(r))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("profile.json", json.dumps(profile, indent=2, ensure_ascii=False))
        z.writestr("applications.json", json.dumps(apps, indent=2, ensure_ascii=False, default=str))
        z.writestr("job_verdicts.csv", verdicts.getvalue())
        z.writestr("blocklist.json", json.dumps(blocked, indent=2, ensure_ascii=False))
        gmail = token_info(conn, user_id)
        if gmail:  # where drafts go; never the token itself
            z.writestr("gmail.json", json.dumps({k: gmail[k] for k in ("account_email", "connected_at")}))
        resume = resume_path(home, user_id)
        if resume.exists():
            z.write(resume, "resume.pdf")
    return buf.getvalue()


def _contact(conn: sqlite3.Connection, contact_id: int | None, fields: tuple[str, ...]) -> dict | None:
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone() if contact_id else None
    return {k: row[k] for k in fields} if row else None
