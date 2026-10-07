from fastapi.testclient import TestClient

from jobseeker.db.core import connect
from jobseeker.db.runs import finish_run, start_run
from jobseeker.web.app import create_app
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
    html = TestClient(create_app(settings)).get("/").text
    assert '<details class="run-notes"' in html and "Daily AI limit reached" in html
