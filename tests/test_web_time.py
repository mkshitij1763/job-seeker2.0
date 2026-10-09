from datetime import UTC, datetime

from jobseeker.web.filters import age


def test_age_counts_ist_days():
    now = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)  # 09:30 IST
    assert age("2026-10-11T00:30:00+00:00", now) == "today"  # 06:00 IST the same IST day
    assert age("2026-10-10T18:00:00+00:00", now) == "1d"     # 23:30 IST the previous day
    assert age(None, now) == "?"


def test_local_hour_is_ist(monkeypatch):
    from jobseeker.web import pipeline
    monkeypatch.setattr("jobseeker.web.pipeline.app_now", lambda: datetime(2026, 10, 11, 7, 0, tzinfo=UTC).astimezone(
        __import__("jobseeker.clock", fromlist=["APP_TZ"]).APP_TZ))
    assert pipeline._local_hour() == 12
