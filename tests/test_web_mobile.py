import json
import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobseeker.web.app import create_app

STATIC = Path(__file__).resolve().parents[1] / "src" / "jobseeker" / "web" / "static"


def client(settings):
    return TestClient(create_app(settings))


def test_base_has_phone_meta_and_toast(settings, seeded):
    html = client(settings).get("/").text
    for snippet in ['viewport-fit=cover', '<link rel="manifest" href="/static/manifest.webmanifest">',
                    '<link rel="apple-touch-icon" href="/static/icon-180.png">', '<meta name="theme-color"',
                    'name="apple-mobile-web-app-capable" content="yes"', 'href="/static/mobile.css"',
                    '<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>']:
        assert snippet in html, snippet


def test_manifest(settings):
    data = json.loads(client(settings).get("/static/manifest.webmanifest").content)
    assert data["display"] == "standalone" and data["start_url"] == "/"
    assert {i["sizes"] for i in data["icons"]} == {"180x180", "512x512"}


@pytest.mark.parametrize("name,size", [("icon-180.png", 180), ("icon-512.png", 512)])
def test_icons_are_pngs_of_the_right_size(settings, name, size):
    body = client(settings).get(f"/static/{name}").content
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", body[16:24]) == (size, size)


def test_mobile_css_contract():
    css = (STATIC / "mobile.css").read_text()
    phone = css[css.index("@media (max-width: 640px)"):]
    assert re.search(r"input, select, textarea \{[^}]*font-size: 16px", phone)
    assert re.search(r"min-height: 44px", phone)
    assert "env(safe-area-inset-bottom)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    desktop = css[css.index("@media (min-width: 641px)"):]
    assert ".phone-only-summary" in desktop.split("}")[0] and "display: none" in desktop.split("}")[0]


def test_swipe_script_loaded(settings, seeded):
    assert '<script src="/static/swipe.js" defer></script>' in client(settings).get("/").text


def test_inbox_filters_fold_and_cards_render(settings, seeded):
    html = client(settings).get("/").text
    assert '<details class="filters-box" open data-phone-closed>' in html
    assert '<summary class="phone-only-summary">Filters</summary>' in html
    a = seeded[0]
    assert f'<li class="swipe-card" data-app-id="{a}" data-swipe>' in html
    card = html.split(f'<li class="swipe-card" data-app-id="{a}" data-swipe>', 1)[1].split("</li>", 1)[0]
    assert '<div class="swipe-bg" aria-hidden="true">' in card and '<div class="card-body">' in card
    assert ">Skip</button>" in card and ">Snooze</button>" in card  # the non-swipe alternative stays
    assert f'href="/applications/{a}"' in card


def test_keys_js_folds_for_phone_and_copies_without_opening():
    js = (STATIC / "keys.js").read_text()
    assert "details[data-phone-closed]" in js and 'details.col[data-count="0"]' in js
    assert "dataset.open" not in js and "Copied ✓" in js
    assert 'classList.add("typing")' in js
