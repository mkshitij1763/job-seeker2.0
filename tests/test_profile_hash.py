from jobseeker.pipeline.profile_hash import profile_hash


def test_stable_and_order_insensitive(prefs, facts):
    h = profile_hash(prefs, facts)
    assert len(h) == 64 and h == profile_hash(prefs, facts)
    shuffled = prefs.model_copy(update={"cities": list(reversed(prefs.cities)),
                                        "target_roles": list(reversed(prefs.target_roles))})
    assert profile_hash(shuffled, facts) == h


def test_scoring_fields_change_it(prefs, facts):
    h = profile_hash(prefs, facts)
    assert profile_hash(prefs.model_copy(update={"experience_summary": "x"}), facts) != h
    assert profile_hash(prefs, facts.model_copy(update={"skills": ["Rust"]})) != h
    assert profile_hash(prefs.model_copy(update={"must_haves": ["remote"]}), facts) != h


def test_filter_only_fields_do_not(prefs, facts):
    h = profile_hash(prefs, facts)
    for update in ({"title_deny": ["intern"]}, {"title_allow": ["x"]}, {"drop_if_min_years_at_least": 9},
                   {"max_age_days": 3}):
        assert profile_hash(prefs.model_copy(update=update), facts) == h
