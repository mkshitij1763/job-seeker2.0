import json

from jobseeker.config import load_rubric
from jobseeker.db.core import connect
from jobseeker.web.view import STEPS, factor_bars, nav_counts, next_step, tier, timeline


def test_tier_thresholds():
    assert [tier(s) for s in (95, 90, 89, 70, 69, 0, None)] == [
        "strong", "strong", "good", "good", "weak", "weak", "none"]


def test_factor_bars_follow_rubric_order_clamp_and_skip_unknown(settings):
    rubric = load_rubric(settings.rubric_path)
    bars = factor_bars(json.dumps({"skills_match": 25, "role_fit": 15, "mystery": 3}), rubric)
    assert [b["key"] for b in bars] == ["role_fit", "skills_match"]
    assert bars[0] == {"key": "role_fit", "label": "Role fit", "value": 15, "max": 30, "pct": 50}
    assert bars[1]["value"] == 20 and bars[1]["pct"] == 100  # clamped to the rubric max
    assert factor_bars(None, rubric) == [] and factor_bars("not json", rubric) == []
    assert factor_bars(json.dumps({"role_fit": "x"}), rubric) == []  # garbage value is skipped, not a 500


def test_next_step_covers_every_status():
    assert len(STEPS) == 4
    assert next_step("drafted", False) == 1 and next_step("drafted", True) == 2
    assert next_step("approved", True) == 3
    assert all(next_step(s, True) == 5 for s in ("sent", "replied", "interview", "offer"))
    for s in ("new", "shortlisted", "snoozed", "skipped", "not_interested", "rejected", "applied_via_portal"):
        assert next_step(s, True) is None, s


def test_timeline_reads_like_sentences():
    events = [
        {"at": "2026-10-03T09:00:00+00:00", "type": "status", "payload": json.dumps({"from": "approved", "to": "sent"})},
        {"at": "2026-10-04T09:00:00+00:00", "type": "status",
         "payload": json.dumps({"from": "shortlisted", "to": "skipped", "reason": "experience 6+ years"})},
        {"at": "2026-10-05T09:00:00+00:00", "type": "undo", "payload": json.dumps({"from": "skipped", "to": "shortlisted"})},
        {"at": "2026-10-08T09:00:00+00:00", "type": "followup", "payload": json.dumps({"n": 1})},
        {"at": "2026-10-08T10:00:00+00:00", "type": "contact", "payload": "{}"},
        {"at": "2026-10-08T11:00:00+00:00", "type": "mystery_thing", "payload": "not json"},
    ]
    assert [(t["day"], t["text"]) for t in timeline(events)] == [
        ("3 Oct", "Marked sent"),
        ("4 Oct", "Marked skipped (experience 6+ years)"),
        ("5 Oct", "Undid skipped, back to shortlisted"),
        ("8 Oct", "Follow-up 1 recorded"),
        ("8 Oct", "Contact saved"),
        ("8 Oct", "Mystery thing"),
    ]


def test_nav_counts(settings, seeded):
    conn = connect(settings.db_path)
    counts = nav_counts(conn, 1)
    assert set(counts) == {"jobs", "pipeline", "today"}
    assert counts["jobs"] == 1  # seeded: one "apply" job in an inbox status


def test_render_context_has_nav(settings, seeded):
    from jobseeker.web.app import create_app
    from tests.conftest import signed_in_client

    app = create_app(settings)
    assert app.state.rubric.dimensions[0].key == "role_fit"
    assert signed_in_client(settings).get("/today").status_code == 200
