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
