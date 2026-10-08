from datetime import UTC, datetime

from jobseeker.config import UserPrefs
from jobseeker.db.core import connect
from jobseeker.db.profile import (claim_extract, get_facts, get_user_prefs, load_user_context, save_facts,
                                  save_user_prefs)
from jobseeker.profile.facts import extract_facts
from tests.fakes import FakeLLM

T = datetime(2026, 10, 8, tzinfo=UTC)


def test_prefs_roundtrip(settings):
    conn = connect(settings.db_path)
    save_user_prefs(conn, 1, UserPrefs(roles=["Data Analyst"], cities=["Pune"]), T)
    assert get_user_prefs(conn, 1).roles == ["Data Analyst"]


def test_facts_roundtrip_and_claim(settings, facts):
    conn = connect(settings.db_path)
    save_facts(conn, 1, "sha", facts, edited=False, now=T)
    assert get_facts(conn, 1) == facts
    assert claim_extract(conn, 1, T) is True
    assert claim_extract(conn, 1, T) is False          # already running
    assert claim_extract(conn, 1, T.replace(hour=1)) is True  # 20-min stale claim taken over


def test_load_user_context_builds_effective_prefs(settings, app_config):
    prefs, facts = load_user_context(connect(settings.db_path), 1, app_config)
    assert prefs.name == "Asha Owner" and facts is not None


def test_extract_facts_is_pure(facts):
    llm = FakeLLM([facts])
    assert extract_facts(llm, "resume text 67%", "m") == facts
    assert "resume text 67%" in llm.calls[0]["prompt"]


def test_current_prefs_reads_fresh_each_request(settings, app_config):
    from types import SimpleNamespace

    from jobseeker.db.users import user_by_id
    from jobseeker.web.deps import current_prefs
    conn = connect(settings.db_path)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_config=app_config)))
    up = get_user_prefs(conn, 1)
    save_user_prefs(conn, 1, up.model_copy(update={"linkedin": "https://www.linkedin.com/in/changed/"}), T)
    assert current_prefs(req, user_by_id(conn, 1), conn).linkedin == "https://www.linkedin.com/in/changed/"
