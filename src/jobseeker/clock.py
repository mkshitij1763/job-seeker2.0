"""App time: storage stays UTC; 'which day / which hour is it' is India time (one app-wide zone)."""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Asia/Kolkata")  # fails loudly at import if tzdata is missing


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def app_now(now: datetime | None = None) -> datetime:
    return _aware(now or datetime.now(UTC)).astimezone(APP_TZ)


def app_today(now: datetime | None = None) -> date:
    return app_now(now).date()


def app_day(dt: datetime) -> str:
    return _aware(dt).astimezone(APP_TZ).date().isoformat()


def day_start_utc(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), APP_TZ).astimezone(UTC)
