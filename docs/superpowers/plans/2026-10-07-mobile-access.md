# Mobile Access (Phone Layout, Swipes, Undo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard comfortable on an iPhone 15 (393 × 852). That means:
- an inbox of cards with swipe-to-skip and swipe-to-snooze, plus Undo;
- a job page with a sticky Approve bar and a More menu;
- a stacked pipeline;
- a home-screen app;

all while the desktop layout stays the same.

**Architecture:**
- **CSS:** desktop styles stay in `app.css`. All phone and touch rules go in a new `static/mobile.css`, loaded after it.
- **Templates:** they gain only the hooks the phone needs: `<details>` wrappers, block classes, the phone card list, and the toast region.
- **Swipe logic:** pure functions in `static/swipe.js`, tested with Node.
- **Undo:** a new DB function plus a POST route reverts the most recent status change.

**Tech Stack:** FastAPI, Jinja2, HTMX (`hx-boost`), vanilla JS and CSS; pytest; `node --test`, Node 26, for the swipe logic.

**Spec:** `docs/superpowers/specs/2026-10-07-mobile-access-design.md`

## Global Constraints

- **Target device:** iPhone 15, 393 × 852 CSS px, DPR 3. Safe-area insets: top ≈ 59 px, bottom 34 px.
- **Phone breakpoint:** `max-width: 640px`. Touch rule: `hover: none`.
- **Touch targets:** ≥ 44 px. Inputs, selects and textareas use 16 px text on phones (no iOS focus zoom).
- **Swipe:**
  - direction lock at 10 px, horizontal only if |dx| > 1.5 × |dy|;
  - commit at ≥ 35 % of card width, or a flick of ≥ 0.5 px/ms over ≥ 40 px;
  - ignore touches starting < 24 px from the left edge.
- **Motion:** card exit 180 ms ease-out, transform only. With `prefers-reduced-motion: reduce`, no transitions or transforms.
- **Undo:** reverts only the latest `status` event, if the current status equals its `to`. Refused after `not_interested`, and for events whose `from` is `snoozed`. Writes an `undo` event.
- **No new runtime dependency.** The app still binds to `127.0.0.1`. The desktop layout (>640 px) looks as before.
- **Verification creates no real Gmail draft.**

## Review Focus

1. **A vertical scroll that drifts sideways** (dx 20, dy 15). Expected: it scrolls and never skips. Test: Task 3 `diagonal drift is a scroll`.
2. **A swipe whose server action fails**, for example the job was already skipped on the laptop. Expected: the card comes back and the toast shows the server's error. Test: Task 3 `parseOutcome reports err from redirect`.
3. **Undo after things moved on** (a later status change, or waking from a snooze). Expected: refused with a message, and the status is untouched. Tests: Task 1 `test_undo_refused_when_status_moved_on`, `test_undo_refused_after_wake_from_snooze`.
4. **Desktop must look unchanged** while the phone-only `<summary>` rows (Filters, Job description, More) exist in the markup. Expected: hidden above 640 px. Test: Task 2 `test_mobile_css_contract`.
5. **iOS Safari zooms in** when a focused input is under 16 px. Expected: 16 px inputs at phone width. Test: Task 2 `test_mobile_css_contract`.

---

### Task 1: Undo the last status change

**Files:**
- Modify: `src/jobseeker/db/applications.py`, `src/jobseeker/web/application.py`, `src/jobseeker/web/templates/application.html`
- Test: `tests/test_web_undo.py`

**Interfaces:**
- Produces: `applications.UNDO_BLOCKED = {"not_interested"}`, `last_status_event(conn, app_id) -> dict|None`, `can_undo(conn, app_id) -> bool`, `undo_last_status(conn, app_id, now=None) -> str` (the restored status; raises `InvalidTransition`), route `POST /applications/{id}/undo` (form `next`), template variable `can_undo`.

- [ ] **Step 1: Write the failing tests `tests/test_web_undo.py`**

```python
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from jobseeker.db.applications import (
    can_undo, get_application, get_events, get_status, mark_not_interested, snooze, transition, undo_last_status,
    wake_snoozed,
)
from jobseeker.db.core import connect
from jobseeker.status import InvalidTransition
from jobseeker.web.app import create_app


def test_undo_skip_restores_previous_status(settings, seeded):
    a = seeded[0]  # drafted
    conn = connect(settings.db_path)
    transition(conn, a, "skipped")
    assert can_undo(conn, a)
    assert undo_last_status(conn, a) == "drafted"
    assert get_status(conn, a) == "drafted"
    ev = get_events(conn, a)[-1]
    assert ev["type"] == "undo" and json.loads(ev["payload"]) == {"from": "skipped", "to": "drafted"}
    assert not can_undo(conn, a)  # an undo is not itself undoable


def test_undo_snooze_clears_snooze_fields(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    snooze(conn, a, datetime(2030, 1, 1, tzinfo=UTC))
    assert undo_last_status(conn, a) == "drafted"
    app = get_application(conn, a)
    assert (app["status"], app["snoozed_until"], app["snoozed_from"]) == ("drafted", None, None)


def test_undo_refused_after_not_interested(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    mark_not_interested(conn, a, block_company=False)
    assert not can_undo(conn, a)
    with pytest.raises(InvalidTransition):
        undo_last_status(conn, a)
    assert get_status(conn, a) == "not_interested"


def test_undo_refused_when_status_moved_on(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    transition(conn, a, "skipped")
    conn.execute("UPDATE applications SET status = 'drafted' WHERE id = ?", (a,))
    conn.commit()
    assert not can_undo(conn, a)
    with pytest.raises(InvalidTransition):
        undo_last_status(conn, a)


def test_undo_refused_after_wake_from_snooze(settings, seeded):
    a = seeded[0]
    conn = connect(settings.db_path)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    snooze(conn, a, now + timedelta(days=3), now=now)
    wake_snoozed(conn, now + timedelta(days=4))
    assert get_status(conn, a) == "drafted"
    assert not can_undo(conn, a)  # undoing a wake would strand the job in "snoozed" with no wake date


def test_undo_route_and_button(settings, seeded):
    a = seeded[0]
    client = TestClient(create_app(settings), follow_redirects=False)
    client.post(f"/applications/{a}/status", data={"status": "skipped"})
    assert "Undo last change" in client.get(f"/applications/{a}").text
    r = client.post(f"/applications/{a}/undo", data={"next": "/"})
    assert r.status_code == 303 and r.headers["location"].startswith("/?msg=")
    assert get_status(connect(settings.db_path), a) == "drafted"
    r = client.post(f"/applications/{a}/undo")
    assert "err=" in r.headers["location"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_undo.py`
Expected: FAIL (`ImportError: cannot import name 'can_undo'`)

- [ ] **Step 3: Implement in `src/jobseeker/db/applications.py`** (append at the end of the file)

```python
UNDO_BLOCKED = {"not_interested"}  # its blocklist entries are not reverted


def last_status_event(conn: sqlite3.Connection, app_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM events WHERE application_id = ? AND type IN ('status', 'undo') ORDER BY id DESC LIMIT 1",
        (app_id,),
    ).fetchone()
    return dict(row) if row else None


def _undo_target(conn: sqlite3.Connection, app_id: int) -> tuple[str, str]:
    """(current status, status to restore) for an undoable latest change; raises InvalidTransition otherwise."""
    ev = last_status_event(conn, app_id)
    if not ev or ev["type"] != "status":
        raise InvalidTransition("nothing to undo")
    payload = json.loads(ev["payload"])
    frm, to = payload.get("from"), payload.get("to")
    if to in UNDO_BLOCKED:
        raise InvalidTransition(f"{to.replace('_', ' ')} can't be undone")
    if not frm or frm == "snoozed":
        raise InvalidTransition("that change can't be undone")
    if get_status(conn, app_id) != to:
        raise InvalidTransition("the status has changed since")
    return to, frm


def can_undo(conn: sqlite3.Connection, app_id: int) -> bool:
    try:
        _undo_target(conn, app_id)
    except InvalidTransition:
        return False
    return True


def undo_last_status(conn: sqlite3.Connection, app_id: int, now: datetime | None = None) -> str:
    current, restored = _undo_target(conn, app_id)
    conn.execute(
        """UPDATE applications SET status = ?, snoozed_until = NULL, snoozed_from = NULL, updated_at = ?,
           applied_via_portal = CASE WHEN ? = 'applied_via_portal' THEN 0 ELSE applied_via_portal END
           WHERE id = ?""",
        (restored, _now(now), current, app_id),
    )
    add_event(conn, app_id, "undo", {"from": current, "to": restored}, now)
    conn.commit()
    return restored
```

- [ ] **Step 4: Add the route and template variable in `src/jobseeker/web/application.py`**

Add `can_undo` and `undo_last_status` to the existing `from jobseeker.db.applications import (...)` list. Then change the `detail` route's return to:
```python
    return render(request, conn, "application.html", terms=terms, can_undo=can_undo(conn, app_id), **d)
```
and add after the `followed_up` route:
```python
@router.post("/{app_id}/undo")
def undo(app_id: int, next: str = Form(""), conn=Depends(get_conn)):
    try:
        restored = undo_last_status(conn, app_id)
    except InvalidTransition as e:
        return _back(app_id, next, err=f"Can't undo: {e}")
    return _back(app_id, next, msg=f"Undone: back to {restored.replace('_', ' ')}")
```

In `src/jobseeker/web/templates/application.html`, inside `<div class="card actions">`, directly before the `not-interested` form, add:
```html
      {% if can_undo %}<form method="post" action="/applications/{{ app.id }}/undo"><button>Undo last change</button></form>{% endif %}
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/db/applications.py src/jobseeker/web/application.py src/jobseeker/web/templates/application.html tests/test_web_undo.py
git commit -m "feat: undo the last status change (route + job page button)"
```

---

### Task 2: Phone foundation (meta, home-screen icons, toast, mobile.css contract)

**Files:**
- Create: `src/jobseeker/web/static/mobile.css`, `src/jobseeker/web/static/manifest.webmanifest`, `scripts/make_icons.py`, `src/jobseeker/web/static/icon-180.png`, `src/jobseeker/web/static/icon-512.png` (both generated)
- Modify: `src/jobseeker/web/templates/base.html`
- Test: `tests/test_web_mobile.py`

**Interfaces:**
- Produces: the `#toast` region in every page, the `mobile.css` file that later tasks append to, the `.long` span in the header error badge.

- [ ] **Step 1: Write the failing tests `tests/test_web_mobile.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_mobile.py`
Expected: FAIL (missing meta tags, a 404 for the manifest and icons, `FileNotFoundError` for `mobile.css`)

- [ ] **Step 3: Write `scripts/make_icons.py` and generate the icons**

```python
"""Generate the home-screen icons (run once; the PNGs are committed). A white briefcase on the accent blue."""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "jobseeker" / "web" / "static"
BLUE, WHITE = (37, 99, 235), (255, 255, 255)


def pixel(x: int, y: int, n: int) -> tuple[int, int, int]:
    u, v = x / n, y / n
    body = 0.22 <= u <= 0.78 and 0.36 <= v <= 0.76
    inner = 0.27 <= u <= 0.73 and 0.41 <= v <= 0.71
    handle = 0.39 <= u <= 0.61 and 0.26 <= v <= 0.37 and not (0.44 <= u <= 0.56 and v >= 0.31)
    clasp = 0.46 <= u <= 0.54 and 0.50 <= v <= 0.58
    return WHITE if (body and not inner) or handle or clasp else BLUE


def png(n: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(c for x in range(n) for c in pixel(x, y, n)) for y in range(n))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    for size in (180, 512):
        (OUT / f"icon-{size}.png").write_bytes(png(size))
        print("wrote", size)
```
Run: `uv run python scripts/make_icons.py`
Expected: `wrote 180` and `wrote 512`

- [ ] **Step 4: Write `src/jobseeker/web/static/manifest.webmanifest`**

```json
{
  "name": "Job Seeker",
  "short_name": "Job Seeker",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#fafafa",
  "theme_color": "#2563eb",
  "icons": [
    {"src": "/static/icon-180.png", "sizes": "180x180", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

- [ ] **Step 5: Replace `src/jobseeker/web/templates/base.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#2563eb">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Job Seeker">
  <title>{% block title %}Job Seeker{% endblock %}</title>
  <link rel="manifest" href="/static/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icon-180.png">
  <link rel="stylesheet" href="/static/app.css">
  <link rel="stylesheet" href="/static/mobile.css">
  <script src="/static/htmx.min.js" defer></script>
  <script src="/static/keys.js" defer></script>
</head>
<body hx-boost="true">
  <header class="top">
    <a class="brand" href="/">Job Seeker</a>
    <nav><a href="/">Inbox</a><a href="/pipeline">Pipeline</a></nav>
    {% if run_errors %}<span class="warn" title="{{ run_errors|join('\n') }}"><span class="long">Last run: </span>{{ run_errors|length }} error(s)</span>{% endif %}
  </header>
  {% if msg %}<div class="flash ok">{{ msg }}</div>{% endif %}
  {% if err %}<div class="flash err">{{ err }}</div>{% endif %}
  <main>{% block content %}{% endblock %}</main>
  <div id="toast" class="toast" role="status" aria-live="polite" hidden></div>
</body>
</html>
```

- [ ] **Step 6: Write `src/jobseeker/web/static/mobile.css`** (later tasks append sections)

```css
/* Phone and touch rules (target: iPhone 15, 393 x 852). Desktop styles live in app.css. */
:root { --skip-bg: #b91c1c; --skip-fg: #ffffff; --snooze-bg: #b45309; --snooze-fg: #ffffff; }
@media (prefers-color-scheme: dark) {
  :root { --skip-bg: #f87171; --skip-fg: #0b0b0d; --snooze-bg: #fbbf24; --snooze-fg: #0b0b0d; }
}

/* Toast: one live region, above the home indicator and any sticky bar. */
.toast { position: fixed; left: 12px; right: 12px; bottom: calc(16px + env(safe-area-inset-bottom)); z-index: 50;
  display: flex; gap: 12px; align-items: center; justify-content: space-between;
  background: var(--text); color: var(--bg); padding: 12px 14px; border-radius: 10px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, .25); }
.toast[hidden] { display: none; }
.toast button { background: transparent; color: inherit; border-color: currentColor; font-weight: 600; }

/* Pressed feedback on every tappable control, without moving its bounds. */
button, .btn { transition: opacity .1s, transform .1s; }
button:active, .btn:active { opacity: .7; transform: scale(.98); }
.btn { display: inline-flex; align-items: center; border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; }

@media (hover: none) { .hint { display: none; } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}

/* Desktop: summaries that only exist to fold content on phones stay hidden, so the desktop looks unchanged. */
@media (min-width: 641px) {
  .phone-only-summary { display: none; }
  .toast { left: auto; right: 20px; max-width: 420px; }
}

@media (max-width: 640px) {
  .top { gap: 14px; padding: calc(8px + env(safe-area-inset-top)) 16px 8px; }
  .top .long { display: none; }
  main { padding: 12px 12px calc(24px + env(safe-area-inset-bottom)); }
  .flash { margin: 8px 12px 0; }
  button, select, .btn, summary { min-height: 44px; }
  input, select, textarea { font-size: 16px; }
  input:not([type=checkbox]), select { min-height: 44px; }
  summary { padding: 10px 0; cursor: pointer; }
}
```

- [ ] **Step 7: Run tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/test_web_mobile.py && uv run pytest`
Expected: all passed

- [ ] **Step 8: Commit**

```bash
git add scripts/make_icons.py src/jobseeker/web/static/mobile.css src/jobseeker/web/static/manifest.webmanifest src/jobseeker/web/static/icon-180.png src/jobseeker/web/static/icon-512.png src/jobseeker/web/templates/base.html tests/test_web_mobile.py
git commit -m "feat: phone foundation — viewport, home-screen icons, toast region, mobile.css"
```

---

### Task 3: Swipe logic and wiring (`swipe.js`)

**Files:**
- Create: `src/jobseeker/web/static/swipe.js`, `tests/js/swipe.test.mjs`, `tests/test_js.py`
- Modify: `src/jobseeker/web/templates/base.html` (script tag)
- Test: `tests/test_web_mobile.py` (script tag present)

**Interfaces:**
- Produces:
  - pure functions `decide(start, current) -> {mode}`, `release(start, end, cardWidth) -> "skip"|"snooze"|null` and `parseOutcome(finalUrl, ok, status) -> {ok, message}`;
  - browser globals `window.JobSwipe` and `window.JobToast(text, undoFn?)`;
  - binding of every `[data-swipe]` element, which needs a `.card-body` child and a `data-app-id`.

- [ ] **Step 1: Write the failing Node tests `tests/js/swipe.test.mjs`**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { decide, release, parseOutcome } = require("../../src/jobseeker/web/static/swipe.js");
const at = (x, y, t = 0) => ({ x, y, t });

test("small moves are undecided", () => assert.equal(decide(at(100, 100), at(105, 104)).mode, "none"));
test("vertical move is a scroll", () => assert.equal(decide(at(100, 100), at(108, 140)).mode, "scroll"));
test("diagonal drift is a scroll", () => assert.equal(decide(at(100, 100), at(120, 115)).mode, "scroll"));
test("horizontal move locks to swipe after 10px", () => assert.equal(decide(at(100, 100), at(115, 103)).mode, "swipe"));
test("edge start is ignored", () => assert.equal(decide(at(10, 100), at(140, 100)).mode, "none"));
test("far left release skips", () => assert.equal(release(at(300, 100, 0), at(160, 100, 600), 360), "skip"));
test("far right release snoozes", () => assert.equal(release(at(60, 100, 0), at(200, 100, 600), 360), "snooze"));
test("short slow release snaps back", () => assert.equal(release(at(200, 100, 0), at(150, 100, 600), 360), null));
test("fast flick commits", () => assert.equal(release(at(200, 100, 0), at(140, 100, 80), 360), "skip"));
test("tiny fast jitter does not commit", () => assert.equal(release(at(200, 100, 0), at(180, 100, 10), 360), null));
test("parseOutcome success reads msg", () =>
  assert.deepEqual(parseOutcome("http://h/?msg=Marked%20skipped", true, 200), { ok: true, message: "Marked skipped" }));
test("parseOutcome reports err from redirect", () =>
  assert.deepEqual(parseOutcome("http://h/applications/3?err=Can%27t%20move", true, 200), { ok: false, message: "Can't move" }));
test("parseOutcome reports HTTP failures", () =>
  assert.deepEqual(parseOutcome("http://h/applications/3/snooze", false, 500), { ok: false, message: "Request failed (HTTP 500)" }));
```

`tests/test_js.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_swipe_logic():
    result = subprocess.run(["node", "--test", str(ROOT / "tests" / "js" / "swipe.test.mjs")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
```

Append to `tests/test_web_mobile.py`:
```python
def test_swipe_script_loaded(settings, seeded):
    assert '<script src="/static/swipe.js" defer></script>' in client(settings).get("/").text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_js.py tests/test_web_mobile.py`
Expected: FAIL (Node: `Cannot find module …swipe.js`; no script tag)

- [ ] **Step 3: Write `src/jobseeker/web/static/swipe.js`**

```js
/* Swipe left = Skip, swipe right = Snooze on inbox cards (spec §4.7). The decision functions are pure for Node tests. */
(function (root) {
  const LOCK_PX = 10;         // movement before a gesture is classified
  const EDGE_PX = 24;         // iOS edge-swipe "back" zone
  const COMMIT_RATIO = 0.35;  // of card width
  const FLICK_SPEED = 0.5;    // px per ms
  const FLICK_MIN_PX = 40;

  function decide(start, current) {
    if (start.x < EDGE_PX) return { mode: "none" };
    const dx = current.x - start.x, dy = current.y - start.y;
    if (Math.abs(dx) < LOCK_PX && Math.abs(dy) < LOCK_PX) return { mode: "none" };
    return { mode: Math.abs(dx) > 1.5 * Math.abs(dy) ? "swipe" : "scroll" };
  }

  function release(start, end, cardWidth) {
    const dx = end.x - start.x, dt = Math.max(1, end.t - start.t);
    const far = Math.abs(dx) >= COMMIT_RATIO * cardWidth;
    const flick = Math.abs(dx) >= FLICK_MIN_PX && Math.abs(dx) / dt >= FLICK_SPEED;
    if (!far && !flick) return null;
    return dx < 0 ? "skip" : "snooze";
  }

  function parseOutcome(finalUrl, ok, status) {
    const params = new URL(finalUrl, "http://localhost").searchParams;
    const err = params.get("err");
    if (!ok || err) return { ok: false, message: err || `Request failed (HTTP ${status})` };
    return { ok: true, message: params.get("msg") || "Done" };
  }

  const api = { decide, release, parseOutcome };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }
  root.JobSwipe = api;

  // ---- browser wiring ----
  const reduced = () => root.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let toastTimer;

  function toast(text, undo) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.replaceChildren();
    const span = document.createElement("span");
    span.textContent = text;
    el.appendChild(span);
    if (undo) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "Undo";
      b.addEventListener("click", () => { el.hidden = true; undo(); });
      el.appendChild(b);
    }
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
  }
  root.JobToast = toast;

  async function post(url, fields) {
    let resp;
    try {
      resp = await fetch(url, { method: "POST", body: new URLSearchParams(fields), credentials: "same-origin" });
    } catch (e) {
      return { ok: false, message: "Couldn't reach the Mac" };
    }
    return parseOutcome(resp.url, resp.ok, resp.status);
  }

  const ACTIONS = {
    skip: { label: "Skipped", send: (id) => post(`/applications/${id}/status`, { status: "skipped", next: "/" }) },
    snooze: { label: "Snoozed 3 days", send: (id) => post(`/applications/${id}/snooze`, { next: "/" }) },
  };

  function move(card, x, animate) {
    const body = card.querySelector(".card-body");
    body.style.transition = animate && !reduced() ? "transform 180ms ease-out" : "none";
    body.style.transform = x ? `translateX(${x}px)` : "";
    if (x) card.dataset.dir = x < 0 ? "skip" : "snooze"; else delete card.dataset.dir;
  }

  function bind(card) {
    if (card.dataset.swipeBound) return;
    card.dataset.swipeBound = "1";
    let start = null, mode = "none";
    card.addEventListener("touchstart", (e) => {
      const t = e.touches[0];
      start = { x: t.clientX, y: t.clientY, t: e.timeStamp };
      mode = "none";
    }, { passive: true });
    card.addEventListener("touchmove", (e) => {
      if (!start || mode === "scroll") return;
      const t = e.touches[0];
      const current = { x: t.clientX, y: t.clientY, t: e.timeStamp };
      if (mode === "none") mode = decide(start, current).mode;
      if (mode === "swipe") move(card, current.x - start.x, false);
    }, { passive: true });
    card.addEventListener("touchcancel", () => { start = null; move(card, 0, true); });
    card.addEventListener("touchend", async (e) => {
      if (!start) return;
      const t = e.changedTouches[0];
      const action = mode === "swipe" ? release(start, { x: t.clientX, y: t.clientY, t: e.timeStamp }, card.offsetWidth) : null;
      start = null;
      if (!action) { move(card, 0, true); return; }
      const id = card.dataset.appId;
      move(card, action === "skip" ? -card.offsetWidth : card.offsetWidth, true);
      const outcome = await ACTIONS[action].send(id);
      if (!outcome.ok) { move(card, 0, true); toast(outcome.message); return; }
      card.remove();
      toast(ACTIONS[action].label, async () => {
        const undone = await post(`/applications/${id}/undo`, { next: "/" });
        if (undone.ok) root.location.reload(); else toast(undone.message);
      });
    });
  }

  function init() { document.querySelectorAll("[data-swipe]").forEach(bind); }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
})(typeof window !== "undefined" ? window : globalThis);
```

- [ ] **Step 4: Load it in `base.html`**

In `src/jobseeker/web/templates/base.html`, directly before `<script src="/static/keys.js" defer></script>`, add:
```html
  <script src="/static/swipe.js" defer></script>
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all passed (including `tests/test_js.py`)

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/web/static/swipe.js tests/js/swipe.test.mjs tests/test_js.py src/jobseeker/web/templates/base.html tests/test_web_mobile.py
git commit -m "feat: swipe-to-skip/snooze logic with Node-tested decision functions and undo toast"
```

---

### Task 4: Inbox on the phone (card list, folded filters) and `keys.js`

**Files:**
- Modify: `src/jobseeker/web/templates/inbox.html`, `src/jobseeker/web/static/keys.js`, `src/jobseeker/web/static/mobile.css`
- Test: `tests/test_web_mobile.py`

**Interfaces:**
- Consumes: `[data-swipe]`, `.card-body`, `data-app-id` (Task 3); `.phone-only-summary` (Task 2).
- Produces: `details[data-phone-closed]`, closed at phone width by `keys.js` (also used in Tasks 5–6); `body.typing` while a field has focus on a phone (used in Task 5).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_mobile.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_mobile.py`
Expected: FAIL (no `filters-box`, no swipe cards; `keys.js` still has `dataset.open`)

- [ ] **Step 3: Replace `src/jobseeker/web/templates/inbox.html`**

```html
{% extends "base.html" %}
{% block content %}
<details class="filters-box" open data-phone-closed>
  <summary class="phone-only-summary">Filters</summary>
  <form class="filters" method="get" action="/">
    <select name="band">{% for b in ["apply", "review", "hide", "all"] %}<option value="{{ b }}" {% if b == f.band %}selected{% endif %}>{{ b }}</option>{% endfor %}</select>
    <select name="family"><option value="">all roles</option>{% for x in families %}<option {% if x == f.family %}selected{% endif %}>{{ x }}</option>{% endfor %}</select>
    <select name="city"><option value="">all cities</option>{% for x in cities %}<option {% if x == f.city %}selected{% endif %}>{{ x }}</option>{% endfor %}</select>
    <select name="source"><option value="">all sources</option>{% for x in sources %}<option {% if x == f.source %}selected{% endif %}>{{ x }}</option>{% endfor %}</select>
    <button>Filter</button>
    <span class="hint">j/k move · enter open · s skip · z snooze</span>
  </form>
</details>
<table class="inbox" data-keys="rows">
  <thead><tr><th>Score</th><th>Role</th><th>Company</th><th>City</th><th>Age</th><th>Source</th><th>Why</th><th></th></tr></thead>
  <tbody>
  {% for r in rows %}
    <tr data-href="/applications/{{ r.app_id }}">
      <td class="score {% if r.score >= 70 %}hi{% elif r.score >= 50 %}mid{% else %}lo{% endif %}">{{ r.score }}</td>
      <td><a href="/applications/{{ r.app_id }}">{{ r.title }}</a> <span class="tag">{{ r.role_family|replace("_", " ") }}</span> <span class="tag muted">{{ r.status }}</span></td>
      <td>{{ r.company }}</td>
      <td>{{ r.location_city or ("remote" if r.remote else (r.location or "?")) }}</td>
      <td>{{ (r.posted_at or r.first_seen_at)|age }}</td>
      <td>{{ r.source }}</td>
      <td class="why">{% for m in (r.matches|fromjson)[:2] %}<span class="m">✓ {{ m }}</span>{% endfor %}{% for g in (r.gaps|fromjson)[:1] %}<span class="g">✗ {{ g }}</span>{% endfor %}</td>
      <td class="acts">
        <form method="post" action="/applications/{{ r.app_id }}/status"><input type="hidden" name="status" value="skipped"><input type="hidden" name="next" value="/"><button data-key="s" title="Skip (s)">Skip</button></form>
        <form method="post" action="/applications/{{ r.app_id }}/snooze"><input type="hidden" name="next" value="/"><button data-key="z" title="Snooze 3 days (z)">Snooze</button></form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="8" class="empty">Nothing here yet. Run <code>jobseeker run</code> or change the filters.</td></tr>
  {% endfor %}
  </tbody>
</table>
{# Phone: the same rows as swipeable cards (a table row can't slide over a fixed coloured panel). #}
<ul class="cards">
  {% for r in rows %}
  <li class="swipe-card" data-app-id="{{ r.app_id }}" data-swipe>
    <div class="swipe-bg" aria-hidden="true"><span class="bg-snooze">Snooze</span><span class="bg-skip">Skip</span></div>
    <div class="card-body">
      <div class="card-top">
        <span class="score {% if r.score >= 70 %}hi{% elif r.score >= 50 %}mid{% else %}lo{% endif %}">{{ r.score }}</span>
        <a class="card-link" href="/applications/{{ r.app_id }}">{{ r.title }}</a>
      </div>
      <p class="card-meta">{{ r.company }} · {{ r.location_city or ("remote" if r.remote else (r.location or "?")) }} · {{ (r.posted_at or r.first_seen_at)|age }} · {{ r.source }}</p>
      <p class="card-tags"><span class="tag">{{ r.role_family|replace("_", " ") }}</span> <span class="tag muted">{{ r.status }}</span>{% for m in (r.matches|fromjson)[:2] %} <span class="m">✓ {{ m }}</span>{% endfor %}{% for g in (r.gaps|fromjson)[:1] %} <span class="g">✗ {{ g }}</span>{% endfor %}</p>
      <div class="card-acts">
        <form method="post" action="/applications/{{ r.app_id }}/status"><input type="hidden" name="status" value="skipped"><input type="hidden" name="next" value="/"><button>Skip</button></form>
        <form method="post" action="/applications/{{ r.app_id }}/snooze"><input type="hidden" name="next" value="/"><button>Snooze</button></form>
      </div>
    </div>
  </li>
  {% else %}
  <li class="empty">Nothing here yet. Run <code>jobseeker run</code> or change the filters.</li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 4: Replace `src/jobseeker/web/static/keys.js`**

```js
(function () {
  const phone = () => window.matchMedia("(max-width: 640px)").matches;
  let i = 0;
  const rows = () => Array.from(document.querySelectorAll("table[data-keys=rows] tbody tr[data-href]"));
  function select(n) {
    const r = rows();
    if (!r.length) return;
    i = Math.max(0, Math.min(n, r.length - 1));
    r.forEach((x, k) => x.classList.toggle("sel", k === i));
    r[i].scrollIntoView({ block: "nearest" });
  }
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey) return;
    const r = rows();
    if (!r.length) return;
    if (e.key === "j") select(i + 1);
    else if (e.key === "k") select(i - 1);
    else if (e.key === "Enter") window.location = r[i].dataset.href;
    else if (e.key === "s" || e.key === "z") {
      const b = r[i].querySelector(`button[data-key="${e.key}"]`);
      if (b) b.click();
    }
  });
  // Copy only: iOS Safari blocks opening a window after an async clipboard write, so "Open LinkedIn" is a plain link.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    e.preventDefault();
    const src = document.querySelector(b.dataset.copy);
    const label = b.dataset.label || b.textContent;
    b.dataset.label = label;
    navigator.clipboard.writeText(src.value || src.textContent).then(() => {
      b.textContent = "Copied ✓";
      setTimeout(() => { b.textContent = label; }, 2000);
    }, () => {
      if (window.JobToast) window.JobToast("Couldn't copy. Select the text and copy it manually.");
    });
  });
  function count(t) {
    const out = document.querySelector(t.dataset.counter);
    if (!out) return;
    const n = t.dataset.unit === "words" ? t.value.trim().split(/\s+/).filter(Boolean).length : t.value.length;
    out.textContent = `${n}/${t.dataset.limit} ${t.dataset.unit}`;
    out.classList.toggle("over", n > Number(t.dataset.limit));
  }
  document.addEventListener("input", (e) => { if (e.target.dataset.limit) count(e.target); });
  // On phones the sticky action bar hides while typing, so it never covers the focused field.
  document.addEventListener("focusin", (e) => {
    if (phone() && e.target.matches("textarea, input:not([type=checkbox]):not([type=hidden])")) {
      document.body.classList.add("typing");
    }
  });
  document.addEventListener("focusout", () => document.body.classList.remove("typing"));
  function foldForPhone() {
    if (!phone()) return;
    document.querySelectorAll('details[data-phone-closed], details.col[data-count="0"]')
      .forEach((d) => d.removeAttribute("open"));
  }
  function init() {
    if (!phone()) select(0);
    foldForPhone();
    document.querySelectorAll("[data-limit]").forEach(count);
  }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
})();
```

- [ ] **Step 5: Append the inbox section to `src/jobseeker/web/static/mobile.css`**

```css
/* ---- Inbox: table on desktop, swipeable cards on phones ---- */
.cards { display: none; list-style: none; margin: 0; padding: 0; }
@media (max-width: 640px) {
  .filters-box { margin-bottom: 10px; }
  .filters-box > summary { padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); font-weight: 600; }
  .filters { flex-direction: column; align-items: stretch; margin: 8px 0 0; }
  table.inbox { display: none; }
  .cards { display: block; }
  .cards .empty { text-align: center; color: var(--muted); padding: 30px 0; }
  .swipe-card { position: relative; margin-bottom: 10px; border-radius: 12px; overflow: hidden; touch-action: pan-y; }
  .swipe-bg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: space-between;
    padding: 0 20px; font-weight: 700; visibility: hidden; }
  .swipe-card[data-dir] .swipe-bg { visibility: visible; }
  .swipe-card[data-dir=skip] .swipe-bg { background: var(--skip-bg); color: var(--skip-fg); }
  .swipe-card[data-dir=snooze] .swipe-bg { background: var(--snooze-bg); color: var(--snooze-fg); }
  .swipe-card[data-dir=skip] .bg-snooze, .swipe-card[data-dir=snooze] .bg-skip { visibility: hidden; }
  .card-body { position: relative; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; }
  .card-top { display: flex; gap: 10px; align-items: flex-start; }
  .card-top .score { flex: 0 0 auto; min-width: 40px; padding: 4px 6px; }
  .card-link { font-weight: 600; color: var(--text); line-height: 1.3; }
  .card-link::after { content: ""; position: absolute; inset: 0; }  /* whole card opens the job */
  .card-meta { margin: 6px 0 4px; color: var(--muted); font-size: 13px; }
  .card-tags { margin: 0 0 8px; font-size: 12px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .card-acts { position: relative; z-index: 1; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .card-acts form, .card-acts button { width: 100%; margin: 0; }
}
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add src/jobseeker/web/templates/inbox.html src/jobseeker/web/static/keys.js src/jobseeker/web/static/mobile.css tests/test_web_mobile.py
git commit -m "feat: phone inbox — swipeable cards, folded filters; keys.js copy/fold/typing"
```

---

### Task 5: Job page on the phone (blocks, sticky Approve bar, More menu, Copy/Open split)

**Files:**
- Modify: `src/jobseeker/web/templates/application.html`, `src/jobseeker/web/application.py` (`matched_skills`), `src/jobseeker/web/static/mobile.css`
- Test: `tests/test_web_mobile.py`

**Interfaces:**
- Consumes: `can_undo` (Task 1); `.phone-only-summary` (Task 2); `data-phone-closed` and `body.typing` (Task 4).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_mobile.py`)

```python
def test_job_page_blocks_and_more_menu(settings, seeded):
    a = seeded[0]
    html = client(settings).get(f"/applications/{a}").text
    for hook in ['class="block head"', 'class="card block drafts"', 'class="card block contact"',
                 '<details class="block jd-box" open data-phone-closed>', 'class="card block history"',
                 'class="card block actions"']:
        assert hook in html, hook
    actions = html.split('class="card block actions"', 1)[1]
    assert actions.index("Approve → Gmail draft") < actions.index('<details class="more" open>')
    more = actions.split('<details class="more" open>', 1)[1].split("</details>", 1)[0]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web_mobile.py`
Expected: FAIL (no block hooks or More menu; the old combined copy button)

- [ ] **Step 3: Pass `matched_skills` from the `detail` route** (`src/jobseeker/web/application.py`)

Replace the last two lines of `detail` with:
```python
    terms = load_facts(settings.facts_path).skills if settings.facts_path.exists() else []
    jd = (d["job"]["jd_text"] or "").lower()
    matched = sum(1 for t in terms if t and t.lower() in jd)
    return render(request, conn, "application.html", terms=terms, matched_skills=matched,
                  can_undo=can_undo(conn, app_id), **d)
```

- [ ] **Step 4: Replace `src/jobseeker/web/templates/application.html`**

```html
{% extends "base.html" %}
{% block title %}{{ job.title }} · {{ job.company }}{% endblock %}
{% block content %}
<div class="detail">
  <section class="col-main">
    <div class="block head">
      <h1>{{ job.title }}</h1>
      <p class="meta">{{ job.company }} · {{ job.location or "location not stated" }}{% if job.remote %} · remote{% endif %} · {{ job.source }} · posted {{ (job.posted_at or job.first_seen_at)|age }}{% if job.salary_text %} · {{ job.salary_text }}{% endif %}</p>
      <p><a href="{{ job.apply_url }}" target="_blank" rel="noopener">Open posting ↗</a> · status <span class="tag">{{ app.status|replace("_", " ") }}</span></p>
      {% if score %}
      <div class="scorebox">
        <span class="big">{{ score.score }}</span>
        <div>
          <ul>{% for k, v in (score.breakdown|fromjson).items() %}<li>{{ k|replace("_", " ") }}: {{ v }}</li>{% endfor %}</ul>
          <p>{% for m in score.matches|fromjson %}<span class="m">✓ {{ m }}</span> {% endfor %}{% for g in score.gaps|fromjson %}<span class="g">✗ {{ g }}</span> {% endfor %}</p>
        </div>
      </div>
      {% endif %}
    </div>
    <details class="block jd-box" open data-phone-closed>
      <summary class="phone-only-summary">Job description · {{ matched_skills }} skills matched</summary>
      <article class="jd">{{ job.jd_text|highlight(terms) }}</article>
    </details>
  </section>

  <section class="col-side">
    <div class="card block contact">
      <h2>Contact</h2>
      {% if app.suggested_contact_role %}
      <p>Suggested: <strong>{{ app.suggested_contact_role }}</strong>. {{ app.suggested_contact_reason }}
        <a href="{{ app.linkedin_search_url }}" target="_blank" rel="noopener">Search LinkedIn ↗</a></p>
      {% endif %}
      <form method="post" action="/applications/{{ app.id }}/contact" class="grid">
        <input name="name" placeholder="Name" autocomplete="off" value="{{ contact.name if contact else '' }}">
        <input name="role" placeholder="Role" value="{{ contact.role if contact else app.suggested_contact_role }}">
        <input name="linkedin_url" type="url" inputmode="url" autocapitalize="off" autocorrect="off" placeholder="LinkedIn URL" value="{{ contact.linkedin_url if contact else '' }}">
        <input name="email" type="email" inputmode="email" autocapitalize="off" autocorrect="off" placeholder="Email" value="{{ contact.email if contact else '' }}">
        <select name="email_status">{% for s in ["unverified", "verified", "bounced"] %}<option {% if contact and contact.email_status == s %}selected{% endif %}>{{ s }}</option>{% endfor %}</select>
        <button>Save contact</button>
      </form>
    </div>

    <div class="card block drafts">
      <h2>Drafts</h2>
      {% if warnings %}<p class="warn">Check before sending: {{ warnings|join("; ") }}</p>{% endif %}
      {% if not drafts %}
        <form method="post" action="/applications/{{ app.id }}/draft"><button>Draft now</button></form>
      {% else %}
        <details open><summary>Email</summary>
          <form method="post" action="/applications/{{ app.id }}/drafts/email">
            <input name="subject" value="{{ drafts.email.subject }}" style="width:100%">
            <textarea name="body" rows="11" data-limit="150" data-unit="words" data-counter="#c_email">{{ drafts.email.body }}</textarea>
            <small id="c_email"></small> <button>Save</button>
            <br><small class="muted">On Approve, "Hi &lt;first name&gt;," is added (unless you wrote your own greeting) and your signature is appended.</small>
          </form>
        </details>
        <details><summary>LinkedIn note</summary>
          <form method="post" action="/applications/{{ app.id }}/drafts/li_note">
            <textarea id="li_note" name="body" rows="4" data-limit="300" data-unit="chars" data-counter="#c_note">{{ drafts.li_note.body }}</textarea>
            <small id="c_note"></small> <button>Save</button>
            <button type="button" data-copy="#li_note">Copy note</button>
            <a class="btn" href="{{ contact.linkedin_url if contact and contact.linkedin_url else app.linkedin_search_url }}" target="_blank" rel="noopener">Open LinkedIn ↗</a>
          </form>
        </details>
        <details><summary>LinkedIn DM</summary>
          <form method="post" action="/applications/{{ app.id }}/drafts/li_dm">
            <textarea id="li_dm" name="body" rows="5" data-limit="600" data-unit="chars" data-counter="#c_dm">{{ drafts.li_dm.body }}</textarea>
            <small id="c_dm"></small> <button>Save</button>
            <button type="button" data-copy="#li_dm">Copy</button>
          </form>
        </details>
      {% endif %}
    </div>

    <div class="card block actions">
      <form method="post" action="/applications/{{ app.id }}/approve" class="approve">
        {% if contact and contact.email and contact.email_status != "verified" %}
        <label><input type="checkbox" name="confirm_unverified" value="true"> Email is unverified, draft anyway</label>
        {% endif %}
        {% if drafts.email and drafts.email.gmail_draft_id %}<p class="warn">A Gmail draft already exists (id {{ drafts.email.gmail_draft_id }}). Approving again creates a new one; delete the old one in Gmail.</p>{% endif %}
        <button class="primary">Approve → Gmail draft</button>
      </form>
      <details class="more" open>
        <summary class="phone-only-summary" aria-label="More actions">More</summary>
        {% if drafts.email and drafts.email.gmail_draft_id %}<a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener">Open Gmail drafts ↗</a>{% endif %}
        {% for s, label in [("sent", "Mark sent"), ("applied_via_portal", "Applied via portal"), ("skipped", "Skip")] %}
        <form method="post" action="/applications/{{ app.id }}/status"><input type="hidden" name="status" value="{{ s }}"><button>{{ label }}</button></form>
        {% endfor %}
        <form method="post" action="/applications/{{ app.id }}/snooze"><button>Snooze 3d</button></form>
        {% if app.status == "sent" %}<form method="post" action="/applications/{{ app.id }}/followed-up"><button>Mark followed up ({{ app.followups_sent }}/2)</button></form>{% endif %}
        {% if drafts and app.status in ["new", "shortlisted", "drafted", "approved"] %}<form method="post" action="/applications/{{ app.id }}/draft"><button>Regenerate all</button></form>{% endif %}
        {% if can_undo %}<form method="post" action="/applications/{{ app.id }}/undo"><button>Undo last change</button></form>{% endif %}
        <form method="post" action="/applications/{{ app.id }}/not-interested">
          <label><input type="checkbox" name="block_company" value="true"> also block company</label>
          <button>Not interested</button>
        </form>
      </details>
    </div>

    <div class="card block notes">
      <h2>Notes</h2>
      <form method="post" action="/applications/{{ app.id }}/notes">
        <textarea name="notes" rows="4" placeholder="Referral source, call notes…">{{ app.notes }}</textarea>
        <button>Save notes</button>
      </form>
    </div>

    <details class="card block history" open data-phone-closed>
      <summary><h2>History</h2></summary>
      <ul class="events">{% for e in events %}<li>{{ e.at[:16]|replace("T", " ") }} · {{ e.type }} {{ e.payload }}</li>{% endfor %}</ul>
    </details>
  </section>
</div>
{% endblock %}
```

- [ ] **Step 5: Append the job-page section to `src/jobseeker/web/static/mobile.css`**

```css
/* ---- Job page ---- */
.history > summary { list-style: none; }
.history > summary::-webkit-details-marker { display: none; }
.history > summary h2 { display: inline; }
.more { display: inline; }
.more > form { display: inline-block; margin: 4px 4px 4px 0; }
@media (max-width: 640px) {
  .detail { display: flex; flex-direction: column; gap: 12px; }
  .col-main, .col-side { display: contents; }
  .detail .card { margin-bottom: 0; }
  .head { order: 1; }
  .drafts { order: 2; }
  .contact { order: 3; }
  .jd-box { order: 4; }
  .notes { order: 5; }
  .history { order: 6; }
  .jd-box > summary { padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); font-weight: 600; }
  .jd { max-height: none; margin-top: 8px; }
  .grid { grid-template-columns: 1fr; }
  .drafts textarea[name=body][data-unit=words] { min-height: 16em; }
  .drafts form button, .drafts form .btn { margin-top: 6px; }
  /* Sticky Approve bar */
  .actions { order: 7; position: sticky; bottom: 0; z-index: 20; margin: 0 -12px calc(-24px - env(safe-area-inset-bottom));
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom)); border-radius: 0; border-width: 1px 0 0;
    box-shadow: 0 -4px 16px rgba(0, 0, 0, .12); }
  .actions .approve { margin: 0; }
  .actions .approve button.primary { width: 100%; font-weight: 600; }
  .actions .approve label { display: block; margin-bottom: 8px; }
  .actions .more { display: block; }
  .actions .more > summary { text-align: center; color: var(--accent); }
  .actions .more[open] { max-height: 50vh; overflow: auto; }
  .actions .more > form { display: block; margin: 6px 0; }
  .actions .more > form button { width: 100%; }
  body.typing .actions { display: none; }  /* never cover the field being typed in */
}
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: all passed (including the existing `tests/test_web_application.py`)

- [ ] **Step 7: Commit**

```bash
git add src/jobseeker/web/templates/application.html src/jobseeker/web/application.py src/jobseeker/web/static/mobile.css tests/test_web_mobile.py
git commit -m "feat: phone job page — reordered blocks, sticky Approve bar, More menu, Copy/Open split"
```

---

### Task 6: Pipeline on the phone (collapsible stacked columns)

**Files:**
- Modify: `src/jobseeker/web/templates/pipeline.html`, `src/jobseeker/web/static/app.css`, `src/jobseeker/web/static/mobile.css`
- Test: `tests/test_web_mobile.py`

**Interfaces:**
- Consumes: `details.col[data-count="0"]` folding (Task 4); `PIPELINE_COLUMNS` (`db/queries.py`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_web_mobile.py`)

```python
def test_pipeline_columns_are_collapsible(settings, seeded):
    from jobseeker.db.queries import PIPELINE_COLUMNS

    html = client(settings).get("/pipeline").text
    assert html.count('<details class="col" open data-count="') == len(PIPELINE_COLUMNS)
    assert '<details class="col" open data-count="1">' in html  # seeded: one drafted application
    assert '<details class="col" open data-count="0">' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_web_mobile.py::test_pipeline_columns_are_collapsible`
Expected: FAIL

- [ ] **Step 3: Update `src/jobseeker/web/templates/pipeline.html`**

Replace the `<section>` … `</section>` wrapper of each column:
```html
  <section>
    <h3>{{ status|replace("_", " ") }} <small class="muted">{{ board[status]|length }}</small></h3>
```
with
```html
  <details class="col" open data-count="{{ board[status]|length }}">
    <summary><h3>{{ status|replace("_", " ") }} <small class="muted">{{ board[status]|length }}</small></h3></summary>
```
and the column's closing `</section>` with `</details>`.

In `src/jobseeker/web/static/app.css`, change the selector `.kanban section {` to `.kanban .col {`, and add after the `.kanban h3` rule:
```css
.kanban .col > summary { list-style: none; cursor: pointer; }
.kanban .col > summary::-webkit-details-marker { display: none; }
```

- [ ] **Step 4: Append the pipeline section to `src/jobseeker/web/static/mobile.css`**

```css
/* ---- Pipeline ---- */
@media (max-width: 640px) {
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .stats .src { grid-column: 1 / -1; margin: 0; }
  .kanban { grid-auto-flow: row; grid-auto-columns: auto; overflow-x: visible; }
  .kanban .col { min-height: 0; }
  .kanban .col > summary { padding: 6px 0; }
  .kanban .col > summary h3 { margin: 0; }
  .kcard form { display: flex; gap: 8px; }
  .kcard select { flex: 1; }
}
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all passed (including the existing `tests/test_web_pipeline.py`)

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/web/templates/pipeline.html src/jobseeker/web/static/app.css src/jobseeker/web/static/mobile.css tests/test_web_mobile.py
git commit -m "feat: phone pipeline — stacked collapsible status columns"
```

---

### Task 7: Visual verification at iPhone 15 size, checklist, docs

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the whole feature.

- [ ] **Step 1: Start a throwaway dashboard on a copy of the data, with no Gmail token, so Approve can't create a real draft**

```bash
T=$(mktemp -d) && mkdir -p "$T/data" "$T/profile" && \
sqlite3 data/jobseeker.db ".backup '$T/data/jobseeker.db'" && \
cp profile/preferences.yaml profile/facts.json profile/resume.pdf "$T/profile/" && cp rubric.yaml companies.yaml "$T/" && \
(JOBSEEKER_HOME="$T" uv run jobseeker serve --port 8770 > "$T/serve.log" 2>&1 &) && sleep 4 && \
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8770/ && echo "$T"
```
Expected: `200`, then the temporary directory path.

- [ ] **Step 2: Phone check with chrome-devtools MCP**

Emulate the iPhone 15: viewport 393×852, DPR 3, mobile, touch, iPhone user agent. Then, for `/`, a drafted `/applications/{id}`, and `/pipeline`:
1. Take a screenshot.
2. Run `document.documentElement.scrollWidth <= window.innerWidth` and expect `true`.
3. On the inbox, check that `.cards` is visible and `table.inbox` is hidden, and that the filters are closed.
4. On the job page:
   - the `.actions` bar's `getBoundingClientRect().bottom` is ≈ `innerHeight` once scrolled;
   - the JD `<details>` is closed;
   - the More menu is closed;
   - every `button` and `select` has a `getBoundingClientRect().height >= 44`.

Expected: all true, and the screenshots look right.

- [ ] **Step 3: Synthetic swipe on the copy**

On `/`, take the first `.swipe-card`'s rect. Dispatch `touchstart` at (`rect.right - 40`, `rect.top + 30`), then `touchmove` events in 20 px steps to `rect.left + 40`, then `touchend` (Chrome emulation supports `new Touch()` and `TouchEvent`). Then check, in order:
1. The card disappears.
2. `#toast` shows "Skipped" and an **Undo** button.
3. Clicking Undo reloads the page with the card back.
4. In the copy database, the application's last event is `undo`.

- [ ] **Step 4: Desktop check**

Set the viewport to 1280×800 with no touch. Then:
1. Take screenshots of the same three pages.
2. Confirm `table.inbox` is visible and `.cards` hidden.
3. Confirm the Filters, Job-description and More summaries aren't shown.
4. Confirm the two-column job page.

- [ ] **Step 5: ui-ux-pro-max pre-delivery checklist**

Using the screenshots and computed styles, confirm each item:
- touch targets ≥ 44 px;
- pressed states don't shift the layout;
- the sticky bar clears the home indicator;
- text contrast ≥ 4.5:1 for the swipe panels and the toast, in light **and** dark (emulate `prefers-color-scheme: dark`);
- reduced motion removes transitions (emulate `prefers-reduced-motion: reduce`);
- swipes have button alternatives;
- no gesture conflicts.

Record the results in the ledger.

- [ ] **Step 6: Stop the throwaway server, then restart the real dashboard**

```bash
pkill -f "jobseeker serve --port 8770"
launchctl kickstart -k gui/$(id -u)/com.kshitij.jobseeker.web && sleep 5 && \
curl -s -o /dev/null -w "%{http_code}\n" https://delulu.tail1c97dd.ts.net/
```
Expected: `200`

- [ ] **Step 7: Update `README.md`**

Under **Daily use**, add:
```markdown
- **On your iPhone:** open the Tailscale address (see Setup step 7) and Add to Home Screen. In the inbox, swipe a card left to **Skip** or right to **Snooze** (Undo appears for 6 seconds). On a job page, **Approve** is pinned to the bottom; everything else is under **More**.
```

Run: `uv run pytest`
Expected: all passed

- [ ] **Step 8: Commit**

```bash
git add README.md
git commit -m "docs: phone usage in README"
```
