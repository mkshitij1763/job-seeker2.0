def test_settings_card_states_rendered(client_as, settings):
    html = client_as(1).get("/settings").text
    assert "data-push-card" in html and "Daily match alerts" in html
    for text in ("Add Job Seeker to your Home Screen first: Share → Add to Home Screen, then open it from there.",
                 "Turn on alerts", "On for this device", "Send a test", "Turn off",
                 "Notifications are blocked. Turn them on in iOS Settings → Notifications → Job Seeker.",
                 "Alerts aren't set up on this server"):
        assert text in html
    assert 'src="/static/push' in html


def test_push_js_only_on_settings(client_as):
    assert "/static/push" not in client_as(1).get("/today").text


def test_toggle_saves_notify_pref(client_as, settings):
    import json

    from jobseeker.db.core import connect

    c = client_as(1)
    c.post("/settings/prefs/alerts", data={})  # unchecked box = off
    data = json.loads(connect(settings.db_path).execute("SELECT data FROM user_prefs WHERE user_id = 1").fetchone()[0])
    assert data["notify_new_matches"] is False
    c.post("/settings/prefs/alerts", data={"notify_new_matches": "on"})
    data = json.loads(connect(settings.db_path).execute("SELECT data FROM user_prefs WHERE user_id = 1").fetchone()[0])
    assert data["notify_new_matches"] is True
