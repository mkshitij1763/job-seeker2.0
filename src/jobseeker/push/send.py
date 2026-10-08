"""Web push delivery: RFC 8291 payload encryption (http-ece) plus VAPID (py-vapid), sent with httpx."""
from __future__ import annotations

import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import http_ece
import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02

from jobseeker.b64 import urlsafe_decode

TTL_SECONDS = 86400
JWT_LIFETIME = 12 * 3600
TIMEOUT = 10.0


@dataclass(frozen=True)
class VapidKeys:
    private: str
    public: str
    subject: str


def vapid_from_settings(settings) -> VapidKeys | None:
    keys = VapidKeys(settings.vapid_private_key.strip(), settings.vapid_public_key.strip(),
                     settings.vapid_subject.strip())
    return keys if keys.private and keys.public and keys.subject else None


def valid_keys(p256dh: str, auth: str) -> bool:
    try:
        return len(urlsafe_decode(p256dh)) == 65 and len(urlsafe_decode(auth)) == 16
    except (binascii.Error, ValueError):
        return False


def encrypt_payload(payload: dict, p256dh: str, auth: str) -> bytes:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return http_ece.encrypt(data, private_key=ec.generate_private_key(ec.SECP256R1()), dh=urlsafe_decode(p256dh),
                            auth_secret=urlsafe_decode(auth), version="aes128gcm")


def vapid_headers(endpoint: str, keys: VapidKeys, now: datetime) -> dict:
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(now.timestamp()) + JWT_LIFETIME,
              "sub": keys.subject}
    return Vapid02.from_raw(keys.private.encode()).sign(claims)


def send_one(client: httpx.Client, endpoint: str, p256dh: str, auth: str, payload: dict, keys: VapidKeys,
             now: datetime) -> int:
    headers = {**vapid_headers(endpoint, keys, now), "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "TTL": str(TTL_SECONDS), "Urgency": "normal"}
    resp = client.post(endpoint, content=encrypt_payload(payload, p256dh, auth), headers=headers, timeout=TIMEOUT)
    return resp.status_code
