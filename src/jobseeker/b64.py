from __future__ import annotations

import base64


def urlsafe_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def urlsafe_decode(text: str) -> bytes:
    text = text.strip().rstrip("=")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
