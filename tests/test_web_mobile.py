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
                    'name="apple-mobile-web-app-capable" content="yes"', 'href="/static/mobile.css?v=',
                    '<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>']:
        assert snippet in html, snippet


def test_manifest(settings):
    data = json.loads(client(settings).get("/static/manifest.webmanifest").content)
    assert data["display"] == "standalone" and data["start_url"] == "/today"
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
    assert '<script src="/static/swipe.js?v=' in client(settings).get("/").text


def test_inbox_filters_fold_and_cards_render(settings, seeded):
    html = client(settings).get("/").text
    assert 'class="chips filter-chips"' in html
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


def test_job_page_blocks_and_more_menu(settings, seeded):
    a = seeded[0]
    html = client(settings).get(f"/applications/{a}").text
    for hook in ['class="job-head"', 'class="card block drafts"', 'class="card block contact"',
                 'class="card block history"', 'class="card block actions"']:
        assert hook in html, hook
    actions = html.split('class="card block actions"', 1)[1]
    assert actions.index("Approve → Gmail draft") < actions.index('<details class="more-menu">')
    more = actions.split('<details class="more-menu">', 1)[1].split("</details>", 1)[0]
    assert 'aria-label="More actions"' in more
    for label in ("Mark sent", "Applied via portal", "Skip", "Snooze 3d", "Not interested", "Regenerate all",
                  "Undo last change"):
        assert label in more, label


def test_copy_note_and_open_linkedin_are_separate(settings, seeded):
    html = client(settings).get(f"/applications/{seeded[0]}").text
    assert "data-open=" not in html
    assert '<button type="button" data-copy="#li_note">Copy note</button>' in html
    assert '<a class="btn" href="https://www.linkedin.com/search/x" target="_blank" rel="noopener">Open LinkedIn ↗</a>' in html


def test_contact_inputs_are_phone_friendly(settings, seeded):
    html = client(settings).get(f"/applications/{seeded[0]}").text
    assert '<input name="linkedin_url" type="url" inputmode="url" autocapitalize="off" autocorrect="off"' in html
    assert '<input name="email" type="email" inputmode="email" autocapitalize="off" autocorrect="off"' in html


def test_jd_summary_counts_matched_skills(settings, seeded, facts):
    import json as _json
    settings.facts_path.write_text(_json.dumps({"resume_sha256": "x", "facts": facts.model_dump()}))
    html = client(settings).get(f"/applications/{seeded[0]}").text
    # seeded JD: "We want SQL and A/B Testing skills." -> SQL and A/B Testing are among the facts' skills
    assert "Job description · 2 skills matched" in html


def test_pipeline_columns_are_collapsible(settings, seeded):
    from jobseeker.db.queries import PIPELINE_COLUMNS

    html = client(settings).get("/pipeline").text
    assert html.count('<details class="col" open data-count="') == len(PIPELINE_COLUMNS)
    assert '<details class="col" open data-count="1">' in html  # seeded: one drafted application
    assert '<details class="col" open data-count="0">' in html


def test_swipe_rebinds_after_htmx_history_restore():
    js = (STATIC / "swipe.js").read_text()
    assert "new WeakSet()" in js and "swipeBound" not in js  # a DOM marker survives into history snapshots
    assert '"htmx:historyRestore"' in js and '"htmx:beforeHistorySave"' in js


def test_keys_js_unfolds_when_leaving_phone_width():
    js = (STATIC / "keys.js").read_text()
    assert 'addEventListener("change"' in js and 'setAttribute("open", "")' in js
    assert '"htmx:historyRestore"' in js


def test_card_refresh_does_not_refold_open_sections():
    js = (STATIC / "keys.js").read_text()
    assert "function foldForPhone(root)" in js and "root.querySelectorAll" in js
    assert "e.detail.elt" in js  # fold only the swapped element, never the whole page
    assert 'addEventListener("htmx:afterSwap", (e) => foldForPhone(rootOf(e)))' in js  # before paint: no flash
    assert 'addEventListener("htmx:afterSettle", (e) => init(rootOf(e)))' in js


def test_static_assets_are_fingerprinted_so_phones_get_updates(settings, seeded):
    import hashlib

    html = client(settings).get("/").text
    for name in ("app.css", "mobile.css", "swipe.js", "keys.js", "htmx.min.js"):
        digest = hashlib.sha1((STATIC / name).read_bytes()).hexdigest()[:8]
        assert f"/static/{name}?v={digest}" in html, name


def _card(html, a):
    return html.split(f'<li class="swipe-card" data-app-id="{a}" data-swipe>', 1)[1].split("</li>", 1)[0]


def test_compact_card_shows_next_step_one_match_and_count(settings, seeded):
    from jobseeker.db.contacts_repo import link_contact, upsert_contact
    from jobseeker.db.core import connect

    a, b = seeded[0], seeded[1]
    conn = connect(settings.db_path)
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id IN (?, ?)", (a, b))
    conn.execute("UPDATE scores SET recommendation = 'apply', matches = '[\"SQL\", \"A/B tests\"]'")
    cid = upsert_contact(conn, "CRED", "Asha Rao", "PM", "https://www.linkedin.com/in/asha", "a@cred.club", "verified")
    link_contact(conn, b, 1, cid, "peer", "r", "smtp")
    html = client(settings).get("/").text
    assert 'class="next-step find">Find contacts →' in _card(html, a)
    assert 'class="next-step ready">Ready to approve →' in _card(html, b)
    assert "✓ SQL" in _card(html, a) and "✓ A/B tests" not in _card(html, a)  # one match keeps cards short
    assert 'class="inbox-count">2 jobs' in html


def test_fingerprinted_assets_are_cached_for_good_and_pages_are_compressed(settings, seeded):
    import re as _re

    c = client(settings)
    html = c.get("/").text
    css = _re.search(r'/static/app\.css\?v=[0-9a-f]+', html).group(0)
    r = c.get(css)
    assert "immutable" in r.headers["cache-control"] and "max-age=31536000" in r.headers["cache-control"]
    assert "immutable" not in c.get("/static/app.css").headers.get("cache-control", "")  # unversioned: revalidate
    assert c.get("/", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") == "gzip"
