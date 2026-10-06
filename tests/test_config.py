import pytest

from jobseeker.config import load_companies, load_rubric


def test_preferences_load(prefs):
    assert prefs.cities == ["Bengaluru", "Gurgaon", "Noida", "Pune"]
    assert prefs.thresholds.apply == 70
    assert prefs.models.drafting == "openai/gpt-oss-120b"
    assert "intern" in prefs.title_deny and "product" in prefs.title_allow


def test_rubric_sums_to_100(rubric):
    assert sum(d.max for d in rubric.dimensions) == 100
    assert [d.key for d in rubric.dimensions] == [
        "role_fit", "experience_fit", "skills_match", "company", "location_pay"]


def test_rubric_rejects_bad_total(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("version: x\ndimensions:\n  - {key: role_fit, max: 50, guidance: g}\n")
    with pytest.raises(ValueError, match="sum to 100"):
        load_rubric(p)


def test_companies_load(settings):
    companies = load_companies(settings.companies_path)
    assert any(c.slug == "sarvam" and c.ats == "ashby" for c in companies)


def test_settings_paths(settings, home):
    assert settings.db_path == home / "data" / "jobseeker.db"
    assert settings.resume_path == home / "profile" / "resume.pdf"


def test_search_defaults_when_block_missing(prefs):
    assert prefs.search.sites == ["linkedin", "naukri", "indeed"]
    assert prefs.search.queries[0] == "Product Analyst"
    assert prefs.search.linkedin_descriptions_per_run == 15
    assert prefs.min_prescore == 30


def test_search_block_parsed(tmp_path):
    from jobseeker.config import load_preferences

    p = tmp_path / "p.yaml"
    p.write_text("""name: A
email: a@x.com
linkedin: https://l
experience_summary: x
target_roles: [PM]
cities: [Pune]
current_ctc_lpa: 1
target_base_lpa: 2
min_prescore: 45
search:
  queries: [APM]
  sites: [naukri]
""")
    prefs = load_preferences(p)
    assert prefs.search.queries == ["APM"] and prefs.search.sites == ["naukri"]
    assert prefs.search.hours_old == 72 and prefs.min_prescore == 45
