from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import httpx

from jobseeker.models import RawJob


class Source(Protocol):
    name: str

    def fetch(self, client: httpx.Client) -> list[RawJob]: ...


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def from_epoch_ms(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms else None
