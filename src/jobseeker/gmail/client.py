from __future__ import annotations

import json
from datetime import UTC, datetime

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailUnavailable(RuntimeError):
    def __init__(self, message: str, reconnect: bool = False):
        super().__init__(message)
        self.reconnect = reconnect  # True: the grant is gone or expired; the user taps Reconnect Gmail


def load_service(conn, user_id: int, key: bytes):
    """This user's Gmail, from their sealed token; a refreshed token is sealed and written back."""
    from jobseeker.db.gmail_tokens import load_token, mark_expired, save_refreshed, token_info

    grant = token_info(conn, user_id)  # read first: a reconnect after this makes the write-back below a no-op
    try:
        info = json.loads(load_token(conn, key, user_id))  # raises GmailUnavailable(reconnect=True)
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except ValueError as e:
        mark_expired(conn, user_id)
        raise GmailUnavailable("Gmail needs reconnecting", reconnect=True) from e
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            mark_expired(conn, user_id)
            raise GmailUnavailable("Gmail needs reconnecting", reconnect=True) from e
        except TransportError as e:
            raise GmailUnavailable(f"Couldn't reach Gmail ({e}). Check the internet and try again.") from e
        if grant is None or not save_refreshed(conn, key, user_id, grant["connected_at"], creds.to_json(),
                                               datetime.now(UTC)):
            current = token_info(conn, user_id)
            if current is None or current["status"] == "expired":  # removed or expired meanwhile: never draft
                raise GmailUnavailable("Gmail needs reconnecting", reconnect=True)
            # reconnected meanwhile: this request still drafts with the grant it loaded; the new one is kept
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


AUTH_REASONS = {"insufficientPermissions", "authError"}


def _auth_failure(e: HttpError) -> bool:
    """401, or a 403 that is about the grant; other 403s (rate limits, API not enabled) don't need a reconnect."""
    status = getattr(e, "status_code", None) or (e.resp.status if e.resp is not None else None)
    if status == 401:
        return True
    if status != 403:
        return False
    try:
        errors = json.loads(e.content or b"{}").get("error", {}).get("errors", [])
    except (ValueError, AttributeError):
        errors = []
    return any(err.get("reason") in AUTH_REASONS for err in errors if isinstance(err, dict))


def create_draft(service, raw: str) -> str:
    try:
        res = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    except HttpError as e:
        if _auth_failure(e):
            raise GmailUnavailable("Gmail needs reconnecting", reconnect=True) from e
        raise GmailUnavailable(f"Couldn't reach Gmail ({e}). Try again in a minute.") from e
    except (TransportError, OSError) as e:
        raise GmailUnavailable(f"Couldn't reach Gmail ({e}). Check the internet and try again.") from e
    return res["id"]
