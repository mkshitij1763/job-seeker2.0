from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.pipeline.prefilter import min_years_required, prefilter
from tests.factories import make_job

NOW = datetime(2026, 10, 7, tzinfo=UTC)


@pytest.mark.parametrize("text,expected", [
    ("Requires 8+ years of experience in analytics", 8),
    ("2-8 years of relevant experience", 2),
    ("3 to 5 yrs experience", 3),
    ("Experience: 10+ years", 10),
    ("We were founded 10 years ago and serve 5 years of data", None),
    ("8+ years of product experience; 2 years experience with Tableau", 2),
    ("No requirement stated", None),
])
def test_min_years(text, expected):
    assert min_years_required(text) == expected


def test_keeps_good_job(prefs):
    assert prefilter(make_job(), prefs, NOW, set()) is None


def test_drops_title_deny_word_boundary(prefs):
    assert prefilter(make_job(title="Product Analyst Intern"), prefs, NOW, set()) == "title: intern"
    assert prefilter(make_job(title="Internal Tools Product Analyst"), prefs, NOW, set()) is None


def test_drops_titles_outside_allow_list(prefs):
    assert prefilter(make_job(title="Customer Support Lead"), prefs, NOW, set()) == "title: not a target role"
    assert prefilter(make_job(title="Chief of Staff to CEO"), prefs, NOW, set()) is None
    assert prefilter(make_job(title="Founder's Office Associate"), prefs, NOW, set()) is None


def test_location_rules(prefs):
    assert prefilter(make_job(location="Hyderabad", location_city="hyderabad"), prefs, NOW, set()) == "location: Hyderabad"
    assert prefilter(make_job(location="Remote - India", location_city=None, is_remote=True), prefs, NOW, set()) is None
    assert prefilter(make_job(location="Remote - US", location_city=None, is_remote=True), prefs, NOW, set()) == "location: Remote - US"
    assert prefilter(make_job(location="", location_city=None), prefs, NOW, set()) is None


def test_experience_and_age_and_block(prefs):
    assert prefilter(make_job(jd_text="10+ years of experience"), prefs, NOW, set()) == "experience: 10+ years"
    assert prefilter(make_job(posted_at=NOW - timedelta(days=8)), prefs, NOW, set()) == "stale: posted 8 days ago"
    assert prefilter(make_job(company="CRED Pvt Ltd"), prefs, NOW, {"cred"}) == "blocked company"


@pytest.mark.parametrize("text", [
    "Founded 10 years ago, we have deep experience in fintech.",
    "We have served customers for over 12 years. Experience with SQL is a must.",
    "10 years ago we gained experience in lending.",
])
def test_min_years_ignores_non_requirement_phrases(text):
    assert min_years_required(text) is None


@pytest.mark.parametrize("title", [
    "Senior Product Designer", "Lead Product Designer", "Senior Staff Engineer, Product Security",
    "Product Engineering Manager", "Senior Manager - Product Marketing",
])
def test_drops_non_pm_product_titles(prefs, title):
    assert prefilter(make_job(title=title), prefs, NOW, set()).startswith("title: ")


@pytest.mark.parametrize("title", [
    "Product Management - Associate Product Manager - Travel.", "Product Manager II",
    "Associate - User Growth (Market intelligence)", "Senior Product Analyst",
])
def test_keeps_target_titles(prefs, title):
    assert prefilter(make_job(title=title), prefs, NOW, set()) is None


@pytest.mark.parametrize("text,expected", [
    ("1.5 years of experience in analytics", 1.5),
    ("2.5+ years of experience", 2.5),
    ("Experience: 3-5 Yrs", 3),
])
def test_min_years_decimals(text, expected):
    assert min_years_required(text) == expected


@pytest.mark.parametrize("jd,reason", [
    ("2-4 years of experience", None),
    ("1.5 years of experience", None),
    ("No experience stated", None),
    ("2.5 years of experience", "experience: 2.5+ years"),
    ("3-5 years of experience", "experience: 3+ years"),
    ("Experience: 3-5 Yrs", "experience: 3+ years"),
])
def test_drops_jobs_requiring_two_and_a_half_years_or_more(prefs, jd, reason):
    assert prefilter(make_job(jd_text=jd), prefs, NOW, set()) == reason


def test_min_years_decimal_upper_bound_uses_lower_bound():
    assert min_years_required("2-4.5 years of experience") == 2


@pytest.mark.parametrize("text,expected", [
    ("* 7+ years in product analytics, growth analytics, or data science", 7),
    ("3-5 years as a product manager at a consumer company", 3),
    ("2+ years working on consumer products", 2),
    ("We have been 10 years in business and love it", None),
])
def test_min_years_plus_or_range_followed_by_in_as_working(text, expected):
    assert min_years_required(text) == expected
