# tests/test_clock.py
from datetime import UTC, date, datetime

from jobseeker.clock import APP_TZ, app_day, app_now, app_today, day_start_utc


def test_ist_day_boundaries():
    assert app_day(datetime(2026, 10, 11, 18, 29, tzinfo=UTC)) == "2026-10-11"
    assert app_day(datetime(2026, 10, 11, 18, 30, tzinfo=UTC)) == "2026-10-12"
    assert app_day(datetime(2026, 10, 11, 18, 30)) == "2026-10-12"  # naive means UTC
    assert app_today(datetime(2026, 10, 11, 20, 0, tzinfo=UTC)) == date(2026, 10, 12)


def test_app_now_and_day_start():
    now = app_now(datetime(2026, 10, 11, 5, 45, tzinfo=UTC))
    assert now.tzinfo == APP_TZ and (now.hour, now.minute) == (11, 15)
    assert day_start_utc(date(2026, 10, 12)) == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
    assert app_now().tzinfo == APP_TZ
