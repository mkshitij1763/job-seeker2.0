def _onboard(conn, uid):
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (?, '{}', 1, NULL, 't', 't')""", (uid,))


def test_outreach_limits_split_among_outreach_users(settings):
    from jobseeker.config import ContactsConfig
    from jobseeker.db.core import connect
    from jobseeker.db.usage import outreach_limits
    from jobseeker.db.users import set_outreach
    conn, cfg = connect(settings.db_path), ContactsConfig()
    assert outreach_limits(conn, cfg, 20)["tavily"].share_cap == cfg.tavily_monthly_limit       # owner alone: all
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    _onboard(conn, 2)
    assert outreach_limits(conn, cfg, 20)["tavily"].share_cap == cfg.tavily_monthly_limit       # matching-only: no share
    set_outreach(conn, 2, True)
    lim = outreach_limits(conn, cfg, 20)
    assert lim["tavily"].share_cap == cfg.tavily_monthly_limit // 2 and lim["draft"].share_cap == 10
    assert lim["apify"].share_cap == round(cfg.apify_monthly_usd_limit / 2, 2)
    assert lim["tavily"].global_cap == cfg.tavily_monthly_limit


def test_summary_shows_mine_and_all(settings):
    from datetime import UTC, datetime

    from jobseeker.config import ContactsConfig
    from jobseeker.db.core import connect
    from jobseeker.db.usage import Budget, outreach_limits
    conn = connect(settings.db_path)
    Budget(conn, 1, outreach_limits(conn, ContactsConfig(), 20), datetime.now(UTC)).spend("tavily", 3)
    s = Budget(conn, 1, outreach_limits(conn, ContactsConfig(), 20), datetime.now(UTC)).summary()
    assert s.startswith("Your Tavily 3/950 · All 3/950")


def test_exhausted_note_names_share_or_shared_budget(settings):
    from datetime import UTC, datetime

    from jobseeker.config import ContactsConfig
    from jobseeker.db.core import connect
    from jobseeker.db.usage import Budget, outreach_limits
    conn = connect(settings.db_path)
    b = Budget(conn, 1, outreach_limits(conn, ContactsConfig(tavily_monthly_limit=2), 20),
               datetime(2026, 10, 8, tzinfo=UTC))
    b.spend("tavily", 2)
    assert b.exhausted_note("tavily", "Tavily") == "Your Tavily share is used for October"
