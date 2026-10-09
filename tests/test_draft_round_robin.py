from datetime import UTC, datetime

from jobseeker.db.applications import ensure_application, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import save_score, upsert_job
from jobseeker.db.users import User
from jobseeker.models import ScoreResult
from jobseeker.outreach.drafter import DraftBundle
from jobseeker.pipeline.draft import Drafter, draft_round_robin
from jobseeker.pipeline.eligible import drafts_enabled
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


def test_one_drafter_run_gets_only_its_slice(tmp_path, prefs, facts):
    from jobseeker.config import AppConfig

    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, is_admin, created_at) VALUES (2, 'a2@x', 1, 't')")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (3, 'r@x', 't')")
    for u in (1, 2, 3):
        conn.execute("""INSERT OR REPLACE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at,
                        updated_at) VALUES (?, '{}', 1, NULL, 't', 't')""", (u,))
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = 1")
    _shortlist(conn, 1, 8)
    cfg = AppConfig()
    cfg.budgets.global_drafts_per_day, cfg.budgets.draft_per_run = 8, 8
    drafters = [Drafter(1, prefs, facts, UserStats())]
    draft_round_robin(conn, drafters, FakeLLM(handler=lambda schema, prompt: DRAFT), cfg, NOW)
    assert drafters[0].stats.drafted == 8 // 2  # two admins can draft; the roommate doesn't count


def test_eligible_count_rules(tmp_path):
    from jobseeker.pipeline.eligible import eligible_count, share_divisor

    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'r@x', 't')")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (3, 'n@x', 't')")
    for u in (1, 2):
        conn.execute("""INSERT OR REPLACE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at,
                        updated_at) VALUES (?, '{}', 1, NULL, 't', 't')""", (u,))
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = 1")
    assert eligible_count(conn, "score") == 2 and eligible_count(conn, "draft") == 1
    assert share_divisor(conn, "score", 3) == 3 and share_divisor(conn, "draft", 0) == 1
