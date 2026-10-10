import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from jobseeker.db.core import connect
from jobseeker.push.notify import RUN_NOTE, notify_new_matches
from jobseeker.push.send import VapidKeys

RUN = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)
NOW = datetime(2026, 10, 11, 6, 30, tzinfo=UTC)
KEYS = VapidKeys("unused-private", "unused-public", "mailto:o@x")


@pytest.fixture
def two(seeded_two, settings, monkeypatch):
    """seeded_two plus one 'apply' application for the roommate created after RUN, and one subscription."""
    conn = connect(settings.db_path)
    sent = []
    monkeypatch.setattr("jobseeker.push.notify.send_one",
                        lambda client, endpoint, p256dh, auth, payload, keys, now: sent.append((endpoint, payload)) or 201)
    conn.execute("UPDATE applications SET created_at = ? WHERE user_id = 2", ("2026-10-11T06:00:00+00:00",))
    conn.execute("""UPDATE scores SET recommendation = 'apply', score = 91 WHERE user_id = 2""")
    conn.execute("""INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at)
                    VALUES (2, 'https://web.push.apple.com/r1', 'p', 'a', 'now')""")
    conn.execute("""INSERT OR IGNORE INTO user_prefs (user_id, data, version, updated_at)
                    VALUES (2, '{}', 1, 'now')""")  # spec 3 creates this at first sign-in; seeded_two inserts users directly
    conn.commit()
    return conn, sent


def test_sends_counts_only_once_per_ist_day(two):
    conn, sent = two
    assert notify_new_matches(conn, 2, RUN, NOW, keys=KEYS) is None
    (endpoint, payload), = sent
    assert payload["url"] == "/?band=apply" and payload["body"] == "Top: 91 · Open Job Seeker"
    assert payload["title"] in ("1 new match",) or payload["title"].endswith("new matches")
    titles = conn.execute("SELECT j.title, j.company FROM jobs j").fetchall()
    blob = json.dumps(payload)
    assert not any(t["title"] in blob or t["company"] in blob for t in titles)
    assert conn.execute("SELECT notified_on FROM users WHERE id = 2").fetchone()[0] == "2026-10-11"
    notify_new_matches(conn, 2, RUN, NOW, keys=KEYS)
    assert len(sent) == 1


def test_new_ist_day_after_1830_utc(two):
    conn, sent = two
    notify_new_matches(conn, 2, RUN, NOW, keys=KEYS)
    late_run, late_now = datetime(2026, 10, 11, 18, 35, tzinfo=UTC), datetime(2026, 10, 11, 18, 40, tzinfo=UTC)
    conn.execute("UPDATE applications SET created_at = ? WHERE user_id = 2", ("2026-10-11T18:36:00+00:00",))
    conn.commit()
    notify_new_matches(conn, 2, late_run, late_now, keys=KEYS)
    assert len(sent) == 2
    assert conn.execute("SELECT notified_on FROM users WHERE id = 2").fetchone()[0] == "2026-10-12"


def test_nothing_new_or_toggle_off_or_unconfigured(two):
    conn, sent = two
    assert notify_new_matches(conn, 2, NOW, NOW, keys=KEYS) is None  # nothing created after NOW
    conn.execute("UPDATE user_prefs SET data = json_set(data, '$.notify_new_matches', json('false')) WHERE user_id = 2")
    conn.commit()
    notify_new_matches(conn, 2, RUN, NOW, keys=KEYS)
    assert sent == []
    conn.execute("UPDATE user_prefs SET data = json_set(data, '$.notify_new_matches', json('true')) WHERE user_id = 2")
    conn.commit()
    assert notify_new_matches(conn, 2, RUN, NOW, keys=None) is None and sent == []  # no VAPID keys


def test_410_deletes_and_failures_count(two, monkeypatch):
    conn, _ = two
    monkeypatch.setattr("jobseeker.push.notify.send_one", lambda *a: 410)
    assert notify_new_matches(conn, 2, RUN, NOW, keys=KEYS) == RUN_NOTE
    assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0
    assert conn.execute("SELECT notified_on FROM users WHERE id = 2").fetchone()[0] is None


def test_fifth_failure_deletes(two, monkeypatch):
    conn, _ = two
    monkeypatch.setattr("jobseeker.push.notify.send_one", lambda *a: 500)
    for _ in range(4):
        notify_new_matches(conn, 2, RUN, NOW, keys=KEYS)
    assert conn.execute("SELECT failures FROM push_subscriptions").fetchone()[0] == 4
    notify_new_matches(conn, 2, RUN, NOW, keys=KEYS)
    assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0


def test_transport_error_and_crash_never_raise(two, monkeypatch):
    conn, _ = two
    def down(*a):
        raise httpx.ConnectError("down")
    monkeypatch.setattr("jobseeker.push.notify.send_one", down)
    assert notify_new_matches(conn, 2, RUN, NOW, keys=KEYS) == RUN_NOTE
    monkeypatch.setattr("jobseeker.push.notify._new_matches", lambda *a: 1 / 0)
    assert notify_new_matches(conn, 2, RUN, NOW, keys=KEYS) == RUN_NOTE


def test_owner_alert_is_independent(two):
    conn, sent = two
    notify_new_matches(conn, 1, RUN, NOW, keys=KEYS)
    assert sent == []  # owner has no subscription and no new matches since RUN


def test_one_bad_subscription_is_pruned_and_the_rest_still_get_sent(two, monkeypatch):
    from jobseeker.push.send import InvalidSubscription
    conn, sent = two
    conn.execute("""INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at)
                    VALUES (2, 'https://web.push.apple.com/r0', 'p', 'a', 'now'),
                           (2, 'https://web.push.apple.com/r9', 'p', 'a', 'now')""")
    conn.commit()

    def send(client, endpoint, p256dh, auth, payload, keys, now):
        if endpoint.endswith("/r0"):
            raise InvalidSubscription("key is not a P-256 point")
        if endpoint.endswith("/r9"):
            raise RuntimeError("anything else")
        sent.append((endpoint, payload))
        return 201

    monkeypatch.setattr("jobseeker.push.notify.send_one", send)
    assert notify_new_matches(conn, 2, RUN, NOW, keys=KEYS) is None
    assert [e for e, _ in sent] == ["https://web.push.apple.com/r1"]
    rows = {r["endpoint"]: r["failures"] for r in conn.execute("SELECT endpoint, failures FROM push_subscriptions")}
    assert "https://web.push.apple.com/r0" not in rows  # invalid: pruned
    assert rows["https://web.push.apple.com/r9"] == 1  # unexpected error: counted as a failure, not fatal


def test_run_finished_push_ignores_the_daily_gate(two):
    from jobseeker.push.notify import notify_run_finished
    conn, sent = two
    conn.execute("UPDATE users SET notified_on = '2026-10-11' WHERE id = 2")  # the daily alert already went out
    conn.commit()
    assert notify_run_finished(conn, 2, RUN, NOW, scored=3, starved=False, keys=KEYS) is None
    (_, payload), = sent
    assert payload == {"title": "Your search finished", "body": "1 new match · top 91", "url": "/today"}


def test_run_finished_push_with_nothing_to_apply(two):
    from jobseeker.push.notify import notify_run_finished
    conn, sent = two
    notify_run_finished(conn, 2, NOW, NOW, scored=3, starved=False, keys=KEYS)  # nothing created after NOW
    notify_run_finished(conn, 2, NOW, NOW, scored=0, starved=True, keys=KEYS)
    notify_run_finished(conn, 2, NOW, NOW, scored=0, starved=False, keys=KEYS)
    assert [p["body"] for _, p in sent] == ["Scored 3 jobs; nothing to apply to yet",
                                            "Scores wait for tomorrow's AI allowance",
                                            "No new matches this time"]


def test_run_finished_push_respects_the_alerts_switch(two):
    from jobseeker.push.notify import notify_run_finished
    conn, sent = two
    conn.execute("UPDATE user_prefs SET data = json_set(data, '$.notify_new_matches', json('false')) WHERE user_id = 2")
    conn.commit()
    assert notify_run_finished(conn, 2, RUN, NOW, scored=3, starved=False, keys=KEYS) is None and sent == []
