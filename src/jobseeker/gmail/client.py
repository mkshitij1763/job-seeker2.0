from __future__ import annotations

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailUnavailable(RuntimeError):
    pass


def authorize(credentials_path: Path, token_path: Path) -> None:
    if not credentials_path.exists():
        raise GmailUnavailable(f"Download an OAuth desktop client JSON to {credentials_path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def load_service(token_path: Path):
    if not token_path.exists():
        raise GmailUnavailable("Gmail is not connected. Run `jobseeker auth-gmail`.")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                raise GmailUnavailable(f"Gmail sign-in expired ({e}). Run `jobseeker auth-gmail`.") from e
            token_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise GmailUnavailable("Gmail token is invalid. Run `jobseeker auth-gmail`.")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def create_draft(service, raw: str) -> str:
    try:
        res = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    except HttpError as e:
        if getattr(e, "status_code", None) in (401, 403) or (e.resp is not None and e.resp.status in (401, 403)):
            raise GmailUnavailable(f"Gmail rejected the request ({e}). Run `jobseeker auth-gmail`.") from e
        raise
    return res["id"]
