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


def test_drafts_enabled_follows_the_switch():
    assert drafts_enabled(User(2, "r@x", "R", False, None, True))
    assert not drafts_enabled(User(1, "o@x", "O", True, None, False))   # admin alone no longer implies drafts


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
    conn.execute("INSERT INTO users (id, email, outreach_enabled, created_at) VALUES (2, 'a2@x', 1, 't')")
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
    assert drafters[0].stats.drafted == 8 // 2  # two outreach users draft; the matching-only roommate doesn't count


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


def test_draft_share_counts_outreach_users_only(settings):
    from jobseeker.config import ContactsConfig
    from jobseeker.db.usage import outreach_limits
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")  # matching-only
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (2, '{}', 1, NULL, 't', 't')""")
    assert outreach_limits(conn, ContactsConfig(), 20)["draft"].share_cap == 20


def test_two_outreach_users_draft_half_each_best_first(tmp_path, prefs, facts):
    from jobseeker.config import AppConfig
    from jobseeker.db.users import set_outreach

    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'r@x', 't')")
    for u in (1, 2):
        conn.execute("""INSERT OR REPLACE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at,
                        updated_at) VALUES (?, '{}', 1, NULL, 't', 't')""", (u,))
    set_outreach(conn, 2, True)
    _shortlist(conn, 1, 4)
    _shortlist(conn, 2, 4)
    cfg = AppConfig()
    cfg.budgets.global_drafts_per_day, cfg.budgets.draft_per_run = 4, 8
    drafters = [Drafter(u, prefs, facts, UserStats()) for u in (1, 2)]
    draft_round_robin(conn, drafters, FakeLLM(handler=lambda schema, prompt: DRAFT), cfg, NOW)
    assert [d.stats.drafted for d in drafters] == [2, 2]
    for u in (1, 2):
        got = [r[0] for r in conn.execute("""SELECT s.score FROM applications a JOIN scores s
                                              ON s.job_id = a.job_id AND s.user_id = a.user_id
                                              WHERE a.user_id = ? AND a.status = 'drafted'""", (u,))]
        assert sorted(got, reverse=True) == [90, 89]                    # the best two of 90..87
