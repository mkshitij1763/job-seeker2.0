from datetime import UTC, datetime

from jobseeker.db.applications import ensure_application, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import save_score, upsert_job
from jobseeker.db.users import User
from jobseeker.models import ScoreResult
from jobseeker.outreach.drafter import DraftBundle
from jobseeker.pipeline.draft import Drafter, draft_round_robin, drafts_enabled
from jobseeker.pipeline.score import UserStats
from tests.factories import make_job
from tests.fakes import FakeLLM
from tests.test_run import DRAFT

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def _shortlist(conn, user_id, n):
    for i in range(n):
        j, _ = upsert_job(conn, make_job(source_job_id=f"{user_id}-{i}", fingerprint=f"f{user_id}{i}"), NOW)
        save_score(conn, user_id, j, ScoreResult(score=90 - i, breakdown={}, matches=[], gaps=[], recommendation="apply",
                                                 role_family="x"), "m", "v1", "h")
        transition(conn, ensure_application(conn, user_id, j, NOW), "shortlisted")


def test_only_admin_drafts_until_outreach_lands():
    assert drafts_enabled(User(1, "o@x", "O", True, None)) and not drafts_enabled(User(2, "r@x", "R", False, None))


def test_two_per_user_round_robin_within_share(tmp_path, prefs, facts):
    from jobseeker.config import AppConfig

    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'r@x', 't')")
    _shortlist(conn, 1, 5)
    _shortlist(conn, 2, 5)
    cfg = AppConfig()
    cfg.budgets.global_drafts_per_day = 6
    order = []
    llm = FakeLLM(handler=lambda schema, prompt: order.append(1) or DRAFT)
    drafters = [Drafter(u, prefs, facts, UserStats()) for u in (1, 2)]
    draft_round_robin(conn, drafters, llm, cfg, NOW)
    assert [d.stats.drafted for d in drafters] == [3, 3]  # share = 6 // 2
    statuses = [r[0] for r in conn.execute("SELECT a.user_id FROM applications a WHERE status = 'drafted' ORDER BY a.id")]
    assert statuses.count(1) == 3 and statuses.count(2) == 3
