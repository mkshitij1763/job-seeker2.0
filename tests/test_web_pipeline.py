from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from jobseeker.db import queries
from jobseeker.db.applications import transition
from jobseeker.db.core import connect
from jobseeker.web.app import create_app


def test_pipeline_board_and_followup_flag(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    then = datetime.now(UTC) - timedelta(days=6)
    transition(conn, a, "approved", now=then)
    transition(conn, a, "sent", now=then)
    board = queries.pipeline(conn, datetime.now(UTC))
    [card] = board["sent"]
    assert card["days_since"] == 6 and card["needs_followup"] is True
    st = queries.stats(conn, datetime.now(UTC))
    assert st["sent"] == 1 and st["drafted"] == 1 and st["reply_rate"] == 0.0
    assert st["jobs_per_source"] == {"lever": 2}

    r = TestClient(create_app(settings)).get("/pipeline")
    assert r.status_code == 200
    assert "Follow up" in r.text and "Senior Product Analyst 0" in r.text


def test_stats_ignore_undone_transitions(settings, seeded):
    from jobseeker.db.applications import undo_last_status

    a = seeded[0]
    conn = connect(settings.db_path)
    transition(conn, a, "approved")
    transition(conn, a, "sent")
    undo_last_status(conn, a)  # "Mark sent" pressed by mistake
    st = queries.stats(conn, datetime.now(UTC))
    assert st["sent"] == 0 and st["drafted"] == 1
    transition(conn, a, "sent")
    assert queries.stats(conn, datetime.now(UTC))["sent"] == 1
