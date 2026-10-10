# P0 review fixes (PM review 2026-10-10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, the user's standing choice) to implement this plan task-by-task, with superpowers:test-driven-development per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the P0 batch from the PM review (PM-071, PM-015/068, PM-063 gaps, PM-001, PM-002, PM-011, PM-016, PM-028) so a newly invited user gets scored matches on their first day and the UI tells the truth after every action.

**Architecture:** Scoring keeps its round robin but reserves a first-scores floor for eligible users who haven't scored today; onboarding's Finish queues a no-fetch "onboarding" run request (migration v6 adds `run_requests.trigger`). The web gets one labelled "Job search" status block (inside the existing `_fetch_now.html` fragment, so every `_fetch_now_slot.html` include keeps working), a "score pending" list, a first-run empty state, and two small client fixes (HTMX response handling + an error toast; `HX-Refresh` when a poll finishes).

**Tech Stack:** Python 3.13, FastAPI, Jinja2, SQLite, HTMX 2.0.4, pytest, `node --test`.

**Spec:** `docs/reviews/2026-10-10-pm-review.md` on `origin/review/pm-2026-10-10` (§3 entries PM-001, 002, 011, 015, 016, 028, 063, 068, 071), plus devops-lead2's PM-071 design as relayed by `manager` (recorded verbatim in `HANDOFF-backend.md` §2 NEXT, commit `7d32b46`).

## Global Constraints

- Work only in `/Users/user/Desktop/untitled folder/js-mu-backend`, branch `multi-user`; every shell command starts with `cd "/Users/user/Desktop/untitled folder/js-mu-backend" && …`. Never touch the main checkout or its `data/`.
- Every task commit also updates `HANDOFF-backend.md` §2 (table row + NEXT line) and §3 (rulings), then `git push origin multi-user` (never force, never `main`). One line to `manager` per task: task, commit, pytest/node counts.
- pytest: `FORCE_COLOR= uv run pytest --color=no -p no:warnings` (baseline **884**). node: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs` (baseline **26**), grep with `grep -aE "(pass|fail) [0-9]+"`.
- Keep: the `_fetch_now_slot.html` includes (`today.html`, `settings.html`, `onboarding/done.html`), `include_router(fetch_now.router, …)` in `app.py`, the alerts card, and `delete_account`'s order (usage → tombstone first; then others → private contacts → runs).
- `config/app.yaml` is git-ignored and only written when missing, so **changes to `config/app.example.yaml` don't reach the live server**. Every such change gets an ops line in the final task's cutover notes.
- Copy uses the app's voice: short, plain, no "Oops". Times are IST `HH:MM` (`clock.app_now`).
- The admin must never see a user's pay (PM-016).

## Review Focus

1. **The status fragment's first load is an HTMX GET with a finished state.** The `HX-Refresh` on "poll finished" must fire only for a request that came from a *polling* element (`?poll=1`), never for the slot's `hx-trigger="load"`, or Today reloads forever. Test in Task 6.
2. **A user who is already queued (a Fetch now) presses Finish** (or a stale tab posts Finish twice). The one-pending-per-user unique index raises `IntegrityError`; Finish must still redirect to `/onboarding/done`, not 500. Test in Task 1.
3. **The reservation must not strand the in-run users when every other user already scored today** (reserved = 0) or when the run includes every eligible user. Existing round-robin numbers must be unchanged in those cases. Test in Task 2.
4. **A 4xx swap of a boosted page that isn't a full page** (CSRF's plain-text 403 "Request blocked", a 404) must not replace the body with bare text; those become a toast. Test in Task 8 (config content) and node test of the message map.
5. **Deleting the account lands on a public page after the session cookie is gone**; the page must render signed out (no nav, no `request.state.user`). Test in Task 10.

---

## File map

| File | Change |
|---|---|
| `src/jobseeker/db/migrations.py`, `db/schema.sql` | v6: `run_requests.trigger` |
| `src/jobseeker/db/run_requests.py` | `queue(…, trigger=)`, fetch-now-only counts |
| `src/jobseeker/pipeline/tick.py`, `cli.py` | run the request's trigger; onboarding = no fetch; run id for no-fetch runs |
| `src/jobseeker/pipeline/run.py` | `RunReport.user_runs`; push for user-requested runs |
| `src/jobseeker/pipeline/score.py` | floor, reservation pool, zero-usage-first order |
| `src/jobseeker/push/notify.py` | `notify_run_finished` |
| `src/jobseeker/db/usage.py` | `used_today(conn, uid, service, now)` |
| `src/jobseeker/web/filters.py`, `web/deps.py` | notes use the day's usage; "reserved" note |
| `src/jobseeker/web/onboarding.py`, `templates/onboarding/*` | Finish queues; done copy; poll refresh |
| `src/jobseeker/db/queries.py`, `web/inbox.py`, `templates/inbox.html`, `templates/today.html`, `web/view.py` | score pending, first-run empty state |
| `src/jobseeker/web/fetch_now.py`, `templates/_fetch_now.html`, `templates/settings.html` | "Job search" block |
| `templates/base.html`, `static/errors.js`, `static/ui.css`, `tests/js/errors.test.mjs` | PM-001 |
| `web/contacts.py`, `templates/_people.html`, `templates/_resume_status.html`, `web/settings.py` | PM-002 |
| `web/settings.py`, `web/app.py`, `templates/settings_delete.html`, `templates/account_deleted.html` | PM-011 |
| `templates/admin_user.html`, `templates/admin.html` | PM-016, tombstone label |
| `config/app.example.yaml` | PM-028 |

---

### Task 1: Migration v6 and the onboarding run request (PM-071 part 2)

**Files:**
- Modify: `src/jobseeker/db/migrations.py` (append v6), `src/jobseeker/db/schema.sql:262-269`
- Modify: `src/jobseeker/db/run_requests.py`, `src/jobseeker/pipeline/tick.py`, `src/jobseeker/pipeline/run.py`, `src/jobseeker/cli.py:57-71`, `src/jobseeker/web/onboarding.py:244-256`
- Test: `tests/test_migration_v4.py::test_fresh_shape` (update), new `tests/test_onboarding_run.py`, `tests/test_tick.py` (add)

**Interfaces:**
- Produces: `run_requests.queue(conn, user_id, now, trigger="fetch_now") -> int`; column `run_requests.trigger TEXT NOT NULL DEFAULT 'fetch_now' CHECK (trigger IN ('fetch_now','onboarding'))`; `RunReport.user_runs: dict[int, int]`; tick passes `req["trigger"]` as the run's trigger; the CLI runner never fetches for trigger `"onboarding"`.
- Consumes: existing `tick(conn, *, settings, cfg, now, run, …)` and `run(trigger, users, plan_cap)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_migration_v4.py::test_fresh_shape`: expect `{"id", "user_id", "requested_at", "status", "run_id", "finished_at", "trigger"}`.

`tests/test_onboarding_run.py`:

```python
from datetime import UTC, datetime, timedelta

from jobseeker.config import AppConfig
from jobseeker.db import run_requests
from jobseeker.db.core import connect
from jobseeker.db.migrations import MIGRATIONS, latest
from jobseeker.db.runs import start_run
from jobseeker.pipeline.tick import tick
from jobseeker.web.fetch_now import fetch_now_state

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)  # 09:30 IST: before the 11:15 schedule, so tick serves the queue


def test_v6_registered_and_old_rows_default_to_fetch_now(tmp_path):
    assert [m.name for m in MIGRATIONS if m.version == 6] == ["run request trigger"] and latest() >= 6
    conn = connect(tmp_path / "f.db")
    rid = run_requests.queue(conn, 1, NOW)
    assert conn.execute("SELECT trigger FROM run_requests WHERE id = ?", (rid,)).fetchone()[0] == "fetch_now"


def test_onboarding_request_is_exempt_from_cap_and_spacing(settings):
    conn = connect(settings.db_path)
    cfg = AppConfig()
    for i in range(cfg.fetch_now.max_per_day):  # the day's Fetch now cap is used up
        start_run(conn, NOW - timedelta(minutes=i), None, kind="fetch", trigger="fetch_now")
    run_requests.queue(conn, 1, NOW, trigger="onboarding")
    seen = []
    out = tick(conn, settings=settings, cfg=cfg, now=NOW, holder="t:1",
               run=lambda trigger, users, cap: seen.append((trigger, [u.id for u in users])) or _Report())
    assert out == "fetch_now" and seen == [("onboarding", [1])]
    assert run_requests.fetch_now_count_today(conn, NOW) == cfg.fetch_now.max_per_day  # not counted


def test_queued_onboarding_request_does_not_count_toward_others_cap(settings):
    conn = connect(settings.db_path)
    run_requests.queue(conn, 1, NOW, trigger="onboarding")
    assert run_requests.fetch_now_count_today(conn, NOW) == 0


def test_onboarding_run_does_not_start_fetch_now_spacing(settings):
    conn = connect(settings.db_path)
    start_run(conn, NOW - timedelta(minutes=5), 1, kind="user", trigger="onboarding")
    assert fetch_now_state(conn, 1, NOW, AppConfig())["state"] == "ready"


class _Report:
    aborted = None
    fetch_run_id = None
    user_runs: dict = {}
```

In `tests/test_onboarding.py` (reuse `_to_resume_step` and `save_facts`):

```python
def test_finish_queues_an_onboarding_run(newbie, client_as, settings, facts):
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    conn = connect(settings.db_path)
    save_facts(conn, newbie, facts)
    assert web.post("/onboarding/finish").headers["location"] == "/onboarding/done"
    row = conn.execute("SELECT trigger, status FROM run_requests WHERE user_id = ?", (newbie,)).fetchone()
    assert tuple(row) == ("onboarding", "queued")


def test_finish_while_already_queued_still_finishes(newbie, client_as, settings, facts):
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    conn = connect(settings.db_path)
    save_facts(conn, newbie, facts)
    run_requests.queue(conn, newbie, datetime.now(UTC))  # e.g. a stale tab's Fetch now
    assert web.post("/onboarding/finish").headers["location"] == "/onboarding/done"
    assert conn.execute("SELECT COUNT(*) FROM run_requests WHERE user_id = ?", (newbie,)).fetchone()[0] == 1
```

In `tests/test_cli_run.py` (or wherever `_runner` is tested): `_runner(...)` with `fetch=True` passes `fetch=False` to `run_all` when `trigger == "onboarding"` (monkeypatch `jobseeker.pipeline.run.run_all` and `jobseeker.cli._pipeline` to capture kwargs).

In `tests/test_tick.py`: an onboarding request's `run_id` is the user's run (`report.user_runs[uid]`) when `fetch_run_id` is None.

- [ ] **Step 2: Run them; expect FAIL** (`queue() got an unexpected keyword argument 'trigger'`, missing column).

Run: `FORCE_COLOR= uv run pytest --color=no -p no:warnings tests/test_onboarding_run.py tests/test_onboarding.py tests/test_migration_v4.py tests/test_tick.py`

- [ ] **Step 3: Implement**

`migrations.py`:

```python
def migrate_v6(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    """Onboarding's first scoring run is a run request too: 'onboarding' requests skip the fetch and are exempt from
    Fetch now's spacing and daily cap."""
    conn.execute("ALTER TABLE run_requests ADD COLUMN trigger TEXT NOT NULL DEFAULT 'fetch_now' "
                 "CHECK (trigger IN ('fetch_now', 'onboarding'))")


MIGRATIONS.append(Migration(6, "run request trigger", migrate_v6))
```

`schema.sql` `run_requests`: add `trigger TEXT NOT NULL DEFAULT 'fetch_now' CHECK (trigger IN ('fetch_now', 'onboarding'))` after `finished_at`.

`run_requests.py`:

```python
def queue(conn, user_id: int, now: datetime, trigger: str = "fetch_now") -> int:
    cur = conn.execute("INSERT INTO run_requests (user_id, requested_at, status, trigger) VALUES (?, ?, 'queued', ?)",
                       (user_id, iso(now), trigger))
    conn.commit()
    return cur.lastrowid
```

and in `fetch_now_count_today` the queued count becomes `… WHERE status = 'queued' AND trigger = 'fetch_now'`. (`last_fetch_now_started` already reads `runs.trigger = 'fetch_now'`, and the onboarding run is started with trigger `onboarding`.)

`run.py`: `RunReport` gains `user_runs: dict[int, int] = field(default_factory=dict)`; set `report.user_runs = user_runs` right after the `start_run` loop (same dict object, so assign `user_runs = report.user_runs` at the top instead of a local `{}`).

`tick.py`, the request branch:

```python
        req = run_requests.next_queued(conn)
        if req:
            trigger = req.get("trigger") or "fetch_now"
            if trigger == "fetch_now" and \
                    run_requests.fetch_now_count_today(conn, now, include_queued=False) >= cfg.fetch_now.max_per_day:
                run_requests.mark(conn, req["id"], "failed", now)
                return "fetch_now_refused"
            run_requests.mark(conn, req["id"], "running", now)
            user = user_by_id(conn, req["user_id"])
            try:
                report = run(trigger, [user], cfg.search.max_searches_fetch_now)
            except SystemExit:
                kind = "fetch" if trigger == "fetch_now" else "user"
                rid = conn.execute("SELECT MAX(id) FROM runs WHERE kind = ? AND trigger = ? AND started_at >= ?",
                                   (kind, trigger, iso(now))).fetchone()[0]
                run_requests.mark(conn, req["id"], "failed", now, rid)
                raise
            run_id = report.fetch_run_id or report.user_runs.get(user.id)
            run_requests.mark(conn, req["id"], "failed" if report.aborted else "done", now, run_id)
            return "fetch_now"
```

(`interrupted_since` joins `runs` by `run_id` and reads `errors`; the user run's errors carry `INTERRUPTED` too, so it keeps working for onboarding requests.)

`cli.py` `_runner.run`: `fetch=fetch and trigger != "onboarding"`.

`onboarding.py` `finish`, after `set_onboarding(...)`:

```python
    try:
        run_requests.queue(conn, user.id, now, trigger="onboarding")
    except sqlite3.IntegrityError:  # already queued or running (a Fetch now from another tab): that run scores them
        conn.rollback()
```

- [ ] **Step 4: Run the task's tests, then the full suite; expect PASS** (884 + new).
- [ ] **Step 5: Live-copy check of v6** — `sqlite3 "/Users/user/Desktop/untitled folder/job-seeker2.0/data/jobseeker.db" ".backup /tmp/jsmig/data/jobseeker.db"`, then `JOBSEEKER_HOME=/tmp/jsmig OWNER_EMAIL=mkshitij1763@gmail.com uv run jobseeker migrate`: v5→v6 clean, `PRAGMA foreign_key_check` empty, counts unchanged. Delete the copy.
- [ ] **Step 6: Commit** `feat(pipeline): onboarding Finish queues a no-fetch first-scores run (v6 run_requests.trigger)`, handoff update, push, report.

---

### Task 2: Reserve a first-scores floor in the shared score cap (PM-071 part 1)

**Files:**
- Modify: `src/jobseeker/pipeline/score.py:47-56` (`_prepare`) and the loop in `score_round_robin`
- Test: `tests/test_score_round_robin.py` (add)

**Interfaces:**
- Consumes: `pipeline.eligible.active_users(conn)`, `Budget.used/used_all`.
- Produces: `Scorer.stats.stopped_by == "reserved"` when the run hit the reservation; `score_round_robin` may return `"reserved"`. `UserStats` unchanged otherwise.

Design (devops-lead2's, verbatim intent): `floor = min(score_per_run, share)`; `reserved = floor × |{eligible users not in this run whose score usage today is 0}|`; this run may spend at most `pool = max(0, global_left − reserved)` where `global_left = global_scores_per_day − used_all("score")`. **Ruling to confirm with manager:** the design says "each user's room = min(room, global_left − reserved)"; applied per user, two in-run users could together eat into the reserve, so `pool` is one counter for the whole run (each user's room is still capped by it). Users with 0 usage today go first in the round robin (stable sort).

- [ ] **Step 1: Write the failing tests**

```python
def _onboard(conn, users):
    for u in users:
        conn.execute("""INSERT OR REPLACE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at,
                        updated_at) VALUES (?, '{}', 1, NULL, 't', 't')""", (u,))
    conn.commit()


def _use(conn, uid, amount):
    from jobseeker.clock import app_now
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (?, ?, 'score', ?)",
                 (uid, app_now(NOW).strftime("%Y-%m-%d"), amount))
    conn.commit()


def test_run_leaves_a_floor_for_users_who_have_not_scored_today(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2, 3, 4), jobs_per_user=40)
    _onboard(conn, (1, 2, 3))
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (9, 'deleted-9@invalid', 't')")
    _use(conn, 9, 10)  # a tombstone's spend still counts: 20 of 30 left
    scorers = _scorers(prefs, facts, users=(1,))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30), NOW)
    # share 10, floor 10, reserved 10 x 2 (users 2 and 3) = 20, pool 0
    assert scorers[0].stats.scored == 0 and scorers[0].stats.stopped_by == "reserved"


def test_no_reservation_once_the_others_have_scored(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, jobs_per_user=40)
    _onboard(conn, (1, 2, 3))
    _use(conn, 2, 1)
    _use(conn, 3, 1)
    scorers = _scorers(prefs, facts, users=(1,))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30), NOW)
    assert scorers[0].stats.scored == 10  # its share, as before


def test_pool_is_shared_by_the_users_in_the_run(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2, 3), jobs_per_user=40)
    _onboard(conn, (1, 2, 3))
    scorers = _scorers(prefs, facts, users=(1, 2))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30, batch=5), NOW)
    # share 10 each; user 3 reserved 10; pool 20: both get their 10, user 3's 10 untouched
    assert [s.stats.scored for s in scorers] == [10, 10]
    from jobseeker.db.usage import Budget, Limit
    b = Budget(conn, 3, {"score": Limit("day", 30, 10)}, app_now(NOW))
    assert 30 - b.used_all("score") == 10


def test_users_with_no_scores_today_go_first(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2), jobs_per_user=12)
    _use(conn, 1, 1)
    order = []
    import jobseeker.pipeline.score as score_mod
    real = score_mod.save_score
    score_mod.save_score = lambda c, uid, *a, **k: order.append(uid) or real(c, uid, *a, **k)
    try:
        score_round_robin(conn, _scorers(prefs, facts, users=(1, 2)), FakeLLM(handler=lambda s, p: SCORE), rubric,
                          _cfg(global_scores=30), NOW)
    finally:
        score_mod.save_score = real
    assert order[0] == 2
```

(`app_now` import at the top of the test module; the existing tests keep their users un-onboarded, so `eligible_count` is 0, reserved is 0 and their numbers stay the same — Review Focus 3.)

- [ ] **Step 2: Run; expect FAIL** (scored 10 / stopped_by "share"; order[0] == 1).
- [ ] **Step 3: Implement**

```python
def _reserved(conn, scorers: list[Scorer], floor: int, today_used) -> int:
    in_run = {s.user_id for s in scorers}
    waiting = [u for u in active_users(conn) if u.id not in in_run and today_used(u.id) == 0]
    return floor * len(waiting)


def _prepare(conn, scorers: list[Scorer], cfg, now: datetime) -> int:
    """Rooms per user, and the run's pool: what's left of the global cap after holding a first-scores floor for every
    eligible user outside this run who hasn't scored today (a new user's first run must never find it spent)."""
    b = cfg.budgets
    share = b.global_scores_per_day // share_divisor(conn, "score", len(scorers))
    for s in scorers:
        s.budget = Budget(conn, s.user_id, {"score": Limit("day", b.global_scores_per_day, share)}, app_now(now))
        left = max(0, share - int(s.budget.used("score")))
        s.room = min(b.score_per_run, left)
        s.cap_reason = "run_cap" if b.score_per_run < left else "share"
        s.stats.score_share_left = left
    if not scorers:
        return 0
    probe = scorers[0].budget
    used = lambda uid: Budget(conn, uid, probe.limits, app_now(now)).used("score")  # noqa: E731
    scorers.sort(key=lambda s: s.budget.used("score") > 0)  # stable: zero-usage users first
    reserved = _reserved(conn, scorers, min(b.score_per_run, share), used)
    return max(0, int(b.global_scores_per_day - probe.used_all("score")) - reserved)
```

In `score_round_robin`: `pool = _prepare(...)`; before `s.budget.take("score")`, `if pool <= 0: stop = "reserved"; s.stats.stopped_by = "reserved"; break`; after a successful score `pool -= 1`; after a refund nothing (the take was refunded). When `stop == "reserved"` the final loop already copies it into every unfinished scorer. Import `active_users` from `jobseeker.pipeline.eligible`. Note `scorers.sort` mutates the caller's list: `run_all` only uses it for the call, fine; say so in a comment.

`run_all`'s draft gate is unchanged (`"reserved"` isn't `unavailable`/`quota`).

- [ ] **Step 4: Full suite PASS.**
- [ ] **Step 5: Commit** `feat(score): hold a first-scores floor for users who haven't scored today; zero-usage users first`, handoff, push, report (flag the pool ruling to `manager`).

---

### Task 3: Notes use the day's usage; "reserved" note; tombstone on the admin Usage card (PM-071 parts 3–4)

**Files:**
- Modify: `src/jobseeker/db/usage.py`, `src/jobseeker/web/filters.py:29-44`, `src/jobseeker/web/deps.py:30-37`, `src/jobseeker/web/templates/admin.html:55-57`
- Test: `tests/test_run_notes.py`, `tests/test_admin.py` (add)

**Interfaces:**
- Produces: `usage.used_today(conn, user_id, service, now) -> float` (IST day period); `explain_stats(stats, scored_today: int | None = None)`.

- [ ] **Step 1: Failing tests**

```python
def test_share_note_counts_the_whole_day():
    notes = explain_stats({"user": {"stopped_by": "share", "scored": 0}, "fetch": {}}, scored_today=75)
    assert notes[0]["text"] == "You've used today's 75 scores; more tomorrow"


def test_reserved_note():
    notes = explain_stats({"user": {"stopped_by": "reserved", "scored": 0}, "fetch": {}}, scored_today=0)
    assert notes[0]["text"] == ("Today's shared AI allowance is held for other users' first scores; "
                                "yours resume tomorrow")


def test_used_today_reads_the_ist_day(settings):
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO usage (user_id, period, service, amount) VALUES (1, '2026-10-11', 'score', 7)")
    assert used_today(conn, 1, "score", datetime(2026, 10, 10, 19, 0, tzinfo=UTC)) == 7  # 00:30 IST on the 11th
```

`tests/test_admin.py`: delete user 2 via `delete_account` after giving them a `score` usage row today; `/admin` shows a row "Deleted account" with that amount (and the Users card still doesn't list them).

- [ ] **Step 2: FAIL.**
- [ ] **Step 3: Implement.** `used_today` = `SELECT COALESCE(SUM(amount),0) FROM usage WHERE user_id=? AND period=? AND service=?` with `app_now(now).strftime("%Y-%m-%d")`. `explain_stats`: `n = scored_today if scored_today is not None else user.get("scored", 0)` in the share note; new branch `elif why == "reserved": …`. `deps.render`: `explain_stats(stats, int(used_today(conn, user.id, "score", datetime.now(UTC))))`. `admin.html`: `<td>{{ "Deleted account" if r.user.email.startswith("deleted-") and r.user.email.endswith("@invalid") else r.user.email }}</td>` — better, pass `is_tombstone` as a template global or precompute `r.label` in `usage_table` (`"Deleted account (" ~ id ~ ")"`). Use the latter: `usage_table` adds `"label"`.
- [ ] **Step 4: PASS. Step 5: Commit** `fix(notes): share note counts the day's scores; reserved note; tombstones labelled on Usage`.

---

### Task 4: "Score pending" and a first-run empty state (PM-071/015)

**Files:**
- Modify: `src/jobseeker/db/queries.py` (new `pending_scores`), `src/jobseeker/web/inbox.py`, `templates/inbox.html`, `src/jobseeker/web/view.py` or the Today route, `templates/today.html`
- Test: `tests/test_inbox_pending.py` (new), `tests/test_today_first_run.py` (new)

Test imports: `from datetime import UTC, datetime`; `from jobseeker.config import UserPrefs` (wherever conftest imports it from); `from jobseeker.db import queries`; `from jobseeker.db.core import connect`; `from jobseeker.db.jobs import set_verdict, upsert_job`; `from tests.factories import make_job`; `NOW = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)`.

**Interfaces:**
- Produces: `queries.pending_scores(conn, user_id, limit=20) -> {"count": int, "rows": list[dict(job_id, title, company, apply_url, prescore)]}` — `user_jobs.filter_reason IS NULL` with no `scores` row for that user and job, by `prescore DESC, first_seen_at DESC`; `queries.has_any_score(conn, user_id) -> bool`.

- [ ] **Step 1: Failing tests**

```python
def test_pending_lists_unscored_matches_by_prescore(settings):
    conn = connect(settings.db_path)
    a, _ = upsert_job(conn, make_job(source_job_id="p1", fingerprint="p1", title="Product Analyst"), NOW)
    b, _ = upsert_job(conn, make_job(source_job_id="p2", fingerprint="p2", title="APM"), NOW)
    set_verdict(conn, 2, a, None, 40, "h", NOW)
    set_verdict(conn, 2, b, None, 70, "h", NOW)
    conn.commit()
    p = queries.pending_scores(conn, 2)
    assert p["count"] == 2 and [r["title"] for r in p["rows"]] == ["APM", "Product Analyst"]


def _pending_job(settings, uid, n=1):
    conn = connect(settings.db_path)
    for i in range(n):
        j, _ = upsert_job(conn, make_job(source_job_id=f"q{i}", fingerprint=f"q{i}", title=f"Product Analyst {i}"), NOW)
        set_verdict(conn, uid, j, None, 50, "h", NOW)
    conn.commit()


def test_review_band_shows_score_pending(seeded_two, client_as, settings):
    _pending_job(settings, 2)
    page = client_as(2).get("/?band=review").text
    assert "Score pending" in page and "1 match is waiting for a score" in page


def test_today_first_run_is_not_all_caught_up(client_as, settings):
    conn = connect(settings.db_path)  # user 3: onboarded, never scored (seeded_two's user 2 already has a score)
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (3, 'new@example.com', 'New', 't')")
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (3, ?, 1, NULL, 't', 't')""", (UserPrefs(roles=["Product Analyst"], cities=["Pune"]).model_dump_json(),))
    conn.commit()
    _pending_job(settings, 3, 3)
    page = client_as(3).get("/today").text
    assert "All caught up" not in page and "Your first matches are on the way" in page
```

- [ ] **Step 2: FAIL. Step 3: Implement.**
  - Inbox: when `band in ("review", "all")` or the list is empty, render a `pending` card above the list: heading "Score pending", "{n} match(es) is/are waiting for a score", then up to 20 rows `title · company` linking to `apply_url` (`target="_blank" rel="noopener"`, `hx-boost="false"`) with a `pill` "score pending". The empty-row text becomes "No scored jobs here yet." when `pending.count` > 0 (keeps the old text otherwise).
  - Today: pass `first_run = not has_any_score(conn, uid)` and `pending = pending_scores(conn, uid, 0)["count"]`. Both "All caught up" cards get a first-run branch: `<h2>Your first matches are on the way</h2><p>{{ pending }} jobs match your filters; scores arrive with your first search (see Job search above).</p>`.
- [ ] **Step 4: PASS. Step 5: Commit** `feat(jobs): unscored matches show as score pending; Today has a first-run state`.

---

### Task 5: Push when a requested run finishes (PM-068)

**Files:**
- Modify: `src/jobseeker/push/notify.py`, `src/jobseeker/pipeline/run.py:115-123`
- Test: `tests/test_push_notify.py`, `tests/test_run_all.py` (add)

**Interfaces:**
- Produces: `notify_run_finished(conn, user_id, run_started_at, now, *, scored, starved, keys=..., client=None) -> str | None` (same return contract as `notify_new_matches`: `None` or `RUN_NOTE`); `_deliver(conn, user_id, payload, now, keys, client) -> int` (delivered count) shared by both.
- `run_all`: trigger `"schedule"` → `notify_new_matches` (unchanged, once a day); `"fetch_now"`/`"onboarding"` → `notify_run_finished` (every time, still respects `notify_new_matches` pref and needs a subscription). Its `notify` parameter stays the injection point: rename default to `_default_notify(conn, uid, started, now, trigger, stats)`; update the test fakes that pass `notify=`.

Payloads: title `"Your search finished"`; body `"{n} new match(es) · top {top}"` if new apply matches, else `"Scored {scored} jobs; nothing to apply to yet"`, else (scored 0 and starved) `"Scores wait for tomorrow's AI allowance"`; url `/today`.

- [ ] **Step 1: Failing tests** — a fake `client` records posts: a fetch_now run with 0 matches still sends one push with "Scored 3 jobs"; the daily `notified_on` gate does not block it; a user with `notify_new_matches=False` gets none.
- [ ] **Step 2: FAIL. Step 3: Implement** (extract the subscription loop into `_deliver`, unchanged behaviour). **Step 4: PASS. Step 5: Commit** `feat(push): tell the user when their Fetch now or first run finishes`.

---

### Task 6: One labelled "Job search" status block (PM-015/068/063)

**Files:**
- Modify: `src/jobseeker/web/fetch_now.py`, `templates/_fetch_now.html`, `templates/settings.html` (move the include to the top, in its own card), `templates/onboarding/_done_status.html`
- Test: `tests/test_web_fetch_now.py` (update + add)

**Interfaces:**
- Produces: `fetch_now_state(conn, user_id, now, cfg) -> dict` keeps `state`/`text`/`poll` (tests and the POST use them) and gains `label` (always "Job search"), `detail` (second line), `kind` (`"fetch_now"|"onboarding"|None`). `GET /fetch-now/status?poll=1` from the polling element; when `poll=1` and the new state isn't `queued`/`running`, the response carries `HX-Refresh: true` (Review Focus 1).

Copy (one message per state; refusals are neutral):

| State | `text` | `detail` |
|---|---|---|
| queued, run lock held | "Waiting for another search to finish" | "Usually 30–60 min. " + ("We'll notify you." if the user has a push subscription else "Today updates when it's done.") |
| queued, idle | "Starts within 5 minutes" | same tail |
| queued/running onboarding | "Scoring your first matches" | "Usually under 15 min." |
| running | "Searching since HH:MM" (`held_since(conn, "run")`, IST) | "Usually 30–60 min. You can leave this page." |
| wait/used_up/ready after a run | unchanged (`Next possible at …` / used up / button) | last run line from `header_run`: "Your HH:MM search scored N jobs (M to apply)."; if `stopped_by` in `global_cap/quota/reserved` and `pending_scores(...)["count"]`: "Scoring is paused until tomorrow's AI allowance; the daily run is at {daily_at}."; if the last request was interrupted: `INTERRUPTED` (PM-063's gap) |

The POST's flash becomes the same `text` (no more "starts in a few minutes" vs "after the current run" mismatch).

- [ ] **Step 1: Failing tests** — update `test_queued_while_locked_says_after_current_run` to expect "Waiting for another search to finish"; add: a finished poll (`/fetch-now/status?poll=1` with no pending request) has `HX-Refresh: true`; the same GET without `poll=1` hasn't; Today and Settings show "Job search"; after a user run with `stopped_by="quota"` and a pending match, the detail says "Scoring is paused until tomorrow's AI allowance"; a queued onboarding request shows "Scoring your first matches".
- [ ] **Step 2: FAIL. Step 3: Implement** (`_fetch_now.html` polls `hx-get="/fetch-now/status?poll=1"` only while `poll`; the outer element keeps `id="fetch-now"` and `class="fetch-now"`; add `<b class="job-search-label">Job search</b>` and a `<p class="muted">{{ detail }}</p>`). `done.html`'s copy "Your first scores arrive with the next run." → "We're scoring your top matches now; Today shows the progress." **Step 4: PASS. Step 5: Commit** `feat(web): one labelled Job search status with honest queued/running copy`.

---

### Task 7: Refresh the page when a poll finishes (PM-002)

**Files:**
- Modify: `templates/_resume_status.html:3`, `templates/_people.html:2` (hx-get gains `?poll=1`), `web/onboarding.py:208-211`, `web/settings.py` `resume_status`, `web/contacts.py:58-65`
- Test: `tests/test_onboarding.py`, `tests/test_settings.py`, the contacts web test file (add)

**Interfaces:** a small helper in `web/deps.py`: `def refresh_if_poll_done(request, response, done: bool)` sets `response.headers["HX-Refresh"] = "true"` when `request.query_params.get("poll") == "1" and done`.

- [ ] **Step 1: Failing tests** — onboarding: with facts saved and `extract_status='done'`, `GET /onboarding/resume/status?poll=1` has `HX-Refresh: true`; without `poll=1` it hasn't; while `running` it hasn't. Same for `/settings/resume/status`. Contacts: `GET /applications/{id}/contacts/card?poll=1` with find state not running → `HX-Refresh: true`.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS. Step 5: Commit** `fix(web): reload the page when a resume read or contact search finishes`.

---

### Task 8: 4xx swaps and an error toast (PM-001)

**Files:**
- Modify: `templates/base.html` (head), `static/ui.css` (reuse `.toast`, add `.toast.err`)
- Create: `static/errors.js`, `tests/js/errors.test.mjs`
- Test: `tests/test_web_view.py` (add)

**Interfaces:** `errors.js` exports `errorMessage(status: number, body: string) -> string` (node-testable via the `module.exports` pattern of `tabs.js`) and, in the browser, listens to `htmx:responseError` and `htmx:sendError` and shows a toast for 4 s.

`base.html` head, before the htmx script:

```html
<meta name="htmx-config" content='{"responseHandling":[{"code":"204","swap":false},{"code":"[23]..","swap":true},{"code":"40[34]","swap":false,"error":true},{"code":"4..","swap":true,"error":false},{"code":"...","swap":false,"error":true}]}'>
<script src="{{ asset('errors.js') }}" defer></script>
```

So 422 validation pages (full pages from `_page`/`_render`) swap in like a 200, while CSRF's plain-text 403, 404s, 5xx and network errors toast instead of replacing the body (Review Focus 4).

`errorMessage`: 403 with body "Request blocked" → "That didn't go through. Reload the page and try again."; 404 → "That's no longer here. Reload the page."; 0/network → "You're offline or the app is restarting. Try again in a minute."; 5xx → "Something went wrong on our side. Try again in a minute.".

- [ ] **Step 1: Failing tests** — node: the four mappings; pytest: `/today` HTML contains the `htmx-config` meta with `"4.."` and `errors.js`.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS (node 26 → 30). Step 5: Manual check** on a local server (`uv run jobseeker serve` against a scratch home): Settings → Replace resume with a non-PDF shows the error in place; Delete with a wrong email (after Task 10 this page isn't boosted, so check a prefs validation error instead). **Step 6: Commit** `fix(web): show validation errors on boosted pages; toast server and network errors`.

---

### Task 9: Admin user view without pay (PM-016)

**Files:** Modify `templates/admin_user.html:32-33`; Test `tests/test_admin_user_view.py`.

- [ ] **Step 1: Failing test** — give user 2 `current_ctc_lpa=18, target_base_lpa=24`; `client_as(1).get("/admin/users/2").text` contains neither "LPA" nor "Pay" nor "18".
- [ ] **Step 2: FAIL. Step 3: delete the two `Pay` lines** (and `ctc` from `user_overview` if it's passed separately). **Step 4: PASS. Step 5: Commit** `fix(admin): the user view never shows pay`.

---

### Task 10: Delete lands on a public "account deleted" page (PM-011)

**Files:**
- Modify: `templates/settings_delete.html` (form `hx-boost="false"`), `web/settings.py:163-174` (redirect `/account-deleted`), `web/app.py` (`PUBLIC` += `"/account-deleted"`, route on `auth.router` or a tiny public router)
- Create: `templates/account_deleted.html` (extends `bare.html`)
- Test: `tests/test_account.py` (add), `tests/test_web_guards.py` (passes via `PUBLIC`)

- [ ] **Step 1: Failing tests**

```python
def test_delete_lands_on_public_deleted_page(seeded_two, client_as):
    web = client_as(2, follow_redirects=False)
    r = web.post("/settings/delete", data={"email": "roomie@example.com"})
    assert r.status_code == 303 and r.headers["location"] == "/account-deleted"
    page = web.get("/account-deleted")
    assert page.status_code == 200 and "Your account is deleted" in page.text
    assert "backups expire in 4 weeks" in page.text


def test_delete_form_is_not_boosted(client_as):
    assert 'hx-boost="false"' in client_as(1).get("/settings/delete").text
```

- [ ] **Step 2: FAIL. Step 3: Implement.** Page copy: `<h1>Your account is deleted.</h1><p>Your data is gone; backups expire in 4 weeks.</p><a class="btn" href="/">Back to the start</a>`. Rendered with `render_public` (no user). **Step 4: PASS. Step 5: Commit** `fix(account): delete is a plain form that lands on an "account deleted" page`.

---

### Task 11: Seniority exclusions and tighter role allow-words (PM-028)

**Files:** Modify `config/app.example.yaml:24-37`; Test `tests/test_prefilter.py`, `tests/test_config.py` (add).

Changes:
- `default_title_deny` += `senior, sr, lead, principal, staff, head` (`director` and `head of` are already there; 24 words, under Settings' 30 cap, and `test_default_title_exclusions_fit_the_experience_step` still passes).
- Role allow-words: Product Analyst `[product]` (was `[product, analyst, analytics]`), Growth Analyst `[growth]` (was `[growth, analyst]`), Business Analyst `[business analyst]` (was `[business analyst, analyst]`). Others unchanged. A bare "analyst" is gone from every role, so "Inventory Analyst", "QA Analyst Lead", "Operations Analyst" no longer pass for a PA/APM/PM user.
- Users with an explicit `title_deny` (the owner) or `title_allow_extra` (the owner) are unchanged; `effective_prefs` already reads both from the user first.

- [ ] **Step 1: Failing tests** — with the example config and `UserPrefs(roles=["Product Analyst", "Associate Product Manager", "Product Manager"])`, `prefilter` hides "Inventory Analyst", "Clinical Business Analyst", "QA Analyst Lead", "Senior Incident Response Analyst", "Operations Analyst", "Lead Data Analyst", "Product Control Sr Analyst" and keeps "Product Analyst", "Associate Product Manager", "Product Manager – Payments"; "Leadership Programme Analyst" is not hit by `lead` (word boundary) but is hidden as not a target role.
- [ ] **Step 2: FAIL. Step 3: Edit the YAML. Step 4: PASS** (check `test_importer`/golden tests still use the owner's explicit lists). **Step 5: Commit** `fix(match): seniority words in the default exclusions; no bare "analyst" allow-word`. Ops line (Task 12): the live `config/app.yaml` needs the same two edits, then `jobseeker refilter --user <roommate> --apply` for each user on the defaults.

---

### Task 12: Acceptance, docs and handoff

- [ ] Full suite under `TZ=UTC` and `TZ=America/New_York` too.
- [ ] Live-DB copy: migrate v0→v6 clean (FK `[]`, integrity ok, counts unchanged); serve on 127.0.0.1:8010 with scripted session cookies; at 390×844: a scripted new user finishes onboarding → `/onboarding/done` → Today shows "Job search · Scoring your first matches" and "Your first matches are on the way"; run `jobseeker tick` against the copy with a fake LLM env (or `run --no-fetch --user`) and check the new user's top-N scored and the status line; Review shows "Score pending"; Settings validation error shows in place; Delete lands on the deleted page.
- [ ] `docs/TESTING-CHECKLIST.md`: re-test items for C3/D6/D8/E2/F2 and the new status block.
- [ ] `HANDOFF.md` §8 cutover additions: **(1)** v6 runs on deploy (`start.sh` migrates); **(2)** edit the server's `config/app.yaml` like Task 11 (deny words + allow-words), then `jobseeker refilter --user <email> --apply` for each roommate; **(3)** `budgets.global_scores_per_day: 300` is already set by ops.
- [ ] Commit `docs: P0 review fixes acceptance and cutover notes`, handoff (NEXT: wait for manager), push, report.

---

## Out of scope (noted, not planned here)

- PM-068's live progress ("Scoring 40 of 170 · about 25 min left") needs run progress written mid-run; the ETA copy above covers the honesty gap.
- PM-064's server-side slot render and PM-003's "URLs that 405 on refresh".
- PM-029 (Naukri 406), being re-checked after the Singapore move by devops-lead2.
