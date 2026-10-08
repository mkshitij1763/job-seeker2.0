import json
import shutil
from datetime import UTC, datetime

from jobseeker.config import UserPrefs, load_preferences
from jobseeker.db.core import connect
from jobseeker.profile.importer import golden_fields, import_profile

ROOT_FIX = __import__("pathlib").Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _profile(tmp_path, with_resume=True):
    prof = tmp_path / "profile"
    prof.mkdir()
    shutil.copy(ROOT_FIX / "preferences.yaml", prof / "preferences.yaml")
    shutil.copy(ROOT_FIX / "facts.json", prof / "facts.json")
    if with_resume:
        (prof / "resume.pdf").write_bytes(b"%PDF-1.4 fixture")
    return prof


def test_import_owner_is_golden_and_onboarded(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    report = import_profile(conn, 1, _profile(tmp_path), tmp_path, NOW)
    row = conn.execute("SELECT * FROM user_prefs WHERE user_id = 1").fetchone()
    assert row["onboarded_at"] and json.loads(row["data"])["roles"]
    assert conn.execute("SELECT name FROM users WHERE id = 1").fetchone()[0] == "Asha Owner"
    assert conn.execute("SELECT edited FROM user_facts WHERE user_id = 1").fetchone()[0] == 1
    resume = tmp_path / "data" / "users" / "1" / "resume.pdf"
    assert resume.read_bytes().startswith(b"%PDF") and oct(resume.stat().st_mode)[-3:] == "600"
    assert (tmp_path / "config" / "app.yaml").exists()
    assert any("imported" in line for line in report)


def test_golden_fields_match_original(tmp_path):
    from jobseeker.db.profile import get_user_prefs
    conn = connect(tmp_path / "db.sqlite")
    import_profile(conn, 1, _profile(tmp_path), tmp_path, NOW)
    from jobseeker.config import effective_prefs, load_app_config
    eff = effective_prefs(get_user_prefs(conn, 1), load_app_config(tmp_path / "config" / "app.yaml"),
                          "Asha Owner", "owner@example.com")
    assert golden_fields(eff) == golden_fields(load_preferences(ROOT_FIX / "preferences.yaml"))


def test_existing_app_yaml_is_not_overwritten(tmp_path):
    from jobseeker.config import REPO_ROOT
    (tmp_path / "config").mkdir()
    mine = (REPO_ROOT / "config" / "app.example.yaml").read_text().replace("min_prescore: 30", "min_prescore: 99")
    (tmp_path / "config" / "app.yaml").write_text(mine)
    import_profile(connect(tmp_path / "db.sqlite"), 1, _profile(tmp_path), tmp_path, NOW)
    assert (tmp_path / "config" / "app.yaml").read_text() == mine


def test_unmatched_query_becomes_custom_role(tmp_path):
    prof = _profile(tmp_path)
    text = (prof / "preferences.yaml").read_text().replace("queries: [", "queries: [Chief of Staff, ")
    (prof / "preferences.yaml").write_text(text)
    conn = connect(tmp_path / "db.sqlite")
    import_profile(conn, 1, prof, tmp_path, NOW)
    from jobseeker.db.profile import get_user_prefs
    assert get_user_prefs(conn, 1).custom_role == "Chief of Staff"
