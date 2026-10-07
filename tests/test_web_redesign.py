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
