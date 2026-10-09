"""Each outreach user's Gmail grant, sealed under TOKEN_KEY and bound to that user (AAD user:<id>)."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from jobseeker.crypto import DecryptError, open_, seal, user_aad
from jobseeker.db.core import iso

log = logging.getLogger(__name__)


def save_token(conn: sqlite3.Connection, key: bytes, user_id: int, account_email: str, creds_json: str,
               now: datetime) -> None:
    blob = seal(key, creds_json.encode(), user_aad(user_id))
    conn.execute("""INSERT INTO gmail_tokens (user_id, account_email, token_enc, status, connected_at, refreshed_at)
                    VALUES (?, ?, ?, 'ok', ?, ?) ON CONFLICT (user_id) DO UPDATE SET
                    account_email = excluded.account_email, token_enc = excluded.token_enc, status = 'ok',
                    connected_at = excluded.connected_at, refreshed_at = excluded.refreshed_at""",
                 (user_id, account_email, blob, iso(now), iso(now)))
    conn.commit()


def save_refreshed(conn: sqlite3.Connection, key: bytes, user_id: int, connected_at: str, creds_json: str,
                   now: datetime) -> bool:
    """Write a refreshed token back only onto the grant it came from: not after a reconnect (a new connected_at),
    an expiry or a removal, which all win. False when the refresh was discarded."""
    cur = conn.execute("""UPDATE gmail_tokens SET token_enc = ?, refreshed_at = ?
                          WHERE user_id = ? AND connected_at = ? AND status = 'ok'""",
                       (seal(key, creds_json.encode(), user_aad(user_id)), iso(now), user_id, connected_at))
    conn.commit()
    return cur.rowcount == 1


def load_token(conn: sqlite3.Connection, key: bytes, user_id: int) -> str:
    from jobseeker.gmail.client import GmailUnavailable
    row = conn.execute("SELECT token_enc, status FROM gmail_tokens WHERE user_id = ?", (user_id,)).fetchone()
    if row is None or row["status"] == "expired":
        raise GmailUnavailable("Gmail needs reconnecting", reconnect=True)
    try:
        return open_(key, row["token_enc"], user_aad(user_id)).decode()
    except DecryptError as e:  # key rotated, or a row copied from another user: never draft into the wrong Gmail
        log.warning("gmail token for user %s doesn't decrypt: %s", user_id, e)
        mark_expired(conn, user_id)
        raise GmailUnavailable("Gmail needs reconnecting", reconnect=True) from e


def mark_expired(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("UPDATE gmail_tokens SET status = 'expired' WHERE user_id = ?", (user_id,))
    conn.commit()


def delete_token(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM gmail_tokens WHERE user_id = ?", (user_id,))
    conn.commit()


def token_info(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT account_email, status, connected_at, refreshed_at FROM gmail_tokens WHERE user_id = ?",
                       (user_id,)).fetchone()
    return dict(row) if row else None
