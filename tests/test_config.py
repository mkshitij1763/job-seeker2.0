import pytest

from jobseeker.config import REPO_ROOT, UserPrefs, effective_prefs, load_app_config, load_companies, load_rubric


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
    companies = load_companies(REPO_ROOT / "companies.yaml")
    assert any(c.slug == "sarvam" and c.ats == "ashby" for c in companies)


def test_settings_paths(settings, home):
    assert settings.db_path == home / "data" / "jobseeker.db"
    assert settings.app_config_path == home / "config" / "app.yaml"


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



def _cfg():
    return load_app_config(REPO_ROOT / "config" / "app.example.yaml")


def test_app_config_loads_catalog_and_checkout_paths():
    cfg = _cfg()
    assert [r.label for r in cfg.roles][:2] == ["Product Analyst", "Associate Product Manager"]
    assert len(cfg.roles) == 9
    assert cfg.companies_path == REPO_ROOT / "companies.yaml" and cfg.rubric_path == REPO_ROOT / "rubric.yaml"


def test_effective_prefs_maps_roles_and_defaults():
    up = UserPrefs(roles=["Product Analyst", "Founder's Office"], custom_role="Chief of Staff", cities=["Pune"],
                   experience_years=1.3, drop_if_min_years_at_least=2.5, experience_summary="x")
    p = effective_prefs(up, _cfg(), name="A B", email="a@example.com")
    assert p.target_roles == ["Product Analyst", "Founder's Office", "Chief of Staff"]
    assert set(p.title_allow) >= {"product", "analyst", "founder", "chief of staff"}
    assert p.search.queries == ["Product Analyst", "Founder's Office", "Chief of Staff"]
    assert p.title_deny == _cfg().default_title_deny
    assert p.current_ctc_lpa is None and p.min_prescore == 30 and p.name == "A B"


def test_complete_lists_missing_steps_in_order():
    assert UserPrefs().complete() == ["roles", "where", "experience"]  # remote on by default is not a choice yet
    assert UserPrefs(cities=["Pune"]).complete() == ["roles", "experience"]
    assert UserPrefs(remote_india_ok=False, where_confirmed=True).complete() == ["roles", "where", "experience"]
    up = UserPrefs(roles=["Product Analyst"], remote_india_ok=True, where_confirmed=True,
                   drop_if_min_years_at_least=2.5, experience_summary="x")
    assert up.complete() == []
    assert UserPrefs(roles=["x"], cities=["Pune"], experience_years=3, drop_if_min_years_at_least=2.5,
                     experience_summary="x").complete() == ["experience"]  # threshold must exceed years


def test_scorer_prompt_says_not_given_for_missing_ctc(facts, rubric, prefs):
    from jobseeker.scoring.scorer import _system
    text = _system(facts, prefs.model_copy(update={"current_ctc_lpa": None, "target_base_lpa": None}), rubric)
    assert "CTC not given" in text


def test_explicit_title_allow_extra_is_used_as_is():
    up = UserPrefs(title_allow_extra=["product"], roles=["Data Analyst"])
    assert effective_prefs(up, _cfg(), name="A", email="a@example.com").title_allow == ["product"]
