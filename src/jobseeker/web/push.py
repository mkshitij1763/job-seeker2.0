"""Root service worker plus the subscribe/unsubscribe/test endpoints for the Settings alerts card."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator

from jobseeker.db.core import iso
from jobseeker.push.send import InvalidSubscription, allowed_endpoint, send_one, valid_keys, vapid_from_settings
from jobseeker.web.deps import current_user, get_conn

SW = (Path(__file__).parent / "static" / "sw.js").read_text(encoding="utf-8")
public = APIRouter()
router = APIRouter(prefix="/push", dependencies=[Depends(current_user)])
_last_test: dict[int, float] = {}
MAX_SUBSCRIPTIONS = 5


class Keys(BaseModel):
    p256dh: str
    auth: str


class Subscription(BaseModel):
    endpoint: str
    keys: Keys

    @field_validator("endpoint")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://") or len(v) > 1024:
            raise ValueError("endpoint must be https and at most 1 KB")
        if not allowed_endpoint(v):
            raise ValueError("endpoint is not a supported push service")
        return v


class Endpoint(BaseModel):
    endpoint: str


def device_subscribed(conn, user_id: int, endpoint: str) -> bool:
    return conn.execute("SELECT 1 FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
                        (user_id, endpoint)).fetchone() is not None


def _keys(request: Request):
    return vapid_from_settings(request.app.state.settings)


@public.get("/sw.js", include_in_schema=False)
def service_worker():
    return Response(SW, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.post("/subscribe", status_code=204)
def subscribe(sub: Subscription, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    if not valid_keys(sub.keys.p256dh, sub.keys.auth):
        return PlainTextResponse("Invalid subscription keys", status_code=422)
    # Delete-then-insert (not upsert) so the newest id is the most recent subscribe, which the cap below keeps.
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (sub.endpoint,))
    conn.execute("""INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                 (user.id, sub.endpoint, sub.keys.p256dh, sub.keys.auth,
                  request.headers.get("user-agent", "")[:200], iso(datetime.now(UTC))))
    conn.execute("""DELETE FROM push_subscriptions WHERE user_id = ? AND id NOT IN
                    (SELECT id FROM push_subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT ?)""",
                 (user.id, user.id, MAX_SUBSCRIPTIONS))
    conn.commit()
    return Response(status_code=204)


@router.post("/unsubscribe", status_code=204)
def unsubscribe(body: Endpoint, user=Depends(current_user), conn=Depends(get_conn)):
    conn.execute("DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", (user.id, body.endpoint))
    conn.commit()
    return Response(status_code=204)


@router.post("/test")
def test_alert(body: Endpoint, request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    keys = _keys(request)
    if keys is None:
        return PlainTextResponse("Alerts aren't set up on this server", status_code=409)
    if time.monotonic() - _last_test.get(user.id, -1e9) < 60:
        return PlainTextResponse("Wait a minute before sending another test", status_code=429)
    sub = conn.execute("SELECT * FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
                       (user.id, body.endpoint)).fetchone()
    if sub is None:
        return PlainTextResponse("This device isn't subscribed", status_code=404)
    _last_test[user.id] = time.monotonic()
    payload = {"title": "Test alert", "body": "Alerts work on this device.", "url": "/settings"}
    try:
        with httpx.Client() as client:
            status = send_one(client, sub["endpoint"], sub["p256dh"], sub["auth"], payload, keys, datetime.now(UTC))
    except InvalidSubscription:
        conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
        conn.commit()
        return PlainTextResponse("This device's subscription was invalid and has been removed; "
                                 "turn alerts off and on again", status_code=422)
    except httpx.HTTPError:
        status = 0
    if 200 <= status < 300:
        return PlainTextResponse("Sent. Check your notifications.")
    return PlainTextResponse(f"The push service refused it (HTTP {status or 'error'})", status_code=502)
