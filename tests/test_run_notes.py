
from jobseeker.db.core import connect
from jobseeker.db.runs import finish_run, start_run
from tests.conftest import signed_in_client
from jobseeker.web.filters import explain_run


def test_explain_run_groups_and_rewords():
    notes = explain_run([
        "linkedin descriptions: 2 failed (last: empty description)",
        "scoring stopped: Groq daily quota used up for openai/gpt-oss-20b; retry in 855s",
        "score job 1: APIConnectionError: Connection error.",
        "score job 2: APIConnectionError: Connection error.",
        "draft application 10: LLMError: response truncated at max tokens",
        "naukri: 15 of 25 searches returned no results (the site may be rate-limiting)",
        "greenhouse:acme: HTTPStatusError: 404",
        "run aborted: KeyError: 'x'",
    ])
    text = " | ".join(n["text"] for n in notes)
    assert "Daily AI limit reached" in text and "tomorrow" in text
    assert "2 jobs couldn't be scored" in text  # grouped, not one line per job
    assert "1 draft couldn't be written" in text
    assert "LinkedIn didn't return 2 job descriptions" in text
    assert "Naukri returned nothing for 15 of 25 searches" in text
    assert "greenhouse:acme" in text
    assert [n["action"] for n in notes].count(True) == 1  # only the crash needs you


def test_header_shows_tappable_run_notes(settings, seeded):
    from datetime import UTC, datetime

    conn = connect(settings.db_path)
    run_id = start_run(conn, datetime.now(UTC))
    finish_run(conn, run_id, {}, ["scoring stopped: Groq daily quota used up for x; retry in 900s"], datetime.now(UTC))
    html = signed_in_client(settings).get("/").text
    assert '<details class="run-notes"' in html and "Daily AI limit reached" in html


def test_share_note_counts_the_whole_day():
    from jobseeker.web.filters import explain_stats
    notes = explain_stats({"user": {"stopped_by": "share", "scored": 0}, "fetch": {}}, scored_today=75)
    assert notes[0]["text"] == "You've used today's 75 scores; more tomorrow"


def test_reserved_note():
    from jobseeker.web.filters import explain_stats
    notes = explain_stats({"user": {"stopped_by": "reserved", "scored": 0}, "fetch": {}}, scored_today=0)
    assert notes[0]["text"] == ("Today's shared AI allowance is held for other users' first scores; "
                                "yours resume tomorrow")


def test_used_today_reads_the_ist_day(settings):
    from datetime import UTC, datetime

    from jobseeker.db.usage import used_today
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (1, '2026-10-11', 'score', 7)")
    conn.commit()
    assert used_today(conn, 1, "score", datetime(2026, 10, 10, 19, 0, tzinfo=UTC)) == 7  # 00:30 IST on the 11th


def test_header_share_note_uses_the_days_usage(settings):
    from datetime import UTC, datetime

    from jobseeker.clock import app_now
    conn = connect(settings.db_path)
    rid = start_run(conn, datetime.now(UTC), 1, kind="user", trigger="schedule")
    finish_run(conn, rid, {"stopped_by": "share", "scored": 0}, [], datetime.now(UTC))
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (1, ?, 'score', 75)",
                 (app_now(datetime.now(UTC)).strftime("%Y-%m-%d"),))
    conn.commit()
    from html import unescape
    assert "You've used today's 75 scores" in unescape(signed_in_client(settings, 1).get("/today").text)
