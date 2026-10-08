"""CSRF: SameSite=Lax keeps the session cookie off cross-site POSTs; this refuses any state-changing request that
doesn't prove it came from our own pages (Origin or Fetch-Metadata), so no per-form tokens are needed."""
from __future__ import annotations

SAFE = {"GET", "HEAD", "OPTIONS"}


class OriginCheck:
    def __init__(self, app, base_url: str):
        self.app, self.base_url = app, base_url.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in SAFE:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            site, origin = headers.get("sec-fetch-site"), headers.get("origin")
            blocked = (site in ("cross-site", "same-site") or (origin is not None and origin != self.base_url)
                       or (site != "same-origin" and origin is None))
            if blocked:
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": b"Request blocked"})
                return
        await self.app(scope, receive, send)
