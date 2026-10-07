import re
from pathlib import Path

from fastapi.testclient import TestClient

from jobseeker.web.app import create_app

STATIC = Path(__file__).resolve().parents[1] / "src" / "jobseeker" / "web" / "static"


def client(settings):
    return TestClient(create_app(settings))


def test_shell_has_sidebar_tabbar_and_active_page(settings, seeded):
    html = client(settings).get("/today").text
    assert '<nav class="sidebar"' in html and '<nav class="tabbar"' in html
    for href in ('href="/today"', 'href="/"', 'href="/pipeline"'):
        assert html.count(href) >= 2, href  # once in the sidebar, once in the tab bar
    assert re.search(r'<a class="nav-item is-active"[^>]*href="/today"', html)
    assert 'href="/static/ui.css?v=' in html


def test_job_page_marks_jobs_tab_active(settings, seeded):
    html = client(settings).get(f"/applications/{seeded[0]}").text
    assert re.search(r'<a class="nav-item is-active"[^>]*href="/"', html)


def test_no_external_stylesheets_or_scripts(settings, seeded):
    html = client(settings).get("/today").text
    assert not re.search(r'<(link|script)[^>]+(href|src)="https?://', html)


def test_ui_css_contract():
    css = (STATIC / "ui.css").read_text()
    for token in ("#FBFBF9", "#3B5BF5", "#ECFDF5", "#FFFBEB", "#FEF2F2", "--radius-card: 16px"):
        assert token in css, token
    assert '@font-face' in css and 'fonts/Geist-Variable.woff2' in css and 'fonts/JetBrainsMono-Variable.woff2' in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    phone = css[css.index("@media (max-width: 640px)"):]
    assert "font-size: 16px" in phone and "env(safe-area-inset-bottom)" in phone
    assert "min-height: 44px" in css


def test_fonts_are_served(settings):
    c = client(settings)
    for name in ("Geist-Variable.woff2", "JetBrainsMono-Variable.woff2"):
        r = c.get(f"/static/fonts/{name}")
        assert r.status_code == 200 and r.content[:4] == b"wOF2", name


def test_today_dashboard_greets_and_shows_stat_tiles(settings, seeded):
    from jobseeker.db.core import connect

    a, b = seeded
    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id IN (?, ?)", (a, b))
    conn.commit()
    html = client(settings).get("/today").text
    assert re.search(r"Good (morning|afternoon|evening), Kshitij\.", html)
    for label in ("New today", "Ready to approve", "Need contacts", "Send in Gmail"):
        assert f'<span class="stat-label">{label}</span>' in html, label
    assert 'href="#find"' in html and 'id="find"' in html
    assert 'class="pill tier-good"' in html  # seeded score 88 -> good tier pill


def test_today_greeting_follows_local_hour(settings, seeded, monkeypatch):
    from jobseeker.web import pipeline as pipeline_routes

    for hour, word in ((8, "morning"), (14, "afternoon"), (21, "evening")):
        monkeypatch.setattr(pipeline_routes, "_local_hour", lambda h=hour: h)
        assert f"Good {word}, Kshitij." in client(settings).get("/today").text


def test_jobs_page_chip_filters_and_tier_pills(settings, seeded):
    html = client(settings).get("/?band=all").text
    assert '<a class="chip is-active" href="/?band=all' in html
    assert '<a class="chip" href="/?band=apply' in html and '<a class="chip" href="/?band=review' in html
    a = seeded[0]
    card = html.split(f'<li class="swipe-card" data-app-id="{a}" data-swipe>', 1)[1].split("</li>", 1)[0]
    assert 'class="pill tier-good"' in card  # 88
    assert '<div class="swipe-bg" aria-hidden="true">' in card and '<div class="card-body">' in card
    assert ">Skip</button>" in card and ">Snooze</button>" in card
    assert 'data-keys="rows"' in html  # desktop table keeps j/k navigation


def test_jobs_chip_links_keep_other_filters(settings, seeded):
    html = client(settings).get("/?band=review&city=bengaluru").text
    assert '<a class="chip" href="/?band=apply&amp;city=bengaluru">' in html  # switching band keeps the city
    assert 'href="/?band=review">All cities</a>' in html  # clearing city keeps the band


def _drafted(settings, app_id):
    from jobseeker.db.core import connect
    from jobseeker.db.applications import save_draft

    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id = ?", (app_id,))
    conn.commit()
    save_draft(conn, app_id, "email", "Hello", "Body", edited=False)
    return conn


def test_job_page_decision_block_with_ring_and_bars(settings, seeded):
    a = seeded[0]
    html = client(settings).get(f"/applications/{a}").text
    assert 'class="ring tier-good"' in html and '<span class="ring-score">88</span>' in html
    assert "Good match" in html
    assert '<span class="bar-label">Role fit</span>' in html and "30/30" in html  # seeded breakdown role_fit 30
    assert "Why you match" in html and "Watch out" in html
    assert "✓ SQL" in html and "⚠ Tableau" in html


def test_job_page_step_bar_tracks_status(settings, seeded):
    a = seeded[0]
    conn = _drafted(settings, a)
    html = client(settings).get(f"/applications/{a}").text
    assert 'class="steps"' in html and 'class="step is-current"' in html
    current = html.split('class="step is-current"', 1)[1][:120]
    assert "Find contacts" in current
    nxt = html.split('class="next-action"', 1)[1].split("</section>", 1)[0]
    assert f'action="/applications/{a}/contacts/find"' in nxt
    conn.execute("UPDATE applications SET status = 'approved' WHERE id = ?", (a,))
    conn.commit()
    html = client(settings).get(f"/applications/{a}").text
    assert "Send in Gmail" in html.split('class="step is-current"', 1)[1][:120]
    nxt = html.split('class="next-action"', 1)[1].split("</section>", 1)[0]
    assert "mail.google.com/mail/u/0/#drafts" in nxt and 'value="sent"' in nxt


def test_job_page_without_score_or_step_still_renders(settings, seeded):
    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    conn.execute("DELETE FROM scores WHERE job_id = (SELECT job_id FROM applications WHERE id = ?)", (a,))
    conn.execute("UPDATE applications SET status = 'snoozed' WHERE id = ?", (a,))
    conn.commit()
    r = client(settings).get(f"/applications/{a}")
    assert r.status_code == 200 and 'class="ring' not in r.text and 'class="steps"' not in r.text


def test_more_menu_holds_rare_actions(settings, seeded):
    a = seeded[0]
    _drafted(settings, a)
    html = client(settings).get(f"/applications/{a}").text
    more = html.split('<details class="more-menu">', 1)[1].split("</details>", 1)[0]
    for label in ("Skip", "Snooze 3d", "Applied via portal", "Not interested", "Regenerate all"):
        assert label in more, label


def test_approve_explains_nothing_is_sent(settings, seeded):
    html = client(settings).get(f"/applications/{seeded[0]}").text
    approve = html.split('class="approve"', 1)[1].split("</form>", 1)[0]
    assert "Nothing is sent until you press Send" in approve or "you press Send" in approve


def test_job_page_phone_tabs_and_timeline(settings, seeded):
    a = seeded[0]
    _drafted(settings, a)
    c = client(settings)
    c.post(f"/applications/{a}/status", data={"status": "skipped"})
    c.post(f"/applications/{a}/undo")
    html = c.get(f"/applications/{a}").text
    assert '<div class="job-body" data-tabs data-default="people">' in html
    for name in ("people", "draft", "job"):
        assert f'data-tab="{name}"' in html and f'data-panel="{name}"' in html
    assert "is-hidden" not in html.split('<div class="job-body"', 1)[1]  # no JS: everything visible
    assert '<ol class="timeline">' in html and "Undid skipped, back to drafted" in html
    assert 'src="/static/tabs.js?v=' in html
    assert '<details class="add-person">' in html  # "Add someone myself" is collapsed behind a link


def test_job_page_default_tab_follows_status(settings, seeded):
    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    for status, tab in (("approved", "draft"), ("sent", "job"), ("drafted", "people")):
        conn.execute("UPDATE applications SET status = ? WHERE id = ?", (status, a))
        conn.commit()
        assert f'data-tabs data-default="{tab}"' in client(settings).get(f"/applications/{a}").text, status


def test_people_card_restyled_with_rank_and_status_pills(settings, seeded):
    from jobseeker.db.contacts_repo import link_contact, upsert_contact
    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    for rank, (name, st) in enumerate([("Asha Rao", "verified"), ("Vikram Singh", "unverified")], start=1):
        cid = upsert_contact(conn, "CRED", name, "PM", f"https://www.linkedin.com/in/{name[:4].lower()}",
                             f"{name[:4].lower()}@cred.club", st)
        link_contact(conn, a, rank, cid, "peer", "r", "smtp")
    html = client(settings).get(f"/applications/{a}").text
    card = html.split('id="people-card"', 1)[1]
    assert card.count('<article class="person">') == 2
    assert '<span class="rank mono">#1</span>' in card and '<span class="pill tier-strong">verified</span>' in card
    assert '<span class="pill tier-good">likely</span>' in card


def test_pipeline_columns_chips_and_default_stage(settings, seeded):
    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id = ?", (a,))
    conn.commit()
    html = client(settings).get("/pipeline").text
    assert '<div class="board" data-tabs data-default="drafted">' in html
    for stage in ("shortlisted", "drafted", "approved", "sent", "replied", "interview", "offer", "closed"):
        assert f'data-tab="{stage}"' in html and f'data-panel="{stage}"' in html, stage
    col = html.split('data-panel="drafted"', 1)[1].split("</section>", 1)[0]
    assert f'href="/applications/{a}"' in col and 'class="pill tier-good"' in col
    assert '<span class="next-step find">Find contacts →</span>' in col
    assert 'name="next" value="/pipeline"' in col  # Move keeps you on the board


def test_pipeline_opens_on_sent_when_a_follow_up_is_due(settings, seeded):
    from datetime import UTC, datetime, timedelta

    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    then = (datetime.now(UTC) - timedelta(days=6)).isoformat(timespec="seconds")
    conn.execute("UPDATE applications SET status = 'sent' WHERE id = ?", (a,))
    conn.execute("UPDATE events SET at = ? WHERE application_id = ?", (then, a))
    conn.commit()
    html = client(settings).get("/pipeline").text
    assert 'data-tabs data-default="sent"' in html and 'class="kcard due"' in html


def test_pipeline_closed_group_and_empty_columns(settings, seeded):
    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET status = 'rejected' WHERE id = ?", (a,))
    conn.commit()
    html = client(settings).get("/pipeline").text
    closed = html.split('data-panel="closed"', 1)[1].split("</section>", 1)[0]
    assert f'href="/applications/{a}"' in closed
    assert "Nothing offer yet." not in html and "No offers yet." in html


def test_legacy_stylesheets_are_gone(settings, seeded):
    html = client(settings).get("/today").text
    assert "app.css" not in html and "mobile.css" not in html
    assert not (STATIC / "app.css").exists() and not (STATIC / "mobile.css").exists()


def test_tablet_layout_contract():
    css = (STATIC / "ui.css").read_text()
    tablet = css[css.index("@media (min-width: 641px) and (max-width: 1240px)"):]
    assert ".shell { grid-template-columns: 72px" in tablet  # sidebar becomes an icon rail
    assert 'grid-template-areas: "people" "draft" "job"' in tablet  # job page stacks into one column
    assert ".table-card { overflow-x: auto; }" in css  # the Jobs table scrolls instead of being clipped


def test_sent_job_with_follow_up_due_opens_on_people(settings, seeded):
    from datetime import UTC, datetime, timedelta

    from jobseeker.db.contacts_repo import link_contact, upsert_contact
    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    cid = upsert_contact(conn, "CRED", "Asha Rao", "PM", "https://www.linkedin.com/in/asha", "asha@cred.club", "verified")
    link_contact(conn, a, 1, cid, "peer", "r", "smtp")
    then = (datetime.now(UTC) - timedelta(days=6)).isoformat(timespec="seconds")
    conn.execute("UPDATE applications SET status = 'sent' WHERE id = ?", (a,))
    conn.execute("UPDATE application_contacts SET emailed_at = ? WHERE application_id = ?", (then, a))
    conn.execute("UPDATE events SET at = ? WHERE application_id = ?", (then, a))
    conn.commit()
    html = client(settings).get(f"/applications/{a}").text
    assert 'data-tabs data-default="people"' in html
    nxt = html.split('class="next-action"', 1)[1].split("</section>", 1)[0]
    assert 'href="#people-card"' in nxt and "Follow up now" in nxt
