"""One signed S3 PUT (AWS SigV4, path-style), enough for Backblaze B2's S3 API. No read, list or delete."""
from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlsplit

import httpx

FIELDS = {"endpoint": "BACKUP_S3_ENDPOINT", "region": "BACKUP_S3_REGION", "bucket": "BACKUP_S3_BUCKET",
          "key_id": "BACKUP_S3_KEY_ID", "secret": "BACKUP_S3_SECRET"}


class OffsiteConfigError(ValueError):
    pass


class UploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    region: str
    bucket: str
    key_id: str
    secret: str

    @classmethod
    def from_settings(cls, settings) -> S3Config | None:
        values = {f: getattr(settings, f"backup_s3_{f}").strip() for f in FIELDS}
        if not any(values.values()):
            return None
        missing = [env for f, env in FIELDS.items() if not values[f]]
        if missing:
            raise OffsiteConfigError(f"Off-site backup settings are incomplete: missing {', '.join(missing)}")
        return cls(endpoint=values["endpoint"].rstrip("/"), **{k: v for k, v in values.items() if k != "endpoint"})

    def url(self, key: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{key}"


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign_put(url: str, body: bytes, cfg: S3Config, now: datetime) -> dict[str, str]:
    parts = urlsplit(url)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {"host": parts.netloc, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    signed = ";".join(sorted(headers))
    canonical = "\n".join(["PUT", quote(parts.path, safe="/-_.~"), "",
                           "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)), signed, payload_hash])
    scope = f"{day}/{cfg.region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + cfg.secret).encode(), day), cfg.region), "s3"), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {"Authorization": f"AWS4-HMAC-SHA256 Credential={cfg.key_id}/{scope}, SignedHeaders={signed}, "
                             f"Signature={signature}",
            "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}


def put_object(client: httpx.Client, cfg: S3Config, key: str, body: bytes, now: datetime,
               sleep: Callable[[float], None] = time.sleep, retries: int = 2) -> None:
    url = cfg.url(key)
    last = ""
    for attempt in range(retries + 1):
        try:
            resp = client.put(url, content=body, headers=sign_put(url, body, cfg, now), timeout=60.0)
        except httpx.TransportError as e:
            last = f"{type(e).__name__}: {e}"
        else:
            if resp.status_code < 300:
                return
            last = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code < 500:
                break
        if attempt < retries:
            sleep(2 ** attempt)
    raise UploadError(f"Upload of {key} failed: {last}")
