import pytest

from jobseeker.pipeline.prescore import prescore
from tests.factories import make_job


def test_default_job(prefs, facts):
    # title 40 + skills SQL, A/B Testing = 6 + experience "2-4 years" = 20 + Bengaluru = 10
    assert prescore(make_job(), facts, prefs) == 76


@pytest.mark.parametrize("title,points", [
    ("Senior Product Analyst", 40), ("APM - Growth", 40), ("Founder's Office Associate", 40),
    ("Chief of Staff", 40), ("Product Manager II", 35), ("Growth Lead", 20), ("Program Lead", 5),
])
def test_title_points(prefs, facts, title, points):
    job = make_job(title=title, jd_text="", location_city=None, is_remote=False)
    assert prescore(job, facts, prefs) == points + 15 + 12


def test_skills_capped_and_neutral_when_empty(prefs, facts):
    many = " ".join(facts.skills) * 3
    full = make_job(jd_text=many, location_city=None)
    assert prescore(full, facts, prefs) == 40 + 18 + 12  # 6 skills x 3
    facts.skills = [f"skill{i}" for i in range(20)]
    capped = make_job(jd_text=" ".join(facts.skills), location_city=None)
    assert prescore(capped, facts, prefs) == 40 + 30 + 12


@pytest.mark.parametrize("jd,points", [
    ("1-3 years of experience", 20), ("5+ years of experience", 12), ("6+ years of experience", 4), ("", 12),
])
def test_experience_points(prefs, facts, jd, points):
    job = make_job(jd_text=jd, location_city=None)
    skills = 15 if not jd else 0
    assert prescore(job, facts, prefs) == 40 + skills + points


def test_location_points(prefs, facts):
    base = dict(jd_text="", title="Product Analyst")
    assert prescore(make_job(location_city="pune", **base), facts, prefs) == 40 + 15 + 12 + 10
    assert prescore(make_job(location_city=None, is_remote=True, **base), facts, prefs) == 40 + 15 + 12 + 8
    assert prescore(make_job(location_city="mumbai", **base), facts, prefs) == 40 + 15 + 12
