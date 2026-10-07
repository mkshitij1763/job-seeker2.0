# UI Redesign (Stitch look on 4 pages) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle Today, Jobs, Job detail and Pipeline in the Stitch "Kinetic Horizon" look, with a match ring, factor bars, a next-step bar and phone tabs, without new backend features.

**Architecture:** The FastAPI + Jinja + HTMX app stays as is. A small `web/view.py` adds template helpers: tier, factor bars, next step, timeline and nav counts. One new token-based stylesheet `static/ui.css` replaces `app.css` and `mobile.css` gradually: during the migration it loads last and overrides them, each page task deletes that page's legacy rules, and the final task deletes the old files. A tiny `static/tabs.js` drives the phone tabs and the pipeline stage chips. Work happens in a git worktree on branch `ui-redesign`, served as a preview on :8001 / Tailscale :8443 against the real data. `main` keeps serving :8000.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, HTMX 2 (`hx-boost`), vanilla CSS/JS, pytest, `node --test` (Node 26), launchd, Tailscale.

**Spec:** `docs/superpowers/specs/2026-10-08-ui-redesign-design.md`

## Global Constraints

- All work on branch `ui-redesign`, inside the worktree `/Users/user/Desktop/untitled folder/job-seeker2.0-ui`. Never commit UI work to `main`. Never restart `com.kshitij.jobseeker.web` from the worktree.
- No new routes, tables or behaviour. Template helpers only, plus loading `rubric.yaml` into `app.state.rubric` and adding a `people` count column to `queries.pipeline`.
- No runtime CDN dependency: no Tailwind, no Material Symbols, no Google Fonts. Fonts are self-hosted woff2 in `static/fonts/`.
- Tokens (verbatim from the spec):
  - background `#FBFBF9`; cards `#FFFFFF`; muted `#F4F4F0`; borders `#E5E7EB` / `#CBD5E1`
  - text `#0F172A` / `#475569` / `#94A3B8`; accent `#3B5BF5`
  - strong ≥90: `#065F46` on `#ECFDF5`, border `#A7F3D0`
  - good 70–89: `#92400E` on `#FFFBEB`, border `#FDE68A`
  - weak <70: `#991B1B` on `#FEF2F2`, border `#FECACA`
  - neutral: `#64748B` on `#F1F5F9`
- Fonts: Geist (UI), JetBrains Mono (scores and counts), `font-variant-numeric: tabular-nums` for all figures.
- Radii: cards 16px, controls 8px, pills 9999px.
- Phone breakpoint: `max-width: 640px`. Tap targets ≥ 44px. Inputs 16px on the phone (prevents iOS zoom). Respect `env(safe-area-inset-bottom)` and `prefers-reduced-motion`.
- Factor maxima come from `rubric.yaml`: role_fit 30, experience_fit 25, skills_match 20, company 15, location_pay 10.
- Next-step steps: ① Find contacts → ② Approve → ③ Send in Gmail → ④ Mark sent.
- Every form keeps its current `action`, field names and `next` values. Swipe, Undo, run notes, toast and `asset()` fingerprinting keep working.
- Test commands: `FORCE_COLOR= uv run pytest --color=no` (do not pass `-q`). Node: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/`.
- When a test that checks old markup is changed, list each changed assertion in that task's commit message.

## Review Focus

1. **A job with no score or a partial `breakdown`** (old rows, unknown keys): the job page renders without the ring, or with only the known bars. It never shows a 500.
2. **Statuses outside the 4-step flow** (`new`, `shortlisted` without drafts, `snoozed`, `skipped`, `not_interested`, `rejected`): the step bar is hidden and the page still works.
3. **No JavaScript, or an HTMX-boosted navigation:** phone tab panels are all visible in the server HTML (JS hides them). After a boosted page swap, tabs and chips work without a full reload.
4. **Very long titles or company names at 393px wide:** no horizontal page scroll on any of the 4 pages; text truncates or wraps.
5. **Dark mode:** tier pills, the ring and the accent remain readable (no white-on-white or dark-on-dark).

---

## File Structure

- Create `src/jobseeker/web/view.py`: pure helpers `tier`, `TIER_LABELS`, `factor_bars`, `next_step`, `STEPS`, `timeline`, `nav_counts`.
- Create `src/jobseeker/web/static/ui.css`: tokens, base, shell, shared components, then one section per page.
- Create `src/jobseeker/web/static/tabs.js`: phone tabs and stage chips; exports the pure `resolveTab` for Node tests.
- Create `src/jobseeker/web/static/fonts/Geist-Variable.woff2` and `src/jobseeker/web/static/fonts/JetBrainsMono-Variable.woff2`.
- Create `src/jobseeker/web/templates/_icons.html`: the `icon(name)` macro with inline SVGs.
- Create `scripts/preview_ui.sh` and `scripts/com.kshitij.jobseeker.uipreview.plist`: the preview server.
- Create `tests/test_web_view.py`, `tests/test_web_redesign.py` and `tests/js/tabs.test.mjs`.
- Modify `web/app.py` (rubric in state; Jinja globals), `web/deps.py` (`nav` in render context), `web/application.py` (detail context), `db/queries.py` (`people` in pipeline).
- Modify templates `base.html`, `today.html`, `inbox.html`, `application.html`, `_people.html`, `pipeline.html`.
- Delete at the end: `static/app.css` and `static/mobile.css`.

---

### Task 1: Worktree and preview server

**Files:**
- Create: `scripts/preview_ui.sh`
- Create: `scripts/com.kshitij.jobseeker.uipreview.plist`

**Interfaces:**
- Produces: the worktree at `/Users/user/Desktop/untitled folder/job-seeker2.0-ui` (branch `ui-redesign`), the launchd label `com.kshitij.jobseeker.uipreview` on 127.0.0.1:8001, and `https://delulu.tail1c97dd.ts.net:8443`. Restart with `launchctl kickstart -k gui/$(id -u)/com.kshitij.jobseeker.uipreview`.

- [ ] **Step 1: Put the main folder back on `main` and create the worktree**

```bash
cd "/Users/user/Desktop/untitled folder/job-seeker2.0"
git status --short            # expect nothing to commit except untracked files
git switch main
git worktree add "../job-seeker2.0-ui" ui-redesign
cd "../job-seeker2.0-ui" && uv sync && git branch --show-current   # expect: ui-redesign
```

- [ ] **Step 2: Write the plist template** `scripts/com.kshitij.jobseeker.uipreview.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.kshitij.jobseeker.uipreview</string>
  <key>ProgramArguments</key>
  <array>
    <string>__UV__</string><string>run</string><string>--project</string><string>__WORKTREE__</string>
    <string>jobseeker</string><string>serve</string><string>--port</string><string>8001</string>
  </array>
  <!-- Runs the branch's code against the real data, .env and secrets in the main folder. -->
  <key>WorkingDirectory</key><string>__MAIN__</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>__MAIN__/data/logs/uipreview.log</string>
  <key>StandardErrorPath</key><string>__MAIN__/data/logs/uipreview.err.log</string>
</dict>
</plist>
```

- [ ] **Step 3: Write `scripts/preview_ui.sh`**

```bash
#!/usr/bin/env bash
# Preview the ui-redesign branch on :8001 (Tailscale :8443) against the real data.
# Usage: scripts/preview_ui.sh install | remove
set -euo pipefail
WORKTREE="$(cd "$(dirname "$0")/.." && pwd)"
MAIN="$(cd "$WORKTREE/../job-seeker2.0" && pwd)"
UV="$(command -v uv)"
LABEL=com.kshitij.jobseeker.uipreview
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale

case "${1:-}" in
  install)
    sed -e "s|__UV__|$UV|g" -e "s|__WORKTREE__|$WORKTREE|g" -e "s|__MAIN__|$MAIN|g" \
      "$WORKTREE/scripts/$LABEL.plist" > "$DEST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$DEST"
    "$TS" serve --bg --https=8443 http://127.0.0.1:8001
    echo "Preview: https://delulu.tail1c97dd.ts.net:8443" ;;
  remove)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$DEST"
    "$TS" serve --https=8443 off || true
    echo "Preview stopped. Remove the worktree with: git -C \"$MAIN\" worktree remove \"$WORKTREE\"" ;;
  *) echo "usage: $0 install|remove" >&2; exit 2 ;;
esac
```

- [ ] **Step 4: Install and verify**

```bash
cd "/Users/user/Desktop/untitled folder/job-seeker2.0-ui"
chmod +x scripts/preview_ui.sh && scripts/preview_ui.sh install
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/today        # expect 200
curl -s -o /dev/null -w "%{http_code}\n" https://delulu.tail1c97dd.ts.net:8443/today   # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/today        # expect 200 (live, untouched)
git -C "../job-seeker2.0" branch --show-current                            # expect main
```

- [ ] **Step 5: Commit**

```bash
git add scripts/preview_ui.sh scripts/com.kshitij.jobseeker.uipreview.plist
git commit -m "chore: preview server for the ui-redesign branch on :8001 / Tailscale :8443"
git push
```

---

### Task 2: View helpers

**Files:**
- Create: `src/jobseeker/web/view.py`
- Modify: `src/jobseeker/web/app.py` (load the rubric; register globals)
- Modify: `src/jobseeker/web/deps.py` (`nav` in the render context)
- Test: `tests/test_web_view.py`

**Interfaces:**
- Produces:
  - `tier(score: int | None) -> str`: one of `"strong"` (≥90), `"good"` (70–89), `"weak"` (<70), `"none"`.
  - `TIER_LABELS: dict[str, str]`.
  - `factor_bars(breakdown: str | dict | None, rubric: Rubric) -> list[dict]`: each item has keys `key, label, value, max, pct`, in rubric order; unknown or missing keys are skipped; values are clamped to `0..max`.
  - `STEPS: list[str]` (4 labels); `next_step(status: str, has_people: bool) -> int | None`: 1 or 2 for drafted, 3 for approved, 5 (all done) for sent/replied/interview/offer, `None` otherwise.
  - `timeline(events: list[dict]) -> list[dict]` with keys `day, text`.
  - `nav_counts(conn) -> dict` with keys `jobs, pipeline, today`.
  - Jinja globals `tier`, `TIER_LABELS`, `STEPS`.
  - `app.state.rubric`.
  - `render()` adds `nav`.

- [ ] **Step 1: Write the failing tests** `tests/test_web_view.py`

```python
import json

from jobseeker.config import load_rubric
from jobseeker.db.core import connect
from jobseeker.web.view import STEPS, factor_bars, nav_counts, next_step, tier, timeline


def test_tier_thresholds():
    assert [tier(s) for s in (95, 90, 89, 70, 69, 0, None)] == [
        "strong", "strong", "good", "good", "weak", "weak", "none"]


def test_factor_bars_follow_rubric_order_clamp_and_skip_unknown(settings):
    rubric = load_rubric(settings.rubric_path)
    bars = factor_bars(json.dumps({"skills_match": 25, "role_fit": 15, "mystery": 3}), rubric)
    assert [b["key"] for b in bars] == ["role_fit", "skills_match"]
    assert bars[0] == {"key": "role_fit", "label": "Role fit", "value": 15, "max": 30, "pct": 50}
    assert bars[1]["value"] == 20 and bars[1]["pct"] == 100  # clamped to the rubric max
    assert factor_bars(None, rubric) == [] and factor_bars("not json", rubric) == []


def test_next_step_covers_every_status():
    assert len(STEPS) == 4
    assert next_step("drafted", False) == 1 and next_step("drafted", True) == 2
    assert next_step("approved", True) == 3
    assert all(next_step(s, True) == 5 for s in ("sent", "replied", "interview", "offer"))
    for s in ("new", "shortlisted", "snoozed", "skipped", "not_interested", "rejected", "applied_via_portal"):
        assert next_step(s, True) is None, s


def test_timeline_reads_like_sentences():
    events = [
        {"at": "2026-10-03T09:00:00+00:00", "type": "status", "payload": json.dumps({"from": "approved", "to": "sent"})},
        {"at": "2026-10-04T09:00:00+00:00", "type": "status",
         "payload": json.dumps({"from": "shortlisted", "to": "skipped", "reason": "experience 6+ years"})},
        {"at": "2026-10-05T09:00:00+00:00", "type": "undo", "payload": json.dumps({"from": "skipped", "to": "shortlisted"})},
        {"at": "2026-10-08T09:00:00+00:00", "type": "followup", "payload": json.dumps({"n": 1})},
        {"at": "2026-10-08T10:00:00+00:00", "type": "contact", "payload": "{}"},
        {"at": "2026-10-08T11:00:00+00:00", "type": "mystery_thing", "payload": "{}"},
    ]
    assert [(t["day"], t["text"]) for t in timeline(events)] == [
        ("3 Oct", "Marked sent"),
        ("4 Oct", "Marked skipped (experience 6+ years)"),
        ("5 Oct", "Undid skipped, back to shortlisted"),
        ("8 Oct", "Follow-up 1 recorded"),
        ("8 Oct", "Contact saved"),
        ("8 Oct", "Mystery thing"),
    ]


def test_nav_counts(settings, seeded):
    conn = connect(settings.db_path)
    counts = nav_counts(conn)
    assert set(counts) == {"jobs", "pipeline", "today"}
    assert counts["jobs"] == 1  # seeded: one "apply" job in an inbox status


def test_render_context_has_nav(settings, seeded):
    from fastapi.testclient import TestClient

    from jobseeker.web.app import create_app

    app = create_app(settings)
    assert app.state.rubric.dimensions[0].key == "role_fit"
    assert TestClient(app).get("/today").status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_web_view.py`
Expected: collection error `ModuleNotFoundError: No module named 'jobseeker.web.view'`.

- [ ] **Step 3: Implement** `src/jobseeker/web/view.py`

```python
"""Presentation helpers for the templates: no I/O except nav_counts' read-only queries."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from jobseeker.config import Rubric

TIER_LABELS = {"strong": "Strong match", "good": "Good match", "weak": "Weak match", "none": "Not scored"}
FACTOR_LABELS = {"role_fit": "Role fit", "experience_fit": "Experience", "skills_match": "Skills",
                 "company": "Company", "location_pay": "Location & pay"}
STEPS = ["Find contacts", "Approve", "Send in Gmail", "Mark sent"]
_DONE = {"sent", "replied", "interview", "offer"}


def tier(score: int | None) -> str:
    if score is None:
        return "none"
    return "strong" if score >= 90 else "good" if score >= 70 else "weak"


def factor_bars(breakdown: str | dict | None, rubric: Rubric) -> list[dict]:
    """One bar per rubric dimension present in the score, in rubric order, clamped to that dimension's max."""
    if isinstance(breakdown, str):
        try:
            breakdown = json.loads(breakdown)
        except ValueError:
            return []
    values = breakdown if isinstance(breakdown, dict) else {}
    bars = []
    for d in rubric.dimensions:
        if values.get(d.key) is None or d.max <= 0:
            continue
        v = max(0, min(int(values[d.key]), d.max))
        bars.append({"key": d.key, "label": FACTOR_LABELS.get(d.key, d.key.replace("_", " ").capitalize()),
                     "value": v, "max": d.max, "pct": round(100 * v / d.max)})
    return bars


def next_step(status: str, has_people: bool) -> int | None:
    """1-4 is the current step of Find contacts -> Approve -> Send in Gmail -> Mark sent; 5 = all done;
    None = this status isn't on that path (new, skipped, snoozed, ...)."""
    if status == "drafted":
        return 2 if has_people else 1
    if status == "approved":
        return 3
    return 5 if status in _DONE else None


def _day(at: str) -> str:
    dt = datetime.fromisoformat(at)
    return f"{dt.day} {dt:%b}"


def timeline(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        try:
            p = json.loads(e.get("payload") or "{}")
        except ValueError:
            p = {}
        kind = e["type"]
        if kind == "status":
            text = f"Marked {str(p.get('to', '?')).replace('_', ' ')}"
            if p.get("reason"):
                text += f" ({p['reason']})"
        elif kind == "undo":
            text = f"Undid {str(p.get('from', '')).replace('_', ' ')}, back to {str(p.get('to', '')).replace('_', ' ')}"
        elif kind == "followup":
            text = f"Follow-up {p.get('n', '')} recorded".replace("  ", " ")
        elif kind == "contact":
            text = "Contact saved"
        else:
            text = kind.replace("_", " ").capitalize()
        out.append({"day": _day(e["at"]), "text": text})
    return out


def nav_counts(conn: sqlite3.Connection) -> dict:
    """Badges for the sidebar/tab bar: Jobs = default inbox rows, Pipeline = active applications."""
    from jobseeker.db.queries import inbox

    pipeline = conn.execute("""SELECT COUNT(*) FROM applications
                               WHERE status IN ('approved', 'sent', 'replied', 'interview')""").fetchone()[0]
    ready = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'approved'").fetchone()[0]
    return {"jobs": len(inbox(conn)), "pipeline": pipeline, "today": ready}
```

- [ ] **Step 4: Wire it in.**

In `src/jobseeker/web/app.py`:
- change the config import to `from jobseeker.config import Settings, load_preferences, load_rubric`
- add `from jobseeker.web.view import STEPS, TIER_LABELS, tier`
- right after `app.state.prefs = load_preferences(settings.preferences_path)`, add:

```python
    app.state.rubric = load_rubric(settings.rubric_path)
```

and after `templates.env.globals["asset"] = asset` add:

```python
    templates.env.globals.update(tier=tier, TIER_LABELS=TIER_LABELS, STEPS=STEPS)
```

In `src/jobseeker/web/deps.py`, add `from jobseeker.web.view import nav_counts` and, in `render()` before the `return`:

```python
    ctx["nav"] = nav_counts(conn)
```

- [ ] **Step 5: Run the tests**

Run: `FORCE_COLOR= uv run pytest --color=no`
Expected: all pass (377 = 371 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/web/view.py src/jobseeker/web/app.py src/jobseeker/web/deps.py tests/test_web_view.py
git commit -m "feat(ui): view helpers for tiers, factor bars, next step, timeline and nav counts"
```

---

### Task 3: Design tokens, fonts and the app shell

**Files:**
- Create: `src/jobseeker/web/static/fonts/Geist-Variable.woff2`
- Create: `src/jobseeker/web/static/fonts/JetBrainsMono-Variable.woff2`
- Create: `src/jobseeker/web/static/ui.css`
- Create: `src/jobseeker/web/templates/_icons.html`
- Modify: `src/jobseeker/web/templates/base.html`
- Test: `tests/test_web_redesign.py`

**Interfaces:**
- Consumes: `nav` in the context (Task 2).
- Produces:
  - CSS classes: `.pill.tier-strong|good|weak|none`, `.btn`, `.btn-primary`, `.btn-ghost`, `.chip`, `.chip.is-active`, `.card`, `.section-title`, `.stat`, `.muted`, `.mono`, `.empty`.
  - Shell: `.shell`, `.sidebar`, `.topbar`, `.tabbar`, `.main`.
  - The `icon(name)` macro, for names `today, jobs, pipeline, more, check, warn, external, back, gmail, people, draft, job`.

- [ ] **Step 1: Download the fonts**

```bash
mkdir -p src/jobseeker/web/static/fonts
curl -sfL -o src/jobseeker/web/static/fonts/Geist-Variable.woff2 \
  https://cdn.jsdelivr.net/npm/geist@1/dist/fonts/geist-sans/Geist-Variable.woff2
curl -sfL -o src/jobseeker/web/static/fonts/JetBrainsMono-Variable.woff2 \
  https://cdn.jsdelivr.net/npm/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2
file src/jobseeker/web/static/fonts/*.woff2   # expect "Web Open Font Format (Version 2)" for both
```

Both fonts are SIL Open Font License 1.1, so bundling them is allowed.

- [ ] **Step 2: Write the failing tests** `tests/test_web_redesign.py`

```python
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_web_redesign.py`
Expected: 4 failed (no sidebar, no `ui.css`, no fonts).

- [ ] **Step 4: Write `src/jobseeker/web/templates/_icons.html`** (24px monoline SVGs using `currentColor`)

```jinja
{% macro icon(name, size=20) -%}
<svg class="icon" width="{{ size }}" height="{{ size }}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
{%- if name == "today" -%}<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M3 9h18M8 2v4M16 2v4"/>
{%- elif name == "jobs" -%}<rect x="3" y="7" width="18" height="13" rx="3"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>
{%- elif name == "pipeline" -%}<rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="10" y="4" width="5" height="11" rx="1.5"/><rect x="17" y="4" width="4" height="7" rx="1.5"/>
{%- elif name == "more" -%}<circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/>
{%- elif name == "check" -%}<path d="M5 12.5l4.5 4.5L19 7.5"/>
{%- elif name == "warn" -%}<path d="M12 3l9.5 17h-19L12 3z"/><path d="M12 10v4M12 17.5v.01"/>
{%- elif name == "external" -%}<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>
{%- elif name == "back" -%}<path d="M15 5l-7 7 7 7"/>
{%- elif name == "gmail" -%}<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7l8.5 6 8.5-6"/>
{%- elif name == "people" -%}<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>
{%- elif name == "draft" -%}<path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>
{%- elif name == "job" -%}<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>
{%- endif -%}
</svg>
{%- endmacro %}
```

- [ ] **Step 5: Write `src/jobseeker/web/static/ui.css`** (tokens, base, shell, shared components; page sections are added by later tasks)

```css
/* Kinetic Horizon (Stitch) tokens: docs/superpowers/specs/2026-10-08-ui-redesign-design.md */
@font-face { font-family: "Geist"; src: url("fonts/Geist-Variable.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }
@font-face { font-family: "JetBrains Mono"; src: url("fonts/JetBrainsMono-Variable.woff2") format("woff2"); font-weight: 100 800; font-display: swap; }

:root {
  --bg: #FBFBF9; --surface: #FFFFFF; --muted-bg: #F4F4F0; --line: #E5E7EB; --line-strong: #CBD5E1;
  --text: #0F172A; --text-2: #475569; --text-3: #94A3B8;
  --accent: #3B5BF5; --accent-press: #2F4BE0; --accent-wash: rgba(59, 91, 245, 0.06);
  --strong-fg: #065F46; --strong-bg: #ECFDF5; --strong-line: #A7F3D0; --strong-dot: #10B981;
  --good-fg: #92400E; --good-bg: #FFFBEB; --good-line: #FDE68A; --good-dot: #F59E0B;
  --weak-fg: #991B1B; --weak-bg: #FEF2F2; --weak-line: #FECACA; --weak-dot: #EF4444;
  --neutral-fg: #64748B; --neutral-bg: #F1F5F9; --neutral-line: #E2E8F0;
  --radius-card: 16px; --radius-ctl: 8px;
  --shadow-1: 0 1px 2px rgba(15, 23, 42, .04);
  --shadow-2: 0 4px 12px -2px rgba(15, 23, 42, .06), 0 2px 4px -1px rgba(15, 23, 42, .03);
  --shadow-3: 0 12px 32px -4px rgba(15, 23, 42, .10), 0 4px 8px -2px rgba(15, 23, 42, .04);
  --font: "Geist", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  /* aliases so legacy app.css / mobile.css rules pick up the new palette until they are removed */
  --panel: var(--surface); --muted: var(--text-2); --ok: var(--strong-dot); --warn: var(--good-dot); --err: var(--weak-dot);
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0B1120; --surface: #111827; --muted-bg: #1A2232; --line: #253045; --line-strong: #334155;
    --text: #E5E9F0; --text-2: #A3AEC2; --text-3: #6B778C;
    --accent: #6F87FF; --accent-press: #5A74F5; --accent-wash: rgba(111, 135, 255, 0.10);
    --strong-fg: #6EE7B7; --strong-bg: rgba(16, 185, 129, .12); --strong-line: rgba(16, 185, 129, .35);
    --good-fg: #FCD34D; --good-bg: rgba(245, 158, 11, .12); --good-line: rgba(245, 158, 11, .35);
    --weak-fg: #FCA5A5; --weak-bg: rgba(239, 68, 68, .12); --weak-line: rgba(239, 68, 68, .35);
    --neutral-fg: #A3AEC2; --neutral-bg: #1A2232; --neutral-line: #253045;
    --shadow-1: none; --shadow-2: 0 4px 12px rgba(0, 0, 0, .35); --shadow-3: 0 12px 32px rgba(0, 0, 0, .5);
    color-scheme: dark;
  }
}

/* ---- base ---- */
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--text); font: 400 15px/1.6 var(--font); letter-spacing: -0.005em; }
a { color: var(--accent); text-decoration: none; }
h1 { font-size: 28px; line-height: 36px; font-weight: 600; letter-spacing: -0.025em; margin: 0 0 4px; }
h2 { font-size: 18px; line-height: 26px; font-weight: 600; letter-spacing: -0.015em; margin: 0 0 8px; }
h3 { font-size: 15px; line-height: 22px; font-weight: 500; margin: 0; }
.muted { color: var(--text-2); } .faint { color: var(--text-3); }
.mono, .score, .count, .stat b { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.label { font-size: 12px; font-weight: 500; letter-spacing: .02em; text-transform: uppercase; color: var(--text-2); }
.icon { flex: 0 0 auto; vertical-align: middle; }

/* ---- controls ---- */
button, .btn { font: 500 14px/1 var(--font); display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  min-height: 44px; padding: 0 14px; border-radius: var(--radius-ctl); border: 1px solid var(--line); background: var(--surface);
  color: var(--text); cursor: pointer; text-decoration: none; transition: background .15s, border-color .15s, transform .05s; }
button:hover, .btn:hover { border-color: var(--line-strong); background: var(--muted-bg); }
button:active, .btn:active { transform: scale(.98); }
button.primary, .btn-primary { background: var(--accent); border-color: transparent; color: #fff; }
button.primary:hover, .btn-primary:hover { background: var(--accent-press); }
.btn-ghost { background: transparent; border-color: transparent; color: var(--text-2); }
button:focus-visible, .btn:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px; }
input, select, textarea { font: 400 15px/1.5 var(--font); color: var(--text); background: var(--muted-bg); border: 1px solid var(--line);
  border-radius: var(--radius-ctl); padding: 9px 12px; min-height: 44px; max-width: 100%; }
input:focus, select:focus, textarea:focus { background: var(--surface); border-color: var(--accent); outline: none; }
textarea { width: 100%; }
form { margin: 0; }

/* ---- shared components ---- */
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-card); box-shadow: var(--shadow-1); padding: 16px 18px; min-width: 0; }
.pill { display: inline-flex; align-items: center; gap: 4px; border-radius: 9999px; padding: 2px 9px; font: 500 12px/18px var(--mono);
  border: 1px solid var(--neutral-line); background: var(--neutral-bg); color: var(--neutral-fg); white-space: nowrap; }
.tier-strong { color: var(--strong-fg); background: var(--strong-bg); border-color: var(--strong-line); }
.tier-good { color: var(--good-fg); background: var(--good-bg); border-color: var(--good-line); }
.tier-weak { color: var(--weak-fg); background: var(--weak-bg); border-color: var(--weak-line); }
.chip { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 0 12px; border-radius: 9999px; border: 1px solid var(--line);
  background: var(--surface); color: var(--text-2); font: 500 13px/1 var(--font); white-space: nowrap; cursor: pointer; }
.chip .count { font-size: 11px; color: var(--text-3); }
.chip.is-active { background: var(--text); border-color: var(--text); color: var(--bg); }
.chip.is-active .count { color: inherit; opacity: .7; }
.chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.ok { color: var(--strong-fg); } .warnc { color: var(--good-fg); } .bad { color: var(--weak-fg); }
.empty { text-align: center; color: var(--text-2); padding: 32px 16px; }
.section-title { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; }

/* ---- shell ---- */
.shell { display: grid; grid-template-columns: 240px minmax(0, 1fr); min-height: 100vh; }
.sidebar { position: sticky; top: 0; height: 100vh; border-right: 1px solid var(--line); background: var(--surface);
  padding: 18px 12px; display: flex; flex-direction: column; gap: 4px; }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 16px; color: var(--text); padding: 4px 10px 18px; }
.brand-mark { width: 26px; height: 26px; border-radius: 7px; background: var(--accent); color: #fff; display: grid; place-items: center; font: 600 13px var(--mono); }
.nav-item { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 0 10px; border-radius: var(--radius-ctl); color: var(--text-2); font-weight: 500; }
.nav-item:hover { background: var(--muted-bg); color: var(--text); }
.nav-item.is-active { background: var(--accent-wash); color: var(--accent); }
.nav-item .count { margin-left: auto; font-size: 11px; padding: 1px 7px; border-radius: 9999px; background: var(--muted-bg); color: var(--text-2); }
.sidebar-foot { margin-top: auto; }
.topbar { display: none; }
.tabbar { display: none; }
.main { min-width: 0; padding: 28px 32px 48px; max-width: 1200px; width: 100%; }
.flash { margin: 0 0 16px; padding: 10px 14px; border-radius: var(--radius-ctl); border: 1px solid var(--line); background: var(--surface); }
.flash.ok { border-color: var(--strong-line); background: var(--strong-bg); color: var(--strong-fg); }
.flash.err { border-color: var(--weak-line); background: var(--weak-bg); color: var(--weak-fg); }

/* run notes (header pill + panel) */
.run-notes { position: relative; }
.run-notes > summary { cursor: pointer; list-style: none; font-size: 13px; color: var(--good-fg); }
.run-notes > summary::-webkit-details-marker { display: none; }
.run-notes > summary.err { color: var(--weak-fg); }
.run-notes-panel { position: absolute; left: 0; bottom: calc(100% + 8px); z-index: 40; width: 320px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow-3); padding: 12px 14px; }
.run-notes-panel p { margin: 0 0 8px; font-size: 13px; color: var(--text-2); }
.run-notes-panel ul { margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.45; }
.run-notes-panel li + li { margin-top: 6px; }
.run-notes-panel li.err { color: var(--weak-fg); }

/* toast (swipe Undo) */
.toast { position: fixed; left: 50%; bottom: calc(84px + env(safe-area-inset-bottom)); transform: translateX(-50%); z-index: 50;
  display: flex; gap: 12px; align-items: center; background: var(--text); color: var(--bg); border-radius: 12px; padding: 10px 14px; box-shadow: var(--shadow-3); }
.toast[hidden] { display: none; }
.toast button { min-height: 32px; background: transparent; color: inherit; border-color: transparent; text-decoration: underline; }

/* ---- phone ---- */
@media (max-width: 640px) {
  .shell { display: block; }
  .sidebar { display: none; }
  .topbar { display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 30;
    padding: calc(8px + env(safe-area-inset-top)) 16px 8px; background: var(--surface); border-bottom: 1px solid var(--line); }
  .topbar .brand { padding: 0; }
  .topbar .run-notes-panel { position: fixed; left: 16px; right: 16px; width: auto; top: calc(56px + env(safe-area-inset-top)); bottom: auto; }
  .main { padding: 16px 16px calc(88px + env(safe-area-inset-bottom)); }
  .tabbar { display: grid; grid-template-columns: repeat(3, 1fr); position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
    background: var(--surface); border-top: 1px solid var(--line); padding: 6px 8px calc(6px + env(safe-area-inset-bottom)); }
  .tabbar .nav-item { flex-direction: column; justify-content: center; gap: 2px; min-height: 52px; font-size: 11px; padding: 0; }
  .tabbar .nav-item .count { position: absolute; margin: -30px 0 0 26px; }
  .tabbar .nav-item { position: relative; }
  input, select, textarea { font-size: 16px; }
  h1 { font-size: 24px; line-height: 32px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }

/* ---- pages (sections added per task) ---- */
```

- [ ] **Step 6: Rewrite `src/jobseeker/web/templates/base.html`**

The old `app.css` / `mobile.css` stay linked **before** `ui.css` until Task 8 deletes them.

```jinja
{% from "_icons.html" import icon %}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#FBFBF9" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0B1120" media="(prefers-color-scheme: dark)">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Job Seeker">
  <title>{% block title %}Job Seeker{% endblock %}</title>
  <link rel="manifest" href="/static/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/icon-180.png">
  <link rel="preload" href="/static/fonts/Geist-Variable.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="{{ asset('app.css') }}">
  <link rel="stylesheet" href="{{ asset('mobile.css') }}">
  <link rel="stylesheet" href="{{ asset('ui.css') }}">
  <script src="{{ asset('htmx.min.js') }}" defer></script>
  <script src="{{ asset('swipe.js') }}" defer></script>
  <script src="{{ asset('keys.js') }}" defer></script>
</head>
<body hx-boost="true">
{% set path = request.url.path %}
{% set items = [("today", "/today", "Today", nav.today if nav else 0), ("jobs", "/", "Jobs", nav.jobs if nav else 0),
                ("pipeline", "/pipeline", "Pipeline", nav.pipeline if nav else 0)] %}
{% macro nav_links() -%}
  {% for key, href, label, count in items %}
  {% set active = (path == href) or (key == "jobs" and path.startswith("/applications/")) %}
  <a class="nav-item{{ ' is-active' if active }}" href="{{ href }}">{{ icon(key) }}<span>{{ label }}</span>{% if count %}<span class="count mono">{{ count }}</span>{% endif %}</a>
  {% endfor %}
{%- endmacro %}
{% macro run_notes_box() -%}
  {% if run_notes %}
  {% set needs_you = run_notes|selectattr("action")|list %}
  <details class="run-notes">
    <summary class="{{ 'err' if needs_you else 'warn' }}">{% if needs_you %}Last run needs you{% else %}{{ run_notes|length }} note{{ "s" if run_notes|length != 1 }}{% endif %}</summary>
    <div class="run-notes-panel">
      {% set ago = run_finished|age %}<p class="muted">Daily run finished {{ ago if ago in ("today", "?") else ago ~ " ago" }}{% if not needs_you %}. Nothing to do: these fix themselves{% endif %}.</p>
      <ul>{% for n in run_notes %}<li{% if n.action %} class="err"{% endif %}>{{ n.text }}</li>{% endfor %}</ul>
    </div>
  </details>
  {% endif %}
{%- endmacro %}
<div class="shell">
  <nav class="sidebar" aria-label="Main">
    <a class="brand" href="/today"><span class="brand-mark">J</span>Job Seeker</a>
    {{ nav_links() }}
    <div class="sidebar-foot">{{ run_notes_box() }}</div>
  </nav>
  <div>
    <header class="topbar"><a class="brand" href="/today"><span class="brand-mark">J</span>Job Seeker</a>{{ run_notes_box() }}</header>
    <main class="main">
      {% if msg %}<div class="flash ok">{{ msg }}</div>{% endif %}
      {% if err %}<div class="flash err">{{ err }}</div>{% endif %}
      {% block content %}{% endblock %}
    </main>
  </div>
</div>
<nav class="tabbar" aria-label="Main">{{ nav_links() }}</nav>
<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>
</body>
</html>
```

- [ ] **Step 7: Update the old header tests that this changes**

In `tests/test_run_notes.py::test_header_shows_tappable_run_notes`, keep `'<details class="run-notes"'` and `"Daily AI limit reached"` (both still present). In `tests/test_web_today.py::test_today_page_nav_and_mark_sent`, `'href="/today"' in html` still passes. In `tests/test_web_mobile.py::test_base_has_phone_meta_and_toast`, the `<meta name="theme-color"` substring and the toast div are unchanged. Run the suite and fix only assertions that check removed header markup (for example `class="top"` or `class="long"`).

- [ ] **Step 8: Run all tests**

Run: `FORCE_COLOR= uv run pytest --color=no`
Expected: all pass, including the 4 new ones.

- [ ] **Step 9: Browser check of the shell**

```bash
launchctl kickstart -k gui/$(id -u)/com.kshitij.jobseeker.uipreview && sleep 8
```

Open `http://127.0.0.1:8001/today` with chrome-devtools:
- **iPhone (393×852, mobile, touch):** the bottom tab bar is visible, `document.documentElement.scrollWidth === 393`, and the run notes open over the content.
- **Mac (1440×900):** the 240px sidebar is visible, and the active item is accent-coloured.
- **Dark mode** (`emulate colorScheme: dark`): text is readable and the pills are visible.

- [ ] **Step 10: Commit**

```bash
git add src/jobseeker/web/static/fonts src/jobseeker/web/static/ui.css src/jobseeker/web/templates/_icons.html \
  src/jobseeker/web/templates/base.html tests/
git commit -m "feat(ui): Kinetic Horizon tokens, self-hosted fonts, sidebar + bottom tab bar shell"
```

---

### Task 4: Today page

**Files:**
- Modify: `src/jobseeker/web/templates/today.html`
- Modify: `src/jobseeker/web/static/ui.css` (append the Today section)
- Modify: `src/jobseeker/web/static/app.css` (delete the `/* ---- Today ---- */` block)
- Test: `tests/test_web_redesign.py`

**Interfaces:**
- Consumes: `t` from `queries.today` (`send`, `followups`, `ready`, `find_contacts`, `new_since_yesterday`), `tier`, the `icon` macro, and the `prefs` name via `request.app.state.prefs.name`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_web_redesign.py`)

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_web_redesign.py -k today_dashboard`
Expected: FAIL (no greeting).

- [ ] **Step 3: Rewrite `src/jobseeker/web/templates/today.html`**

```jinja
{% extends "base.html" %}
{% from "_icons.html" import icon %}
{% block title %}Today · Job Seeker{% endblock %}
{% block content %}
{% set hour = now_hour if now_hour is defined else 9 %}
{% set first = request.app.state.prefs.name.split()[0] %}
{% macro job(r) %}<a class="today-job" href="/applications/{{ r.app_id }}"><span class="pill tier-{{ tier(r.score) }}">{{ r.score }}</span><span class="today-job-text"><b>{{ r.title }}</b><small class="muted">{{ r.company }}</small></span></a>{% endmacro %}
<header class="page-head">
  <h1>Good {{ "morning" if hour < 12 else ("afternoon" if hour < 17 else "evening") }}, {{ first }}.</h1>
  <p class="muted">Here's what needs you today.</p>
</header>
<div class="stats">
  {% for label, n, anchor in [("New today", t.new_since_yesterday, "/"), ("Ready to approve", t.ready|length, "#ready"),
                              ("Need contacts", t.find_contacts|length, "#find"), ("Send in Gmail", t.send|length, "#send")] %}
  <a class="stat card" href="{{ anchor }}"><b>{{ n }}</b><span class="stat-label">{{ label }}</span></a>
  {% endfor %}
</div>
<div class="today">
  {% if t.send %}
  <section class="card" id="send">
    <h2 class="section-title">{{ icon("gmail") }} Send in Gmail <span class="pill">{{ t.send|length }}</span></h2>
    <p class="muted">Drafts are waiting in Gmail. Send them, then mark sent here.</p>
    {% for r in t.send %}
    <div class="today-row">{{ job(r) }}
      <form method="post" action="/applications/{{ r.app_id }}/status"><input type="hidden" name="status" value="sent"><input type="hidden" name="next" value="/today"><button>Mark sent</button></form>
    </div>
    {% endfor %}
  </section>
  {% endif %}
  {% if t.followups %}
  <section class="card" id="followups">
    <h2 class="section-title">Follow-ups due <span class="pill tier-good">{{ t.followups|length }}</span></h2>
    <p class="muted">5+ days with no reply. Open one to draft a follow-up or email #3.</p>
    {% for r in t.followups %}<div class="today-row">{{ job(r) }}</div>{% endfor %}
  </section>
  {% endif %}
  {% if t.ready %}
  <section class="card" id="ready">
    <h2 class="section-title">Ready to approve <span class="pill">{{ t.ready|length }}</span></h2>
    <p class="muted">People found. Check them and tap Approve to create Gmail drafts.</p>
    {% for r in t.ready %}<div class="today-row">{{ job(r) }}</div>{% endfor %}
  </section>
  {% endif %}
  {% if t.find_contacts %}
  <section class="card" id="find">
    <h2 class="section-title">{{ icon("people") }} Find contacts <span class="pill">{{ t.find_contacts|length }}</span></h2>
    <p class="muted">Drafts are written; find who to send them to. Best matches first.</p>
    {% for r in t.find_contacts[:5] %}<div class="today-row">{{ job(r) }}</div>{% endfor %}
    {% if t.find_contacts|length > 5 %}<p><a href="/">{{ t.find_contacts|length - 5 }} more in Jobs →</a></p>{% endif %}
  </section>
  {% endif %}
  {% if not (t.send or t.followups or t.ready or t.find_contacts) %}
  <section class="card empty"><h2>All caught up</h2><p>Nothing needs you right now. New jobs arrive after the 11:15 run.</p></section>
  {% endif %}
</div>
{% endblock %}
```

Add `now_hour` to the Today route in `src/jobseeker/web/pipeline.py`, so the greeting uses local time:

```python
@router.get("/today")
def today(request: Request, conn=Depends(get_conn)):
    return render(request, conn, "today.html", t=queries.today(conn, datetime.now(UTC)),
                  now_hour=datetime.now().astimezone().hour)
```

- [ ] **Step 4: Append the Today CSS to `ui.css` and delete the old `/* ---- Today ---- */` block from `app.css`**

```css
/* ---- Today ---- */
.page-head { margin: 0 0 18px; }
.page-head p { margin: 0; }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0 0 18px; }
.stat { display: flex; flex-direction: column; gap: 2px; color: var(--text); padding: 14px 16px; }
.stat:hover { border-color: var(--line-strong); box-shadow: var(--shadow-2); }
.stat b { font-size: 26px; line-height: 32px; font-weight: 500; }
.stat-label { font-size: 13px; color: var(--text-2); }
.today { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; max-width: 760px; }
.today-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; border-top: 1px solid var(--line); }
.today-job { display: flex; align-items: center; gap: 12px; color: var(--text); min-width: 0; flex: 1; }
.today-job-text { display: flex; flex-direction: column; min-width: 0; }
.today-job b { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 640px) {
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .stat b { font-size: 22px; }
}
```

- [ ] **Step 5: Run all tests**

Run: `FORCE_COLOR= uv run pytest --color=no`
Expected: all pass. `tests/test_web_today.py` still passes because the `Mark sent` form, `next=/today`, "Send in Gmail" and "All caught up" are all unchanged.

- [ ] **Step 6: Browser check** at 393×852 and 1440×900, light and dark:
- the greeting and 4 tiles render (2×2 on the phone);
- no horizontal scroll (`scrollWidth === innerWidth`);
- tapping "Need contacts" jumps to the section.

- [ ] **Step 7: Commit**

```bash
git add src/jobseeker/web/templates/today.html src/jobseeker/web/pipeline.py src/jobseeker/web/static/ui.css \
  src/jobseeker/web/static/app.css tests/test_web_redesign.py
git commit -m "feat(ui): Today dashboard with greeting, stat tiles and tiered match pills"
```

---

### Task 5: Jobs page

**Files:**
- Modify: `src/jobseeker/web/templates/inbox.html`
- Modify: `src/jobseeker/web/static/ui.css` (append the Jobs section)
- Modify: `src/jobseeker/web/static/mobile.css` (delete the `/* ---- Inbox ... ---- */` block, lines from `.cards {` through `.card-acts button`)
- Modify: `src/jobseeker/web/static/app.css` (delete the `table.inbox`, `.filters`, `.inbox-count` rules)
- Modify: `tests/test_web_mobile.py::test_inbox_filters_fold_and_cards_render`
- Test: `tests/test_web_redesign.py`

**Interfaces:**
- Consumes: `rows` (from `queries.inbox`, including `people`), `f` (filters), `families`, `cities`, `sources`, `tier`.
- Must keep: `<li class="swipe-card" data-app-id=… data-swipe>`, `.swipe-bg`, `.card-body`, `.card-link`, Skip/Snooze forms with `next="/"`, `table.inbox[data-keys=rows]` with `tr[data-href]` (desktop j/k keys), and the classes `next-step find|ready|wait` and `inbox-count`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_web_redesign.py`)

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_web_redesign.py -k jobs_page`
Expected: FAIL (no chips).

- [ ] **Step 3: Rewrite `src/jobseeker/web/templates/inbox.html`**

```jinja
{% extends "base.html" %}
{% block title %}Jobs · Job Seeker{% endblock %}
{% block content %}
{% macro q(**over) -%}
  {%- set p = dict(band=f.band, family=f.family, city=f.city, source=f.source) -%}{%- set _ = p.update(over) -%}
  /?{% for k, v in p.items() if v %}{{ k }}={{ v|urlencode }}{{ "&" if not loop.last }}{% endfor %}
{%- endmacro %}
<header class="page-head">
  <h1>Jobs</h1>
  <p class="inbox-count">{{ rows|length }} job{{ "s" if rows|length != 1 }}{% if rows %} · swipe ← skip, → snooze{% endif %}</p>
</header>
<div class="chips filter-chips">
  {% for b, label in [("apply", "Apply"), ("review", "Review"), ("all", "All")] %}
  <a class="chip{{ ' is-active' if f.band == b }}" href="{{ q(band=b) }}">{{ label }}</a>
  {% endfor %}
  <details class="chip-menu">
    <summary class="chip{{ ' is-active' if f.family }}">{{ f.family|replace("_", " ") if f.family else "Role" }} ▾</summary>
    <div class="menu"><a href="{{ q(family='') }}">All roles</a>{% for x in families %}<a href="{{ q(family=x) }}">{{ x|replace("_", " ") }}</a>{% endfor %}</div>
  </details>
  <details class="chip-menu">
    <summary class="chip{{ ' is-active' if f.city }}">{{ f.city|title if f.city else "City" }} ▾</summary>
    <div class="menu"><a href="{{ q(city='') }}">All cities</a>{% for x in cities %}<a href="{{ q(city=x) }}">{{ x|title }}</a>{% endfor %}</div>
  </details>
  <details class="chip-menu">
    <summary class="chip{{ ' is-active' if f.source }}">{{ f.source or "Source" }} ▾</summary>
    <div class="menu"><a href="{{ q(source='') }}">All sources</a>{% for x in sources %}<a href="{{ q(source=x) }}">{{ x }}</a>{% endfor %}</div>
  </details>
</div>
<div class="card table-card">
<table class="inbox" data-keys="rows">
  <thead><tr><th>Match</th><th>Role</th><th>Company</th><th>City</th><th>Age</th><th>Why</th><th></th></tr></thead>
  <tbody>
  {% for r in rows %}
    <tr data-href="/applications/{{ r.app_id }}">
      <td><span class="pill tier-{{ tier(r.score) }}">{{ r.score }}</span></td>
      <td><a class="row-title" href="/applications/{{ r.app_id }}">{{ r.title }}</a><small class="muted">{{ r.role_family|replace("_", " ") }} · {{ r.source }}</small></td>
      <td>{{ r.company }}</td>
      <td>{{ (r.location_city|title) if r.location_city else ("Remote" if r.remote else (r.location or "?")) }}</td>
      <td class="mono muted">{{ (r.posted_at or r.first_seen_at)|age }}</td>
      <td class="why">{% for m in (r.matches|fromjson)[:1] %}<span class="ok">✓ {{ m }}</span>{% endfor %}{% for g in (r.gaps|fromjson)[:1] %}<span class="warnc">⚠ {{ g }}</span>{% endfor %}</td>
      <td class="acts">
        <form method="post" action="/applications/{{ r.app_id }}/status"><input type="hidden" name="status" value="skipped"><input type="hidden" name="next" value="/"><button class="btn-ghost" data-key="s" title="Skip (s)">Skip</button></form>
        <form method="post" action="/applications/{{ r.app_id }}/snooze"><input type="hidden" name="next" value="/"><button class="btn-ghost" data-key="z" title="Snooze 3 days (z)">Snooze</button></form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="7" class="empty">We're still looking. New jobs arrive after the 11:15 run, or change the filters.</td></tr>
  {% endfor %}
  </tbody>
</table>
<p class="hint muted">j/k move · enter open · s skip · z snooze</p>
</div>
<ul class="cards">
  {% for r in rows %}
  <li class="swipe-card" data-app-id="{{ r.app_id }}" data-swipe>
    <div class="swipe-bg" aria-hidden="true"><span class="bg-snooze">Snooze</span><span class="bg-skip">Skip</span></div>
    <div class="card-body">
      <div class="card-top">
        <a class="card-link" href="/applications/{{ r.app_id }}">{{ r.title }}</a>
        <span class="pill tier-{{ tier(r.score) }}">{{ r.score }}</span>
      </div>
      <p class="card-meta">{{ r.company }} · {{ (r.location_city|title) if r.location_city else ("Remote" if r.remote else (r.location or "?")) }} · {{ (r.posted_at or r.first_seen_at)|age }}</p>
      <p class="card-why">{% for m in (r.matches|fromjson)[:1] %}<span class="ok">✓ {{ m }}</span>{% endfor %}{% for g in (r.gaps|fromjson)[:1] %}<span class="warnc">⚠ {{ g }}</span>{% endfor %}</p>
      <div class="card-foot">
        {% if r.status == "drafted" and r.people %}<span class="next-step ready">Ready to approve →</span>
        {% elif r.status == "drafted" %}<span class="next-step find">Find contacts →</span>
        {% else %}<span class="next-step wait">Drafts in next run</span>{% endif %}
        <div class="card-acts">
          <form method="post" action="/applications/{{ r.app_id }}/status"><input type="hidden" name="status" value="skipped"><input type="hidden" name="next" value="/"><button>Skip</button></form>
          <form method="post" action="/applications/{{ r.app_id }}/snooze"><input type="hidden" name="next" value="/"><button>Snooze</button></form>
        </div>
      </div>
    </div>
  </li>
  {% else %}
  <li class="empty">We're still looking. New jobs arrive after the 11:15 run, or change the filters.</li>
  {% endfor %}
</ul>
{% endblock %}
```

The old filters `<form>` with `<select name="band">` goes away; the chips build the same query parameters (`band`, `family`, `city`, `source`).

- [ ] **Step 4: Append the Jobs CSS to `ui.css` and delete the legacy inbox/card rules from `app.css` and `mobile.css`**

```css
/* ---- Jobs ---- */
.filter-chips { margin: 0 0 16px; }
.chip-menu { position: relative; }
.chip-menu > summary { list-style: none; }
.chip-menu > summary::-webkit-details-marker { display: none; }
.chip-menu .menu { position: absolute; z-index: 20; top: calc(100% + 6px); left: 0; min-width: 200px; max-height: 320px; overflow: auto;
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow-3); padding: 6px; }
.chip-menu .menu a { display: block; padding: 9px 10px; border-radius: 6px; color: var(--text); }
.chip-menu .menu a:hover { background: var(--muted-bg); }
.table-card { padding: 0; overflow: hidden; }
table.inbox { width: 100%; border-collapse: collapse; }
table.inbox th { text-align: left; font: 500 12px/1 var(--font); letter-spacing: .02em; text-transform: uppercase; color: var(--text-2);
  background: var(--muted-bg); padding: 10px 14px; border-bottom: 1px solid var(--line); }
table.inbox td { padding: 12px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }
table.inbox tr:hover td, table.inbox tr.sel td { background: var(--accent-wash); }
.row-title { display: block; color: var(--text); font-weight: 500; }
table.inbox .why span { display: block; font-size: 13px; }
table.inbox .acts { white-space: nowrap; }
table.inbox .acts form { display: inline; }
.hint { font-size: 12px; padding: 8px 14px; margin: 0; }
.cards { display: none; list-style: none; margin: 0; padding: 0; }
@media (max-width: 640px) {
  .table-card { display: none; }
  .cards { display: block; }
  .inbox-count { font-size: 13px; color: var(--text-2); margin: 0; }
  .chip-menu .menu { position: fixed; left: 16px; right: 16px; top: auto; bottom: calc(80px + env(safe-area-inset-bottom)); }
  .swipe-card { position: relative; margin-bottom: 10px; border-radius: var(--radius-card); overflow: hidden; touch-action: pan-y; }
  .swipe-bg { position: absolute; inset: 0; display: flex; align-items: center; justify-content: space-between; padding: 0 22px;
    font-weight: 600; visibility: hidden; }
  .swipe-card[data-dir] .swipe-bg { visibility: visible; }
  .swipe-card[data-dir=skip] .swipe-bg { background: var(--weak-bg); color: var(--weak-fg); }
  .swipe-card[data-dir=snooze] .swipe-bg { background: var(--good-bg); color: var(--good-fg); }
  .swipe-card[data-dir=skip] .bg-snooze, .swipe-card[data-dir=snooze] .bg-skip { visibility: hidden; }
  .card-body { position: relative; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-card);
    box-shadow: var(--shadow-1); padding: 14px 16px; }
  .card-top { display: flex; gap: 10px; align-items: flex-start; justify-content: space-between; }
  .card-link { font-weight: 600; color: var(--text); line-height: 1.35; min-width: 0; overflow-wrap: anywhere; }
  .card-link::after { content: ""; position: absolute; inset: 0; }
  .card-meta { margin: 4px 0 6px; color: var(--text-2); font-size: 13px; }
  .card-why { margin: 0 0 10px; font-size: 13px; display: flex; gap: 10px; min-width: 0; }
  .card-why span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .card-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .next-step { font-size: 13px; font-weight: 600; color: var(--text-2); }
  .next-step.find { color: var(--accent); } .next-step.ready { color: var(--strong-fg); }
  .card-acts { position: relative; z-index: 1; display: flex; gap: 6px; }
  .card-acts button { padding: 0 12px; font-size: 13px; }
}
```

- [ ] **Step 5: Update `tests/test_web_mobile.py::test_inbox_filters_fold_and_cards_render`.** Replace its two filter assertions (`'<details class="filters-box" open data-phone-closed>'` and `'<summary class="phone-only-summary">Filters</summary>'`) with:

```python
    assert 'class="chips filter-chips"' in html
```

Keep the card assertions.

- [ ] **Step 6: Run all tests and the Node tests**

Run: `FORCE_COLOR= uv run pytest --color=no` and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/`
Expected: all pass. The swipe tests are untouched because the swipe hooks are unchanged.

- [ ] **Step 7: Browser check.** At 393×852, light and dark:
- swipe one card left with synthetic touch events; the toast appears; Undo returns to `/?band=…` keeping filters;
- the Role chip opens its menu above the tab bar;
- no horizontal scroll.

At 1440×900: the table renders and j/k moves the selection.

- [ ] **Step 8: Commit**

The message lists the changed assertion (filters-box / phone-only-summary replaced by `chips filter-chips`).

```bash
git add src/jobseeker/web/templates/inbox.html src/jobseeker/web/static/ui.css src/jobseeker/web/static/app.css \
  src/jobseeker/web/static/mobile.css tests/
git commit -m "feat(ui): Jobs page with chip filters, tiered pills and restyled swipe cards

Test change: test_inbox_filters_fold_and_cards_render now checks the chip filter row
instead of the old filters <details>/<summary> (filters are chips, not a folded form)."
```

---

### Task 6: Job page decision block, step bar and More menu

**Files:**
- Modify: `src/jobseeker/web/application.py` (`detail` passes `bars`, `step`, `timeline_items`)
- Modify: `src/jobseeker/web/templates/application.html` (header, decision block, step bar, More menu)
- Modify: `src/jobseeker/web/static/ui.css` (append the Job page section, part 1)
- Modify: `tests/test_web_mobile.py::test_job_page_blocks_and_more_menu`
- Test: `tests/test_web_redesign.py`

**Interfaces:**
- Consumes: `factor_bars`, `next_step`, `timeline`, `STEPS`, `TIER_LABELS`, `tier`, `app.state.rubric`.
- Produces template context keys `bars: list[dict]`, `step: int | None`, `timeline_items: list[dict]`. The approve `<form class="approve">` keeps its action and its `confirm_*` checkboxes.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_redesign.py`)

```python
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
    _drafted(settings, a)
    html = client(settings).get(f"/applications/{a}").text
    assert 'class="steps"' in html and 'class="step is-current"' in html
    current = html.split('class="step is-current"', 1)[1][:120]
    assert "Find contacts" in current
    assert 'action="/applications/%d/contacts/find"' % a in html


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_web_redesign.py -k "job_page or more_menu"`
Expected: 4 failed.

- [ ] **Step 3: Pass the helpers from the route.** In `src/jobseeker/web/application.py::detail`, replace the `return render(...)` with:

```python
    from jobseeker.web.view import factor_bars, next_step, timeline

    ctx = card_context(request, conn, app_id)
    bars = factor_bars(d["score"]["breakdown"], request.app.state.rubric) if d["score"] else []
    return render(request, conn, "application.html", terms=terms, matched_skills=matched,
                  can_undo=can_undo(conn, app_id), bars=bars,
                  step=next_step(d["app"]["status"], bool(ctx["people"])),
                  timeline_items=timeline(d["events"]), **ctx, **d)
```

- [ ] **Step 4: Replace the top of `application.html`**: everything from `<div class="detail">` up to, but not including, `<details class="block jd-box"`. The body below (JD, People, drafts, notes, history) stays for now; Task 7 restructures it.

```jinja
{% from "_icons.html" import icon %}
<div class="job">
  <header class="job-head">
    <a class="back" href="/">{{ icon("back", 18) }} Jobs</a>
    <div class="job-title-row">
      <div class="job-title">
        <h1>{{ job.title }}</h1>
        <p class="muted">{{ job.company }} · {{ job.location or "Location not stated" }}{% if job.remote %} · Remote{% endif %} · {{ job.source }} · posted {{ (job.posted_at or job.first_seen_at)|age }}{% if job.salary_text %} · {{ job.salary_text }}{% endif %}</p>
      </div>
      <div class="job-head-acts">
        <span class="pill">{{ app.status|replace("_", " ") }}</span>
        <a class="btn" href="{{ job.apply_url }}" target="_blank" rel="noopener">Open posting {{ icon("external", 16) }}</a>
      </div>
    </div>
  </header>

  {% if score %}
  {% set t = tier(score.score) %}
  <section class="card decision">
    <div class="decision-score">
      <div class="ring tier-{{ t }}" style="--pct: {{ score.score }}"><span class="ring-score">{{ score.score }}</span><span class="ring-label">match</span></div>
      <p class="decision-tier {{ 'ok' if t == 'strong' else ('warnc' if t == 'good' else 'bad') }}">{{ TIER_LABELS[t] }}</p>
    </div>
    {% if bars %}
    <ul class="bars">
      {% for b in bars %}
      <li><span class="bar-label">{{ b.label }}</span><span class="bar"><span class="bar-fill" style="width: {{ b.pct }}%"></span></span><span class="bar-num mono">{{ b.value }}/{{ b.max }}</span></li>
      {% endfor %}
    </ul>
    {% endif %}
    <div class="decision-lists">
      <div><p class="label">Why you match</p><ul class="plain">{% for m in score.matches|fromjson %}<li class="ok">✓ {{ m }}</li>{% else %}<li class="muted">Nothing specific noted</li>{% endfor %}</ul></div>
      <div><p class="label">Watch out</p><ul class="plain">{% for g in score.gaps|fromjson %}<li class="warnc">⚠ {{ g }}</li>{% else %}<li class="muted">No gaps noted</li>{% endfor %}</ul></div>
    </div>
  </section>
  {% endif %}

  {% if step %}
  <section class="card next">
    <ol class="steps">
      {% for label in STEPS %}
      <li class="step{{ ' is-done' if loop.index < step }}{{ ' is-current' if loop.index == step }}"><span class="step-num mono">{{ loop.index }}</span><span>{{ label }}</span></li>
      {% endfor %}
    </ol>
    <div class="next-action">
      {% if step == 1 %}
        <form method="post" action="/applications/{{ app.id }}/contacts/find"><button class="primary" {% if not has_tavily %}disabled{% endif %}>{{ icon("people", 18) }} Find contacts</button></form>
        <p class="muted">Finds 3 people at {{ job.company }} with work emails. About half a minute.</p>
      {% elif step == 2 %}
        <p class="muted trust">Creates Gmail drafts for {{ people|selectattr("wave", "equalto", 1)|map(attribute="name")|join(" and ") or "your contact" }}. Nothing is sent until you press Send in Gmail.</p>
        <p class="muted"><a href="#approve">Review people and drafts below, then Approve ↓</a></p>
      {% elif step == 3 %}
        <a class="btn btn-primary" href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener">{{ icon("gmail", 18) }} Open Gmail drafts</a>
        <form method="post" action="/applications/{{ app.id }}/status"><input type="hidden" name="status" value="sent"><button>Mark sent</button></form>
      {% else %}
        <p class="muted">Sent. Follow-ups appear here 5 days after Mark sent if there's no reply.</p>
      {% endif %}
    </div>
  </section>
  {% endif %}

<div class="detail">
  <section class="col-main">
```

At the very end of the template, before `{% endblock %}`, add one extra `</div>` to close `<div class="job">`.

- [ ] **Step 5: Turn the old actions card into the approve card plus a More menu.** In `application.html`, replace the whole `<div class="card block actions">…</div>` with the block below. The approve form is unchanged except for its id and the trust line.

```jinja
    <div class="card block actions" id="approve">
      <form method="post" action="/applications/{{ app.id }}/approve" class="approve">
        {% set wave1 = people|selectattr("wave", "equalto", 1)|list %}
        {% set linked_ids = people|map(attribute="contact_id")|list %}
        {% if people and contact and contact.id not in linked_ids and contact.email and contact.email_status == "unverified" %}
        <label><input type="checkbox" name="confirm_0" value="true"> {{ contact.name or contact.email }}'s email is unverified, draft anyway</label>
        {% endif %}
        {% if wave1 %}
          {% for p in wave1 if p.email and p.email_status == "unverified" %}
          <label><input type="checkbox" name="confirm_{{ p.rank }}" value="true"> {{ p.name }}'s email is unverified, draft anyway</label>
          {% endfor %}
        {% elif contact and contact.email and contact.email_status != "verified" %}
        <label><input type="checkbox" name="confirm_unverified" value="true"> Email is unverified, draft anyway</label>
        {% endif %}
        {% if drafts.email and drafts.email.gmail_draft_id %}<p class="warnc">A Gmail draft already exists (id {{ drafts.email.gmail_draft_id }}). Approving again creates another; delete the older one in Gmail.</p>{% endif %}
        <p class="muted trust">AI prepared this. You approve, Gmail keeps it as a draft, you press Send.</p>
        <button class="primary">Approve → Gmail draft</button>
      </form>
      <details class="more-menu">
        <summary class="btn" aria-label="More actions">{{ icon("more", 18) }} More</summary>
        <div class="menu">
          {% if drafts.email and drafts.email.gmail_draft_id %}<a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener">Open Gmail drafts ↗</a>{% endif %}
          {% for s, label in [("sent", "Mark sent"), ("applied_via_portal", "Applied via portal"), ("skipped", "Skip")] %}
          <form method="post" action="/applications/{{ app.id }}/status"><input type="hidden" name="status" value="{{ s }}"><button class="btn-ghost">{{ label }}</button></form>
          {% endfor %}
          <form method="post" action="/applications/{{ app.id }}/snooze"><button class="btn-ghost">Snooze 3d</button></form>
          {% if app.status == "sent" %}<form method="post" action="/applications/{{ app.id }}/followed-up"><button class="btn-ghost">Mark followed up ({{ app.followups_sent }}/2)</button></form>{% endif %}
          {% if drafts and app.status in ["new", "shortlisted", "drafted", "approved"] %}<form method="post" action="/applications/{{ app.id }}/draft"><button class="btn-ghost">Regenerate all drafts</button></form>{% endif %}
          {% if can_undo %}<form method="post" action="/applications/{{ app.id }}/undo"><button class="btn-ghost">Undo last change</button></form>{% endif %}
          <form method="post" action="/applications/{{ app.id }}/not-interested" class="danger-zone">
            <label><input type="checkbox" name="block_company" value="true"> also block company</label>
            <button class="btn-ghost bad">Not interested</button>
          </form>
        </div>
      </details>
    </div>
```

Before replacing it, check the previous template's exact label texts with `git show HEAD:src/jobseeker/web/templates/application.html | grep -n "Regenerate\|followed-up"`. If the old label is "Regenerate all drafts", keep that exact text.

- [ ] **Step 6: Append the Job page CSS (part 1) to `ui.css`**

```css
/* ---- Job page: header, decision, steps, approve ---- */
.job { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; }
.back { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2); font-size: 14px; margin-bottom: 8px; }
.job-title-row { display: flex; gap: 16px; align-items: flex-start; justify-content: space-between; }
.job-title { min-width: 0; }
.job-title h1 { overflow-wrap: anywhere; }
.job-title p { margin: 0; }
.job-head-acts { display: flex; gap: 8px; align-items: center; flex: 0 0 auto; }
.decision { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 18px 28px; align-items: center;
  box-shadow: inset 0 0 0 1px var(--accent-wash), var(--shadow-1); }
.decision-score { text-align: center; }
.ring { --pct: 0; --ring: var(--neutral-fg); width: 112px; height: 112px; border-radius: 50%; display: grid; place-content: center; text-align: center;
  background: radial-gradient(closest-side, var(--surface) 78%, transparent 79% 100%),
              conic-gradient(var(--ring) calc(var(--pct) * 1%), var(--muted-bg) 0); }
.ring.tier-strong { --ring: var(--strong-dot); } .ring.tier-good { --ring: var(--good-dot); } .ring.tier-weak { --ring: var(--weak-dot); }
.ring.tier-strong, .ring.tier-good, .ring.tier-weak { color: var(--text); border: 0; }
.ring-score { font: 600 32px/1 var(--mono); }
.ring-label { font: 500 11px/1.6 var(--font); text-transform: uppercase; letter-spacing: .04em; color: var(--text-2); }
.decision-tier { margin: 8px 0 0; font-weight: 600; font-size: 14px; }
.bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 9px; }
.bars li { display: grid; grid-template-columns: 120px minmax(0, 1fr) 52px; gap: 10px; align-items: center; font-size: 13px; }
.bar { height: 8px; border-radius: 9999px; background: var(--muted-bg); overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: inherit; background: var(--accent); }
.bar-num { text-align: right; color: var(--text-2); font-size: 12px; }
.decision-lists { grid-column: 1 / -1; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; border-top: 1px solid var(--line); padding-top: 14px; }
.decision-lists .label { margin: 0 0 6px; }
ul.plain { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; font-size: 14px; }
.steps { list-style: none; margin: 0 0 14px; padding: 0; display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.step { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-3); padding-top: 10px; border-top: 3px solid var(--line); }
.step-num { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 11px; background: var(--muted-bg); }
.step.is-done { color: var(--text-2); border-top-color: var(--strong-dot); }
.step.is-done .step-num { background: var(--strong-bg); color: var(--strong-fg); }
.step.is-current { color: var(--text); font-weight: 600; border-top-color: var(--accent); }
.step.is-current .step-num { background: var(--accent); color: #fff; }
.next-action { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.next-action p { margin: 0; flex-basis: 100%; }
.trust { font-size: 13px; }
.actions .approve { display: grid; gap: 10px; }
.actions .approve button.primary { width: 100%; }
.more-menu { position: relative; margin-top: 10px; }
.more-menu > summary { list-style: none; width: 100%; }
.more-menu > summary::-webkit-details-marker { display: none; }
.more-menu .menu { margin-top: 8px; display: grid; gap: 2px; border: 1px solid var(--line); border-radius: 12px; padding: 6px; background: var(--surface); }
.more-menu .menu button, .more-menu .menu a { width: 100%; justify-content: flex-start; }
.more-menu .menu a { display: flex; align-items: center; min-height: 44px; padding: 0 14px; color: var(--text); }
.danger-zone { border-top: 1px solid var(--line); margin-top: 4px; padding-top: 6px; display: grid; gap: 4px; font-size: 13px; }
@media (max-width: 640px) {
  .job-title-row { flex-direction: column; gap: 10px; }
  .decision { grid-template-columns: 1fr; justify-items: stretch; }
  .decision-score { display: flex; align-items: center; gap: 14px; text-align: left; }
  .ring { width: 88px; height: 88px; } .ring-score { font-size: 26px; }
  .bars li { grid-template-columns: 96px minmax(0, 1fr) 46px; }
  .decision-lists { grid-template-columns: 1fr; }
  .steps { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .step span:last-child { font-size: 11px; line-height: 1.2; }
  .step { flex-direction: column; align-items: flex-start; gap: 4px; }
}
```

- [ ] **Step 7: Update `tests/test_web_mobile.py::test_job_page_blocks_and_more_menu`** to the new markup (replace the whole test body):

```python
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
```

The `can_undo` label only renders if undo is possible. If "Undo last change" fails for the seeded data, first make a status change in the test (`client.post(f"/applications/{a}/status", data={"status": "skipped"})`) exactly as the old test's data did. Check with `git show HEAD:tests/test_web_mobile.py`.

Delete `test_mobile_css_makes_approve_full_width` and `test_phone_job_description_sits_right_under_the_header`; both check `mobile.css` page rules that this task replaces. Their replacements are `.actions .approve button.primary { width: 100% }` in `ui.css` here, and the phone tab order in Task 7.

- [ ] **Step 8: Run all tests**

Run: `FORCE_COLOR= uv run pytest --color=no`
Expected: all pass.

- [ ] **Step 9: Browser check of `/applications/<a drafted id>`** at 393×852 and 1440×900, light and dark:
- the ring colour matches the tier;
- the bars fill proportionally;
- the step bar shows ① as current, and the Find contacts button works (it posts and returns);
- the More menu opens and closes;
- no horizontal scroll.

- [ ] **Step 10: Commit**

The message lists the test changes.

```bash
git add src/jobseeker/web/application.py src/jobseeker/web/templates/application.html src/jobseeker/web/static/ui.css tests/
git commit -m "feat(ui): job page decision block (ring, factor bars), next-step bar and More menu

Test changes: test_job_page_blocks_and_more_menu now checks job-head and details.more-menu
(was block head / details.more); removed test_mobile_css_makes_approve_full_width and
test_phone_job_description_sits_right_under_the_header (legacy mobile.css rules replaced)."
```

---

### Task 7: Job page body, phone tabs and timeline

**Files:**
- Create: `src/jobseeker/web/static/tabs.js`
- Create: `tests/js/tabs.test.mjs`
- Modify: `src/jobseeker/web/templates/application.html` (body layout)
- Modify: `src/jobseeker/web/templates/_people.html` (person cards restyle)
- Modify: `src/jobseeker/web/templates/base.html` (load `tabs.js`)
- Modify: `src/jobseeker/web/static/ui.css` (append the Job page part 2 section)
- Modify: `src/jobseeker/web/static/app.css` and `mobile.css` (delete the `.detail`, `.people`, `.person`, `.kcard`-unrelated job page rules)
- Test: `tests/test_web_redesign.py`, `tests/test_js.py` (register the new Node test file if `test_js.py` lists files explicitly)

**Interfaces:**
- Produces:
  - `tabs.js` exports `resolveTab(available: string[], requested: string | null, fallback: string) -> string`.
  - DOM contract: a container `[data-tabs]` with an optional `data-default`, buttons `[data-tab=NAME]`, and panels `[data-panel=NAME]`. JS adds `.is-hidden` to inactive panels and `.is-active` to the active button. CSS hides `.is-hidden` only at ≤640px.

- [ ] **Step 1: Write the failing JS test** `tests/js/tabs.test.mjs`

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { resolveTab } = require("../../src/jobseeker/web/static/tabs.js");

test("requested tab wins when it exists", () => assert.equal(resolveTab(["people", "draft", "job"], "draft", "people"), "draft"));
test("unknown request falls back", () => assert.equal(resolveTab(["people", "draft", "job"], "nope", "job"), "job"));
test("missing fallback picks the first", () => assert.equal(resolveTab(["a", "b"], null, "zzz"), "a"));
test("no tabs gives empty", () => assert.equal(resolveTab([], "a", "b"), ""));
```

Check how `tests/test_js.py` runs Node (`grep -n "node" tests/test_js.py`). If it runs a single file, change it to run every `tests/js/*.test.mjs`.

- [ ] **Step 2: Write the failing Python test** (append to `tests/test_web_redesign.py`)

```python
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/` and `FORCE_COLOR= uv run pytest --color=no tests/test_web_redesign.py -k phone_tabs`
Expected: the Node tests fail (module not found); the pytest test fails.

- [ ] **Step 4: Write `src/jobseeker/web/static/tabs.js`**

```js
/* Phone tabs and stage chips: [data-tabs] > [data-tab=x] buttons + [data-panel=x] panels. CSS hides .is-hidden only on phones,
   so desktop and no-JS readers always see every panel. */
(function (root) {
  function resolveTab(available, requested, fallback) {
    if (!available.length) return "";
    if (requested && available.includes(requested)) return requested;
    return available.includes(fallback) ? fallback : available[0];
  }
  const api = { resolveTab };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

  function show(box, name) {
    box.querySelectorAll("[data-tab]").forEach((b) => {
      const on = b.dataset.tab === name;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    box.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("is-hidden", p.dataset.panel !== name));
    box.dataset.current = name;
  }
  function init() {
    document.querySelectorAll("[data-tabs]").forEach((box) => {
      const names = [...box.querySelectorAll("[data-tab]")].map((b) => b.dataset.tab);
      show(box, resolveTab(names, box.dataset.current || null, box.dataset.default || ""));
      if (box.dataset.bound) return;  // listener on the container survives the People card's outerHTML refresh
      box.dataset.bound = "1";
      box.addEventListener("click", (e) => {
        const b = e.target.closest("[data-tab]");
        if (b && box.contains(b)) { e.preventDefault(); show(box, b.dataset.tab); }
      });
    });
  }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
  document.addEventListener("htmx:historyRestore", init);
})(typeof window !== "undefined" ? window : globalThis);
```

Add `<script src="{{ asset('tabs.js') }}" defer></script>` after `keys.js` in `base.html`.

- [ ] **Step 5: Restructure the body of `application.html`.** Replace everything from `<div class="detail">` (opened at the end of Task 6's header block) to the end of the file with the block below. The drafts card, notes form and approve card keep the exact forms from the current template; copy them in unchanged where marked.

```jinja
<div class="job-body" data-tabs data-default="{{ 'draft' if app.status == 'approved' else ('people' if app.status == 'drafted' else 'job') }}">
  <div class="tab-bar chips" role="tablist">
    <button type="button" class="chip" data-tab="people" role="tab">{{ icon("people", 16) }} People{% if people %} <span class="count">{{ people|length }}</span>{% endif %}</button>
    <button type="button" class="chip" data-tab="draft" role="tab">{{ icon("draft", 16) }} Draft</button>
    <button type="button" class="chip" data-tab="job" role="tab">{{ icon("job", 16) }} Job</button>
  </div>

  <section class="panel panel-job" data-panel="job">
    <details class="card block jd-box" open>
      <summary><h2>Job description <span class="muted">· {{ matched_skills }} skills matched</span></h2></summary>
      <article class="jd">{{ job.jd_text|highlight(terms) }}</article>
    </details>
    <div class="card block notes">
      <h2>Notes</h2>
      <!-- COPY the existing <form method="post" action="/applications/{{ app.id }}/notes"> … </form> unchanged -->
    </div>
    <section class="card block history">
      <h2>History</h2>
      <ol class="timeline">{% for e in timeline_items %}<li><span class="mono muted">{{ e.day }}</span> {{ e.text }}</li>{% else %}<li class="muted">Nothing yet.</li>{% endfor %}</ol>
    </section>
  </section>

  <section class="panel panel-people" data-panel="people">
    {% include "_people.html" %}
    <details class="add-person">
      <summary class="btn btn-ghost">+ Add someone myself</summary>
      <div class="card block contact">
        <h2>Add someone myself</h2>
        <!-- COPY the existing "Add someone myself" contents unchanged: the suggested-role <p>, the {% set own = … %} line and the <form …/contact> -->
      </div>
    </details>
  </section>

  <section class="panel panel-draft" data-panel="draft">
    <div class="card block drafts">
      <!-- COPY the existing drafts card contents unchanged (h2 Drafts, warnings, Draft now / Email / LinkedIn note / LinkedIn DM) -->
    </div>
    <!-- MOVE the Task 6 <div class="card block actions" id="approve"> … </div> here, unchanged -->
  </section>
</div>
</div>
{% endblock %}
```

Replace each `COPY` / `MOVE` comment with the referenced markup from the current file. Remove the old `<details class="block jd-box" open data-phone-closed>` and its `phone-only-summary`. The JD summary text keeps "· N skills matched": update `test_jd_summary_counts_matched_skills` to assert `"2 skills matched" in html`.

- [ ] **Step 6: Restyle `_people.html` person rows.** Keep every form and action, the `id="people-card"` polling attributes, and the `data-copy` buttons.
- Wrap each person in `<article class="person">`.
- Show the email status as a pill: `{% if p.email_status == 'verified' %}<span class="pill tier-strong">verified</span>{% elif p.email_status == 'bounced' %}<span class="pill tier-weak">bounced</span>{% else %}<span class="pill tier-good">likely</span>{% endif %}`.
- Show the rank as `<span class="rank mono">#{{ p.rank }}</span>`.
- Keep the label tag as `<span class="pill">{{ p.label|replace("_", " ") }}</span>`.

- [ ] **Step 7: Append the Job page part 2 CSS and delete the old `.detail` / `.col-main` / `.col-side` / `.jd` / `.people` / `.person` / `.events` / `.scorebox` rules from `app.css` and `mobile.css`**

```css
/* ---- Job page: body, tabs, people, drafts, timeline ---- */
.job-body { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); grid-template-areas: "tabs tabs" "job people" "job draft"; gap: 14px; align-items: start; }
.tab-bar { grid-area: tabs; display: none; }
.panel { display: grid; gap: 14px; min-width: 0; }
.panel-job { grid-area: job; } .panel-people { grid-area: people; } .panel-draft { grid-area: draft; }
.jd-box > summary { list-style: none; cursor: pointer; }
.jd-box > summary::-webkit-details-marker { display: none; }
.jd { white-space: pre-wrap; font-size: 14px; line-height: 1.65; color: var(--text); overflow-wrap: anywhere; }
.jd mark { background: var(--strong-bg); color: var(--strong-fg); border-radius: 4px; padding: 0 2px; }
.person { border-top: 1px solid var(--line); padding: 12px 0; display: grid; gap: 6px; }
.person:first-of-type { border-top: 0; }
.rank { color: var(--text-3); margin-right: 4px; }
.person p { margin: 0; }
.add-person > summary { list-style: none; }
.add-person > summary::-webkit-details-marker { display: none; }
.add-person[open] > summary { display: none; }
.contact form.grid, .person-edit form.grid { display: grid; gap: 8px; }
.drafts details > summary { cursor: pointer; font-weight: 500; padding: 6px 0; }
.drafts input[name=subject] { width: 100%; margin-bottom: 8px; }
ol.timeline { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; font-size: 14px; }
ol.timeline li { display: flex; gap: 10px; }
ol.timeline .mono { flex: 0 0 52px; font-size: 12px; padding-top: 2px; }
@media (max-width: 640px) {
  .job-body { display: block; }
  .tab-bar { display: flex; position: sticky; top: calc(52px + env(safe-area-inset-top)); z-index: 10; background: var(--bg); padding: 8px 0; margin-bottom: 6px; }
  .tab-bar .chip { flex: 1; justify-content: center; min-height: 44px; }
  .panel.is-hidden { display: none; }
  .panel + .panel { margin-top: 14px; }
}
```

- [ ] **Step 8: Run all Python and Node tests**

Run: `FORCE_COLOR= uv run pytest --color=no` and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/`
Expected: all pass. The tests that check People-card markup (`tests/test_web_contacts*.py`) must still pass. If one checks a removed wrapper, update it, keeping its behavioural intent, and list it in the commit message.

- [ ] **Step 9: Browser check** at 393×852.

- The drafted job opens on People.
- Tap Draft, then Job: the panels switch with no page reload, and the tab bar stays under the top bar while scrolling.
- Click Find contacts: the People card polls every 3 s and refreshes without resetting the active tab.
- Navigate Jobs → a job → back with `hx-boost`: the tabs still work.

At 1440×900, the two-column layout shows all panels and the tab bar is hidden. Check dark mode.

- [ ] **Step 10: Commit**

```bash
git add src/jobseeker/web/static/tabs.js tests/js/tabs.test.mjs src/jobseeker/web/templates/ src/jobseeker/web/static/ tests/
git commit -m "feat(ui): job page body with People/Draft/Job phone tabs, restyled people cards and readable timeline"
```

---

### Task 8: Pipeline, and removing the legacy stylesheets

**Files:**
- Modify: `src/jobseeker/db/queries.py` (add a `people` count column to `pipeline()`)
- Modify: `src/jobseeker/web/templates/pipeline.html`
- Modify: `src/jobseeker/web/static/ui.css` (append the Pipeline section)
- Modify: `src/jobseeker/web/templates/base.html` (stop linking `app.css` / `mobile.css`)
- Delete: `src/jobseeker/web/static/app.css`, `src/jobseeker/web/static/mobile.css`
- Modify: `tests/test_web_mobile.py` (pipeline, CSS-contract and fingerprint tests)
- Test: `tests/test_web_redesign.py`

**Interfaces:**
- Consumes: `board` (from `queries.pipeline`, now with `people`), `columns`, `st`, `allowed_next`, `tier`, and `tabs.js` (the stage chips reuse `[data-tabs]`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_web_redesign.py`)

```python
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


def test_pipeline_opens_on_sent_when_a_follow_up_is_due(settings, seeded):
    from datetime import UTC, datetime, timedelta

    from jobseeker.db.core import connect

    a = seeded[0]
    conn = connect(settings.db_path)
    then = (datetime.now(UTC) - timedelta(days=6)).isoformat(timespec="seconds")
    conn.execute("UPDATE applications SET status = 'sent' WHERE id = ?", (a,))
    conn.execute("INSERT INTO events (application_id, at, type, payload) VALUES (?, ?, 'status', '{\"to\": \"sent\"}')", (a, then))
    conn.commit()
    html = client(settings).get("/pipeline").text
    assert 'data-tabs data-default="sent"' in html and 'class="kcard due"' in html


def test_legacy_stylesheets_are_gone(settings, seeded):
    html = client(settings).get("/today").text
    assert "app.css" not in html and "mobile.css" not in html
    assert not (STATIC / "app.css").exists() and not (STATIC / "mobile.css").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_web_redesign.py -k "pipeline or legacy"`
Expected: 3 failed.

- [ ] **Step 3: Add `people` to `queries.pipeline`.** In `src/jobseeker/db/queries.py::pipeline`, add this select column after `a.followups_sent,`:

```python
                   (SELECT COUNT(*) FROM application_contacts ac WHERE ac.application_id = a.id) AS people,
```

- [ ] **Step 4: Rewrite `src/jobseeker/web/templates/pipeline.html`**

```jinja
{% extends "base.html" %}
{% block title %}Pipeline · Job Seeker{% endblock %}
{% block content %}
{% set active = ["shortlisted", "drafted", "approved", "sent", "replied", "interview", "offer"] %}
{% set closed = board.applied_via_portal + board.rejected %}
{% set due = board.sent|selectattr("needs_followup")|list %}
{% set default = "sent" if due else "drafted" %}
{% macro card(c) %}
<article class="kcard{{ ' due' if c.needs_followup }}">
  <div class="kcard-top"><a class="kcard-title" href="/applications/{{ c.app_id }}">{{ c.title }}</a><span class="pill tier-{{ tier(c.score) }}">{{ c.score }}</span></div>
  <p class="muted">{{ c.company }} · <span class="mono">{{ c.days_since }}d</span> since last action</p>
  {% if c.third %}<p class="warnc"><b>⚠ Email #3: {{ c.third.name.split()[0] }}</b></p>
  {% elif c.needs_followup %}<p class="warnc"><b>⚠ Follow up</b></p>
  {% elif c.status == "drafted" and c.people %}<span class="next-step ready">Ready to approve →</span>
  {% elif c.status == "drafted" %}<span class="next-step find">Find contacts →</span>
  {% elif c.status == "approved" %}<span class="next-step find">Send in Gmail →</span>{% endif %}
  {% set nexts = allowed_next(c.status) %}
  {% if nexts %}
  <form method="post" action="/applications/{{ c.app_id }}/status" class="move">
    <input type="hidden" name="next" value="/pipeline">
    <select name="status" aria-label="Move to">{% for s in nexts %}<option value="{{ s }}">{{ s|replace("_", " ") }}</option>{% endfor %}</select>
    <button>Move</button>
  </form>
  {% endif %}
</article>
{% endmacro %}
<header class="page-head"><h1>Pipeline</h1><p class="muted">Every application after the inbox, by stage.</p></header>
<div class="stats pipe-stats">
  {% for n, label in [(st.drafted, "Drafted (30d)"), (st.sent, "Sent"), (st.replied, "Replies"), ((st.reply_rate * 100)|round|int ~ "%", "Reply rate"), (st.interviews, "Interviews")] %}
  <div class="stat card"><b>{{ n }}</b><span class="stat-label">{{ label }}</span></div>
  {% endfor %}
</div>
<div class="board" data-tabs data-default="{{ default }}">
  <div class="chips stage-chips" role="tablist">
    {% for s in active %}<button type="button" class="chip" data-tab="{{ s }}" role="tab">{{ s|capitalize }} <span class="count">{{ board[s]|length }}</span></button>{% endfor %}
    <button type="button" class="chip" data-tab="closed" role="tab">Closed <span class="count">{{ closed|length }}</span></button>
  </div>
  <div class="columns">
    {% for s in active %}
    <section class="column" data-panel="{{ s }}">
      <h3 class="column-head label">{{ s }} <span class="count mono">{{ board[s]|length }}</span></h3>
      {% for c in board[s] %}{{ card(c) }}{% else %}<p class="empty">Nothing {{ s }} yet.</p>{% endfor %}
    </section>
    {% endfor %}
    <section class="column column-closed" data-panel="closed">
      <h3 class="column-head label">Closed <span class="count mono">{{ closed|length }}</span></h3>
      {% for c in closed %}{{ card(c) }}{% else %}<p class="empty">Nothing closed yet.</p>{% endfor %}
    </section>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Append the Pipeline CSS, stop linking the legacy files, and delete them**

Append to `ui.css`:

```css
/* ---- Pipeline ---- */
.pipe-stats { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.stage-chips { display: none; }
.columns { display: grid; grid-auto-flow: column; grid-auto-columns: 280px; gap: 12px; overflow-x: auto; padding-bottom: 12px; scroll-snap-type: x proximity; }
.column { background: rgba(244, 244, 240, .6); border: 1px solid var(--line); border-radius: var(--radius-card); padding: 10px; display: grid; gap: 10px;
  align-content: start; scroll-snap-align: start; min-height: 160px; }
@media (prefers-color-scheme: dark) { .column { background: var(--muted-bg); } }
.column-head { display: flex; align-items: center; justify-content: space-between; margin: 2px 4px; }
.column .empty { padding: 18px 8px; font-size: 13px; }
.kcard { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 12px; display: grid; gap: 6px; box-shadow: var(--shadow-1); }
.kcard:hover { border-color: var(--line-strong); box-shadow: var(--shadow-2); }
.kcard.due { border-color: var(--good-line); background: var(--good-bg); }
.kcard-top { display: flex; gap: 8px; align-items: flex-start; justify-content: space-between; }
.kcard-title { color: var(--text); font-weight: 500; overflow-wrap: anywhere; }
.kcard p { margin: 0; font-size: 13px; }
.kcard .move { display: flex; gap: 6px; }
.kcard .move select { flex: 1; min-height: 36px; padding: 4px 8px; font-size: 13px; }
.kcard .move button { min-height: 36px; font-size: 13px; }
.next-step { font-size: 13px; font-weight: 600; color: var(--text-2); }
.next-step.find { color: var(--accent); } .next-step.ready { color: var(--strong-fg); }
@media (max-width: 640px) {
  .pipe-stats { display: flex; overflow-x: auto; }
  .pipe-stats .stat { flex: 0 0 120px; }
  .stage-chips { display: flex; margin: 0 0 12px; }
  .columns { display: block; overflow: visible; }
  .column { background: transparent; border: 0; padding: 0; }
  .column.is-hidden { display: none; }
  .column-head { display: none; }
}
```

The `.next-step` rules move out of the phone-only Jobs block into this global section; delete the duplicate from the Task 5 media query.

In `base.html`, delete the two `<link>` lines for `app.css` and `mobile.css`. Then:

```bash
git rm src/jobseeker/web/static/app.css src/jobseeker/web/static/mobile.css
```

Check that no rules still used only by `app.css`/`mobile.css` are lost: run `grep -rhoE 'class="[^"]+"' src/jobseeker/web/templates | tr ' "' '\n\n' | sort -u` and confirm that every visible class (except JS hooks such as `swipe-card`, `sel`, `typing`) has a rule in `ui.css`. Add any missing ones to the relevant `ui.css` section. Known small ones: `.tag` (map to the `.pill` style) and `.warn` (the run-notes summary colour).

- [ ] **Step 6: Update the old tests in `tests/test_web_mobile.py`**
- `test_base_has_phone_meta_and_toast`: replace `'href="/static/mobile.css?v='` with `'href="/static/ui.css?v='`.
- `test_mobile_css_contract`: delete it (superseded by `test_ui_css_contract`).
- `test_pipeline_columns_are_collapsible`: delete it (superseded by `test_pipeline_columns_chips_and_default_stage`).
- `test_keys_js_folds_for_phone_and_copies_without_opening`: unchanged (`keys.js` is unchanged).
- `test_static_assets_are_fingerprinted_so_phones_get_updates`: change the tuple to `("ui.css", "swipe.js", "keys.js", "tabs.js", "htmx.min.js")`.

- [ ] **Step 7: Run all Python and Node tests**

Run: `FORCE_COLOR= uv run pytest --color=no` and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/`
Expected: all pass.

- [ ] **Step 8: Browser check of all 4 pages** at 393×852 and 1440×900, in light and dark (16 views).

- Pipeline on the phone: the chips switch stages with no reload, and the page opens on Drafted (or Sent when a follow-up is due).
- Pipeline on the Mac: the columns scroll sideways, and the Move menu works.
- On every view, `document.documentElement.scrollWidth === innerWidth`.
- No console errors.

- [ ] **Step 9: Commit and push**

The message lists the test changes.

```bash
git add -A src tests
git commit -m "feat(ui): Pipeline as Kanban on Mac and stage chips on phone; remove legacy app.css/mobile.css

Test changes: test_base_has_phone_meta_and_toast checks ui.css; removed test_mobile_css_contract
(→ test_ui_css_contract) and test_pipeline_columns_are_collapsible (→ test_pipeline_columns_chips_and_default_stage);
fingerprint test lists ui.css and tabs.js."
git push
launchctl kickstart -k gui/$(id -u)/com.kshitij.jobseeker.uipreview
```

---

### Task 9: Final review pass and hand-off

**Files:**
- Modify: `HANDOFF.md` (in the worktree: add a "UI redesign branch" section)

- [ ] **Step 1: Run the full suites**

Run: `FORCE_COLOR= uv run pytest --color=no` and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/`
Expected: all pass. Record the counts.

- [ ] **Step 2: Walk the Review Focus list in the browser** on `https://delulu.tail1c97dd.ts.net:8443`, with real data:
- open a job with no score (or check `test_job_page_without_score_or_step_still_renders`);
- open a skipped or snoozed job (the step bar is hidden);
- the job with the longest title at 393px;
- tab switching after boosted navigation;
- dark mode on all 4 pages.

Fix anything found with a test first, then commit.

- [ ] **Step 3: Confirm `main` is untouched**

```bash
git -C "/Users/user/Desktop/untitled folder/job-seeker2.0" branch --show-current   # main
git -C "/Users/user/Desktop/untitled folder/job-seeker2.0" log --oneline -1          # unchanged main tip
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/today                # 200, old UI
```

- [ ] **Step 4: Update HANDOFF.md (worktree copy) and commit**

Add a section "UI redesign (branch `ui-redesign`, not merged)" covering:
- the preview URL `https://delulu.tail1c97dd.ts.net:8443`;
- the worktree path;
- how to merge (`git switch main && git merge ui-redesign`, then restart `com.kshitij.jobseeker.web`, then `scripts/preview_ui.sh remove`, then `git worktree remove`);
- how to abandon (`scripts/preview_ui.sh remove`, `git worktree remove`, `git branch -D ui-redesign`, `git push origin --delete ui-redesign`).

```bash
git add HANDOFF.md && git commit -m "docs: how to preview, merge or abandon the ui-redesign branch" && git push
```
