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
    from jobseeker.db.gmail_tokens import load_token, mark_expired, save_token, token_info

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
        save_token(conn, key, user_id, token_info(conn, user_id)["account_email"], creds.to_json(), datetime.now(UTC),
                   refreshed=True)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def create_draft(service, raw: str) -> str:
    try:
        res = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    except HttpError as e:
        if getattr(e, "status_code", None) in (401, 403) or (e.resp is not None and e.resp.status in (401, 403)):
            raise GmailUnavailable("Gmail needs reconnecting", reconnect=True) from e
        raise GmailUnavailable(f"Couldn't reach Gmail ({e}). Try again in a minute.") from e
    except (TransportError, OSError) as e:
        raise GmailUnavailable(f"Couldn't reach Gmail ({e}). Check the internet and try again.") from e
    return res["id"]
