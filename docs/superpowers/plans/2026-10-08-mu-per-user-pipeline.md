# Multi-user Per-user Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Execution method chosen by the user: Native (inline), via superpowers:executing-plans.**

**Goal:**
- Fetch jobs **once** for everyone, then evaluate, describe, score and draft **per user**, with fair shares of the free AI quota.
- Everything is driven by one host-agnostic `jobseeker tick`: the daily 11:15 IST run, the per-user "Fetch now", and the backup and health ping.

**Architecture:** `pipeline/run.py`'s single-user `run_daily` is replaced by staged, separately tested units:
- `plan.build_plan` (pure);
- `fetch.fetch_shared` (writes `jobs` only);
- `evaluate.evaluate` (per-user verdicts in `user_jobs`);
- `describe.describe_shared` (LinkedIn descriptions, interleaved);
- `score.score_round_robin` / `draft.draft_round_robin` (batches of 5 / 2 across users);
- the orchestrator `run.run_all`.

`pipeline/tick.py` holds the scheduling decision under a heartbeat lock (`db/locks.py`). It calls the extras hooks `push.notify.notify_new_matches` and `backup.nightly.nightly_backup`. The web gets `POST /fetch-now` plus a status fragment, and IST-correct times.

**Tech Stack:** Python 3.13, SQLite, FastAPI/HTMX, `zoneinfo` + `tzdata`, the existing `LLM`/`FallbackLLM`, JobSpy sources; pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-mu-per-user-pipeline-design.md`

## Dependencies on other sub-projects

**Spec 2** (`docs/superpowers/plans/2026-10-08-mu-accounts-auth.md`; the names here are taken from that plan):
- `jobseeker.db.migrations`: `Migration`, `MigrationContext(owner_email, now, home)`, `MIGRATIONS`, `latest()`;
- `jobseeker.db.users`: `OWNER_ID`, `User(id, email, name, is_admin, google_sub)`, `user_by_id`;
- `user_jobs(user_id, job_id, filter_reason, prescore, jd_hash, evaluated_at)`;
- `jobs.py`: `set_filter_reason/set_prescore(conn, user_id, job_id, …)`, `get_user_job`, `expire_unscored(conn, user_id, now, max_age_days)`, `jobs_needing_score(conn, user_id, rubric_version, limit, force=False, with_jd=False)`, `save_score(conn, user_id, job_id, result, model, rubric_version, jd_hash_value)`, `latest_score(conn, user_id, job_id)`;
- `ensure_application(conn, user_id, job_id, now=None)`, `blocked_companies(conn, user_id)`;
- `runs.py`: `start_run(conn, now, user_id=None, kind="legacy")`, `last_run(conn, user_id)`;
- `usage.py`: `Limit(period, global_cap, share_cap)`, `Budget(conn, user_id, limits, now)` (`.can/.spend/.used/.used_all`);
- `web.deps`: `current_user`;
- fixtures `seeded_two`, `client_as(user_id)`, `anon_client()`;
- `run_daily(conn, *, user_id, …)`, which this plan replaces.

**Spec 3** (`docs/superpowers/plans/2026-10-08-mu-onboarding-settings.md`; names from that plan):
- `jobseeker.config`: `AppConfig` (`.models`, `.thresholds`, `.min_prescore`, `.search: AppSearch`, `.budgets: AppBudgets`, `.roles: list[Role(label, query, allow)]`, `.companies_path`, `.rubric_path`), `load_app_config(path)`, `Settings.app_config_path`, `UserPrefs` (with `custom_role`), `effective_prefs(up, cfg, name, email)`;
- `jobseeker.db.profile`: `get_user_prefs`, `get_facts`, `load_user_context(conn, user_id, cfg) -> (Preferences, Facts | None)`;
- `user_prefs(user_id, data, version, onboarding_step, onboarded_at, updated_at)`;
- `jobseeker.pipeline.evaluate`: `verdict(job, prefs, facts, now, blocked, scored) -> (reason | None, prescore)`. It applies the `prefs.min_prescore` cutoff unless `scored` is True; this plan's `evaluate` reuses it (Task 8). Also `reevaluate(conn, user_id, prefs, facts, now, apply)`;
- `jobseeker.db.account`: `delete_account` and `user_scoped_tables`. These find **every** table with a `user_id` column, so `run_requests` is deleted automatically (Task 16 only verifies it);
- fixtures `app_config`, `settings` (with the fixture owner imported and onboarded).

**Spec 6 (extras plan):**
- `push.notify.notify_new_matches(conn, user_id, run_started_at, now) -> str | None` (a run note or `None`; never raises);
- `backup.nightly.nightly_backup(conn, settings, now, force=False) -> BackupResult(path, ok, uploaded, error, skipped)`.

If this plan is built first, Task 12 creates **stubs** with exactly these signatures: notify returns `None`, and backup returns `BackupResult(None, True, False, None, True)`.

**Build order:**

| Task | Before specs 2/3? |
|---|---|
| 1 (clock) | yes |
| 2 (`profile_hash`) | yes |
| 6 (`build_plan` + JobSpy plan) | yes |
| 3 (config) | after spec 3 Task 1 |
| 4 (v4 migration), 5 (locks) | after specs 2 and 3 |
| 7 onwards | after specs 2 and 3 |

## Global Constraints

- **Test commands:** `FORCE_COLOR= uv run pytest --color=no` and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`. **Never pass `-q`.** Baseline: the suite as specs 2/3 left it (400 before multi-user; plus their tests), and 19 node, or 26 after extras Task 12. Every task ends green.
- **No network in tests.** JobSpy `scrape`, `describe`, ATS clients and the LLM are faked (`tests/fakes.FakeLLM`). Time is injected: `now` and the clock helpers take an explicit UTC instant.
- **Time:** `APP_TZ = ZoneInfo("Asia/Kolkata")`. Storage stays UTC ISO (`db.core.iso`). Only "which day / which hour" uses IST. `tzdata` is a direct dependency.
- **`AppConfig` additions** (spec §4.1), defaults verbatim:
  - `timezone: Asia/Kolkata`;
  - `schedule.daily_at "11:15"`, `schedule.max_attempts_per_day 2`;
  - `search.max_searches_per_run 60`, `search.max_searches_fetch_now 30`, `search.max_custom_queries 3`;
  - `budgets.global_scores_per_day 150`, `global_drafts_per_day 20`, `score_per_run 80`, `draft_per_run 10`, `score_batch 5`, `draft_batch 2`;
  - `fetch_now.min_hours_between_per_user 2`, `fetch_now.max_per_day 6`;
  - `lock.takeover_after_minutes 15`.
- **Run kinds/triggers:** `runs.kind ∈ {fetch, user, legacy}`; `runs.trigger ∈ {schedule, fetch_now, cli}`; `runs.parent_id` links a user run to its fetch run.
- **`stopped_by` ∈ {`share`, `global_cap`, `quota`, `unavailable`, `no_candidates`, `run_cap`}.**
- **Fairness:** `share = floor(global_per_day / active_or_eligible_users)`. Room per run = `min(per_run, share − used_today)`. No pooling. A score or draft counts as 1, whichever model served it.
- **`profile_hash`** = sha256 over `experience_summary`, sorted `target_roles`, sorted `cities`, `remote_india_ok`, `current_ctc_lpa`, `target_base_lpa`, sorted `must_haves`, sorted `deal_breakers`, plus `facts.model_dump()`; JSON with `sort_keys=True, separators=(",", ":")`.
- **Lock:** a `locks` row named `run`, holder `"<hostname>:<pid>"`, taken over after 15 minutes without a heartbeat.
- **The ping** goes to `<url>` only if the scheduled run didn't abort **and** `nightly_backup` returned `ok=True` (`skipped=True` counts as success); otherwise to `<url>/fail`. Never on `fetch_now`/`cli`. 5 s timeout, errors only logged.
- Never `git push` or merge.

## Review Focus

1. **Two ticks overlap** (a slow run plus the timer, or a manual `jobseeker run` during a scheduled one). Expected: the second exits without doing anything; `jobseeker run` exits 1 with the holder's start time. Test: Task 5 `test_second_acquire_fails_while_fresh` and Task 13 `test_cli_run_refuses_when_locked`.
2. **The server clock is UTC, and the schedule is 11:15 IST = 05:45 UTC.** Expected: not due at 05:44Z, due at 05:45Z, and caught up after downtime at 17:30Z. A run that crossed IST midnight doesn't count for the next day. Test: Task 13 `test_schedule_due_in_ist`.
3. **A user whose `score_per_run` is smaller than their remaining share, or who has no candidates.** Expected: the stop is recorded as `run_cap` / `no_candidates`, not `share`, so the note doesn't lie. Test: Task 10 `test_stop_reasons_are_precise`.
4. **One user's onboarding isn't finished, or there are no facts yet.** Expected: they're skipped with a run note and never crash the run for others. Test: Task 12 `test_user_without_facts_is_skipped`.
5. **Force rescore (`rescore --user`).** `jobs_needing_score(force=True)` keeps returning the same jobs. Expected: each job is scored at most once per run, with no infinite loop. Test: Task 10 `test_force_scores_each_job_once`.

---

### Task 1: IST clock and `tzdata`

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (`uv add tzdata`)
- Create: `src/jobseeker/clock.py`
- Test: `tests/test_clock.py` (new)

**Interfaces:**
- Produces:
  - `APP_TZ`;
  - `app_now(now: datetime | None = None) -> datetime` (aware, IST);
  - `app_today(now=None) -> date`;
  - `app_day(dt: datetime) -> str` (naive = UTC);
  - `day_start_utc(day: date) -> datetime` (the UTC instant of IST midnight).

- [ ] **Step 1: Add the dependency** — `uv add tzdata`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_clock.py
from datetime import UTC, date, datetime

from jobseeker.clock import APP_TZ, app_day, app_now, app_today, day_start_utc


def test_ist_day_boundaries():
    assert app_day(datetime(2026, 10, 11, 18, 29, tzinfo=UTC)) == "2026-10-11"
    assert app_day(datetime(2026, 10, 11, 18, 30, tzinfo=UTC)) == "2026-10-12"
    assert app_day(datetime(2026, 10, 11, 18, 30)) == "2026-10-12"  # naive means UTC
    assert app_today(datetime(2026, 10, 11, 20, 0, tzinfo=UTC)) == date(2026, 10, 12)


def test_app_now_and_day_start():
    now = app_now(datetime(2026, 10, 11, 5, 45, tzinfo=UTC))
    assert now.tzinfo == APP_TZ and (now.hour, now.minute) == (11, 15)
    assert day_start_utc(date(2026, 10, 12)) == datetime(2026, 10, 11, 18, 30, tzinfo=UTC)
    assert app_now().tzinfo == APP_TZ
```

- [ ] **Step 3: Run it and check it fails** — `FORCE_COLOR= uv run pytest --color=no tests/test_clock.py`. Expected: `ModuleNotFoundError: jobseeker.clock`.

- [ ] **Step 4: Implement**

```python
# src/jobseeker/clock.py
"""App time: storage stays UTC; 'which day / which hour is it' is India time (one app-wide zone)."""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Asia/Kolkata")  # fails loudly at import if tzdata is missing


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def app_now(now: datetime | None = None) -> datetime:
    return _aware(now or datetime.now(UTC)).astimezone(APP_TZ)


def app_today(now: datetime | None = None) -> date:
    return app_now(now).date()


def app_day(dt: datetime) -> str:
    return _aware(dt).astimezone(APP_TZ).date().isoformat()


def day_start_utc(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), APP_TZ).astimezone(UTC)
```

- [ ] **Step 5: Run the tests** (the file, then the full suite). Expected: PASS, green.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/jobseeker/clock.py tests/test_clock.py
git commit -m "feat: IST app clock helpers and tzdata dependency"
```

---

### Task 2: `profile_hash`

**Files:**
- Create: `src/jobseeker/pipeline/profile_hash.py`
- Test: `tests/test_profile_hash.py` (new)

**Interfaces:**
- Produces: `profile_hash(prefs: Preferences, facts: Facts) -> str` (64 hex chars).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_hash.py
from jobseeker.pipeline.profile_hash import profile_hash


def test_stable_and_order_insensitive(prefs, facts):
    h = profile_hash(prefs, facts)
    assert len(h) == 64 and h == profile_hash(prefs, facts)
    shuffled = prefs.model_copy(update={"cities": list(reversed(prefs.cities)),
                                        "target_roles": list(reversed(prefs.target_roles))})
    assert profile_hash(shuffled, facts) == h


def test_scoring_fields_change_it(prefs, facts):
    h = profile_hash(prefs, facts)
    assert profile_hash(prefs.model_copy(update={"experience_summary": "x"}), facts) != h
    assert profile_hash(prefs, facts.model_copy(update={"skills": ["Rust"]})) != h
    assert profile_hash(prefs.model_copy(update={"must_haves": ["remote"]}), facts) != h


def test_filter_only_fields_do_not(prefs, facts):
    h = profile_hash(prefs, facts)
    for update in ({"title_deny": ["intern"]}, {"title_allow": ["x"]}, {"drop_if_min_years_at_least": 9},
                   {"max_age_days": 3}):
        assert profile_hash(prefs.model_copy(update=update), facts) == h
```

- [ ] **Step 2: Run it and check it fails.** Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/jobseeker/pipeline/profile_hash.py
"""Fingerprint of everything the score prompt reads about the user, so edits re-score jobs best-first."""
from __future__ import annotations

import hashlib
import json

from jobseeker.config import Preferences
from jobseeker.profile.facts import Facts


def profile_hash(prefs: Preferences, facts: Facts) -> str:
    data = {
        "experience_summary": prefs.experience_summary,
        "target_roles": sorted(prefs.target_roles),
        "cities": sorted(prefs.cities),
        "remote_india_ok": prefs.remote_india_ok,
        "current_ctc_lpa": prefs.current_ctc_lpa,
        "target_base_lpa": prefs.target_base_lpa,
        "must_haves": sorted(prefs.must_haves),
        "deal_breakers": sorted(prefs.deal_breakers),
        "facts": facts.model_dump(),
    }
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()
```

- [ ] **Step 4: Run the tests.** Expected: PASS, green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/pipeline/profile_hash.py tests/test_profile_hash.py && git commit -m "feat(pipeline): profile_hash over the score prompt's user inputs"`

---

### Task 3: `AppConfig` additions

**Files:**
- Modify: `src/jobseeker/config.py`: spec 3's `AppConfig`, `AppSearch` and `AppBudgets`; `config/app.example.yaml` (spec 3)
- Test: `tests/test_app_config_pipeline.py` (new)

**Interfaces:**
- Consumes: spec 3's `AppConfig` / `load_app_config`.
- Produces:
  - `ScheduleConfig(daily_at: str, max_attempts_per_day: int)`, with `daily_time() -> datetime.time`;
  - `FetchNowConfig(min_hours_between_per_user: float, max_per_day: int)`;
  - `LockConfig(takeover_after_minutes: int)`;
  - `AppConfig.timezone/.schedule/.fetch_now/.lock`;
  - `AppConfig.search.max_searches_per_run/.max_searches_fetch_now/.max_custom_queries`;
  - `AppConfig.budgets.global_scores_per_day/.global_drafts_per_day/.score_batch/.draft_batch` (with `score_per_run`, `draft_per_run` kept).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_config_pipeline.py
from datetime import time

import pytest
from pydantic import ValidationError

from jobseeker.config import AppConfig


def test_defaults():
    cfg = AppConfig()
    assert cfg.timezone == "Asia/Kolkata" and cfg.schedule.daily_time() == time(11, 15)
    assert cfg.schedule.max_attempts_per_day == 2
    assert (cfg.search.max_searches_per_run, cfg.search.max_searches_fetch_now, cfg.search.max_custom_queries) == (60, 30, 3)
    b = cfg.budgets
    assert (b.global_scores_per_day, b.global_drafts_per_day, b.score_per_run, b.draft_per_run,
            b.score_batch, b.draft_batch) == (150, 20, 80, 10, 5, 2)
    assert (cfg.fetch_now.min_hours_between_per_user, cfg.fetch_now.max_per_day) == (2, 6)
    assert cfg.lock.takeover_after_minutes == 15


def test_bad_daily_at_is_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"schedule": {"daily_at": "25:99"}})
```

- [ ] **Step 2: Run it and check it fails.** Expected: `AttributeError` / `ValidationError` on unknown fields.

- [ ] **Step 3: Implement** (in `src/jobseeker/config.py`):

```python
class ScheduleConfig(BaseModel):
    daily_at: str = "11:15"
    max_attempts_per_day: int = 2

    @field_validator("daily_at")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        time.fromisoformat(v)  # raises ValueError on 25:99
        return v

    def daily_time(self) -> time:
        return time.fromisoformat(self.daily_at)


class FetchNowConfig(BaseModel):
    min_hours_between_per_user: float = 2
    max_per_day: int = 6


class LockConfig(BaseModel):
    takeover_after_minutes: int = 15
```

Import `time` from `datetime` and `field_validator` from pydantic.

- To `AppConfig`, add: `timezone: str = "Asia/Kolkata"`, `schedule: ScheduleConfig = ScheduleConfig()`, `fetch_now: FetchNowConfig = FetchNowConfig()`, `lock: LockConfig = LockConfig()`.
- To `AppSearch`, add: `max_searches_per_run: int = 60`, `max_searches_fetch_now: int = 30`, `max_custom_queries: int = 3`.
- To `AppBudgets`, add: `global_scores_per_day: int = 150`, `global_drafts_per_day: int = 20`, `score_batch: int = 5`, `draft_batch: int = 2`. `score_per_run` is already 80 there.
- Mirror the new keys, with their defaults and the "provisional" comments from spec §4.1, in `config/app.example.yaml`.

- [ ] **Step 4: Run the tests** (the file plus spec 3's config tests, then the full suite). Expected: PASS, green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/config.py config/app.example.yaml tests/test_app_config_pipeline.py && git commit -m "feat(config): schedule, fetch-now, lock and fairness settings in AppConfig"`

---

### Task 4: Migration v4

**Files:**
- Modify: `src/jobseeker/db/migrations.py` (register `Migration(4, "pipeline", _v4_pipeline)`), `src/jobseeker/db/schema.sql` (latest shape), `src/jobseeker/db/runs.py` (`start_run` gains `trigger`, `parent_id`)
- Test: `tests/test_migration_v4.py` (new)

**Interfaces:**
- Consumes: Task 2 `profile_hash`; spec 3's `load_user_context(conn, user_id, cfg)` and `load_app_config(path)`; `MigrationContext(owner_email, now, home)`. v2 has already written `ctx.home/config/app.yaml`.
- Produces:
  - `runs.trigger TEXT NOT NULL DEFAULT 'cli'`, `runs.parent_id`;
  - `scores.profile_hash`;
  - tables `locks` and `run_requests`, with indexes `idx_run_requests_status` and `idx_runs_kind`;
  - `start_run(conn, now, user_id=None, kind="legacy", trigger="cli", parent_id=None) -> int`;
  - `jobs.save_score(..., profile_hash: str | None = None)` (keyword-only, added here so v4's column is used from day one).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_v4.py
from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.migrations import MIGRATIONS, latest
from jobseeker.db.runs import start_run


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_v4_registered():
    assert [m.name for m in MIGRATIONS if m.version == 4] == ["pipeline"] and latest() >= 4


def test_fresh_shape(tmp_path):
    conn = connect(tmp_path / "f.db")
    assert {"trigger", "parent_id", "kind", "user_id"} <= _cols(conn, "runs")
    assert "profile_hash" in _cols(conn, "scores")
    assert _cols(conn, "locks") == {"name", "holder", "acquired_at", "heartbeat_at"}
    assert _cols(conn, "run_requests") == {"id", "user_id", "requested_at", "status", "run_id", "finished_at"}


def test_start_run_records_trigger_and_parent(tmp_path):
    conn = connect(tmp_path / "f.db")
    now = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)
    fetch = start_run(conn, now, None, kind="fetch", trigger="schedule")
    user = start_run(conn, now, 1, kind="user", trigger="schedule", parent_id=fetch)
    row = conn.execute("SELECT kind, trigger, parent_id, user_id FROM runs WHERE id = ?", (user,)).fetchone()
    assert tuple(row) == ("user", "schedule", fetch, 1)


def test_backfill_keeps_owner_scores_fresh(migrated_owner_db):
    """`migrated_owner_db` is spec 2/3's fixture that migrates the v0 fixture DB plus the fixture profile/ to latest.
    The v4 back-fill must equal the runtime hash, so the owner's existing scores aren't all stale at once."""
    from jobseeker.config import load_app_config
    from jobseeker.db.profile import load_user_context
    from jobseeker.pipeline.profile_hash import profile_hash

    conn, home = migrated_owner_db
    prefs, facts = load_user_context(conn, 1, load_app_config(home / "config" / "app.yaml"))
    hashes = {r[0] for r in conn.execute("SELECT profile_hash FROM scores WHERE user_id = 1")}
    assert hashes == {profile_hash(prefs, facts)}
```

`migrated_owner_db` builds a v0 DB, puts `tests/fixtures/preferences.yaml` and `facts.json` in `home/profile/` (as spec 3's v2 test does, plan 3 Task 2), runs `migrate` to latest, and returns `(conn, home)`. Add it to `tests/conftest.py`, reusing spec 3's v2 test setup (factor that setup into this fixture rather than copying it).

- [ ] **Step 2: Run it and check it fails.** Expected: no v4, missing columns.

- [ ] **Step 3: Implement**

In `src/jobseeker/db/migrations.py`:
```python
def _v4_pipeline(conn, ctx) -> None:
    conn.execute("ALTER TABLE runs ADD COLUMN trigger TEXT NOT NULL DEFAULT 'cli'")
    conn.execute("ALTER TABLE runs ADD COLUMN parent_id INTEGER REFERENCES runs(id)")
    conn.execute("ALTER TABLE scores ADD COLUMN profile_hash TEXT")
    conn.execute("""CREATE TABLE locks (name TEXT PRIMARY KEY, holder TEXT NOT NULL, acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE run_requests (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    requested_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
                    run_id INTEGER REFERENCES runs(id), finished_at TEXT)""")
    conn.execute("CREATE INDEX idx_run_requests_status ON run_requests (status, requested_at)")
    conn.execute("CREATE INDEX idx_runs_kind ON runs (kind, trigger, started_at)")
    from jobseeker.config import load_app_config
    from jobseeker.db.profile import load_user_context
    from jobseeker.pipeline.profile_hash import profile_hash

    prefs, facts = load_user_context(conn, 1, load_app_config(ctx.home / "config" / "app.yaml"))
    if facts is not None:  # an owner who hasn't onboarded has nothing to back-fill
        conn.execute("UPDATE scores SET profile_hash = ? WHERE user_id = 1", (profile_hash(prefs, facts),))
```

**`load_user_context` must not commit.** It's only reads. Check that, because the framework owns the transaction.

In `schema.sql`:
- `runs` gains `trigger TEXT NOT NULL DEFAULT 'cli'` and `parent_id INTEGER REFERENCES runs (id)` after `kind`;
- `scores` gains `profile_hash TEXT`;
- add the two tables and two indexes with `IF NOT EXISTS`.

`src/jobseeker/db/runs.py`:
```python
def start_run(conn: sqlite3.Connection, now: datetime, user_id: int | None = None, kind: str = "legacy",
              trigger: str = "cli", parent_id: int | None = None) -> int:
    cur = conn.execute("INSERT INTO runs (started_at, user_id, kind, trigger, parent_id) VALUES (?, ?, ?, ?, ?)",
                       (iso(now), user_id, kind, trigger, parent_id))
    conn.commit()
    return cur.lastrowid
```

`src/jobseeker/db/jobs.py`, `save_score`: add a keyword-only `profile_hash: str | None = None` and include it in the INSERT column list and values.

- [ ] **Step 4: Run the tests:** `FORCE_COLOR= uv run pytest --color=no tests/test_migration_v4.py tests/test_migrations.py`, then the full suite. Expected: PASS, including spec 2's fresh-vs-migrated equality.

- [ ] **Step 5: Commit** — `git add src/jobseeker/db/migrations.py src/jobseeker/db/schema.sql src/jobseeker/db/runs.py src/jobseeker/db/jobs.py tests/test_migration_v4.py && git commit -m "feat(db): migration v4 for run triggers, locks, run requests and score profile_hash"`

---

### Task 5: The heartbeat lock (`db/locks.py`)

**Files:**
- Create: `src/jobseeker/db/locks.py`
- Test: `tests/test_locks.py` (new)

**Interfaces:**
- Produces:
  - `LockLost(RuntimeError)`;
  - `holder_id() -> str` (`"<hostname>:<pid>"`);
  - `acquire(conn, name, holder, now, takeover_minutes) -> bool`;
  - `heartbeat(conn, name, holder, now) -> None` (raises `LockLost`);
  - `release(conn, name, holder) -> None`;
  - `held_since(conn, name) -> str | None` (ISO `acquired_at`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_locks.py
from datetime import UTC, datetime, timedelta

import pytest

from jobseeker.db.core import connect
from jobseeker.db.locks import LockLost, acquire, heartbeat, held_since, release

T0 = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def test_second_acquire_fails_while_fresh(tmp_path):
    conn = connect(tmp_path / "db")
    assert acquire(conn, "run", "a:1", T0, 15)
    assert not acquire(conn, "run", "b:2", T0 + timedelta(minutes=14), 15)
    heartbeat(conn, "run", "a:1", T0 + timedelta(minutes=10))
    assert not acquire(conn, "run", "b:2", T0 + timedelta(minutes=24), 15)  # heartbeat refreshed at +10
    assert held_since(conn, "run") == "2026-10-11T05:45:00+00:00"


def test_takeover_after_silence_and_lock_lost(tmp_path):
    conn = connect(tmp_path / "db")
    acquire(conn, "run", "a:1", T0, 15)
    assert acquire(conn, "run", "b:2", T0 + timedelta(minutes=16), 15)
    with pytest.raises(LockLost):
        heartbeat(conn, "run", "a:1", T0 + timedelta(minutes=17))
    release(conn, "run", "a:1")  # the old holder's release is a no-op
    assert held_since(conn, "run") is not None
    release(conn, "run", "b:2")
    assert held_since(conn, "run") is None and acquire(conn, "run", "c:3", T0 + timedelta(minutes=18), 15)
```

- [ ] **Step 2: Run it and check it fails.** Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/jobseeker/db/locks.py
"""One run at a time across processes: a row with a heartbeat; a silent holder is taken over after N minutes."""
from __future__ import annotations

import os
import socket
import sqlite3
from datetime import datetime, timedelta

from jobseeker.db.core import iso


class LockLost(RuntimeError):
    pass


def holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire(conn: sqlite3.Connection, name: str, holder: str, now: datetime, takeover_minutes: int) -> bool:
    cur = conn.execute(
        """INSERT INTO locks (name, holder, acquired_at, heartbeat_at) VALUES (?, ?, ?, ?)
           ON CONFLICT (name) DO UPDATE SET holder = excluded.holder, acquired_at = excluded.acquired_at,
             heartbeat_at = excluded.heartbeat_at
           WHERE locks.heartbeat_at < ?""",
        (name, holder, iso(now), iso(now), iso(now - timedelta(minutes=takeover_minutes))))
    conn.commit()
    return cur.rowcount == 1


def heartbeat(conn: sqlite3.Connection, name: str, holder: str, now: datetime) -> None:
    cur = conn.execute("UPDATE locks SET heartbeat_at = ? WHERE name = ? AND holder = ?", (iso(now), name, holder))
    conn.commit()
    if cur.rowcount != 1:
        raise LockLost(f"lock {name!r} was taken over")


def release(conn: sqlite3.Connection, name: str, holder: str) -> None:
    conn.execute("DELETE FROM locks WHERE name = ? AND holder = ?", (name, holder))
    conn.commit()


def held_since(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT acquired_at FROM locks WHERE name = ?", (name,)).fetchone()
    return row["acquired_at"] if row else None
```

- [ ] **Step 4: Run the tests.** Expected: PASS, green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/db/locks.py tests/test_locks.py && git commit -m "feat(db): heartbeat run lock with takeover"`

---

### Task 6: The search plan and plan-driven JobSpy sources

**Files:**
- Create: `src/jobseeker/pipeline/plan.py`
- Modify:
  - `src/jobseeker/sources/jobspy_source.py:74-87`: an optional `plan` argument; `searches()` returns it when given;
  - `src/jobseeker/sources/registry.py:16-31`: an optional `plan: Plan | None`.
- Test: `tests/test_plan.py` (new); `tests/test_sources_jobspy.py` (append)

**Interfaces:**
- Produces:
  - `PlanUser(user_id: int, queries: list[str], locations: list[str], custom: str, prefs_updated_at: str)`;
  - `Plan(linkedin: list[str], pairs: list[tuple[str, str]], planned: int, trimmed: int)`, with `.for_site(site) -> list[tuple[str, str]]`;
  - `build_plan(users: list[PlanUser], sites: list[str], catalog: set[str], run_no: int, cap: int, max_custom: int) -> Plan`;
  - `plan_users(users_prefs: list[tuple[int, Preferences, str, str]]) -> list[PlanUser]`, from `(user_id, prefs, custom_role, prefs_updated_at)`;
  - `JobSpySource(site, search, plan=None, …)`;
  - `build_sources(companies, discovered=(), search=None, plan=None)`.

**Rotation, made concrete** (spec §4.2 says rotating trimmed pairs must reach every pair within ⌈trimmed/fitted⌉ runs, and that round 1 gives every user their first pair):
1. Round 1 (each user's top pair, users rotated by `run_no`) is **always** planned when it fits.
2. The remaining wanted pairs, in fair round-robin order, form `rest`. With `S` slots left: if `len(rest) ≤ S` take all of them; otherwise take the window `rest[(run_no·S) mod len(rest)]`, `S` long, wrapping round. `trimmed = len(rest) − S`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plan.py
from jobseeker.pipeline.plan import Plan, PlanUser, build_plan

SITES = ["linkedin", "naukri", "indeed"]
CATALOG = {"Product Analyst", "Associate Product Manager", "Product Manager", "Founder's Office", "Growth Analyst",
           "Business Analyst", "Data Analyst"}
OWNER = PlanUser(1, ["Product Analyst", "Associate Product Manager", "Product Manager", "Founder's Office",
                     "Growth Analyst"], ["Bengaluru", "Gurgaon", "Noida", "Pune", "India"], "", "2026-10-01")


def test_owner_alone_is_todays_55_searches():
    plan = build_plan([OWNER], SITES, CATALOG, run_no=0, cap=60, max_custom=3)
    assert len(plan.linkedin) == 5 and len(plan.pairs) == 25
    assert plan.planned == 55 and plan.trimmed == 0
    assert plan.for_site("linkedin") == [(q, "India") for q in plan.linkedin]
    assert plan.for_site("naukri") == plan.pairs


def test_union_dedups_and_round_one_serves_everyone():
    a = PlanUser(1, ["Product Analyst"], ["Bengaluru", "Pune"], "", "1")
    b = PlanUser(2, ["Data Analyst"], ["Mumbai"], "", "2")
    c = PlanUser(3, ["Product Analyst"], ["Bengaluru"], "", "3")
    plan = build_plan([a, b, c], SITES, CATALOG, run_no=0, cap=2 + 2 * 2, max_custom=3)  # 2 linkedin + 2 pairs
    assert sorted(plan.linkedin) == ["Data Analyst", "Product Analyst"]
    assert ("Product Analyst", "Bengaluru") in plan.pairs and ("Data Analyst", "Mumbai") in plan.pairs
    assert plan.planned <= 6 and plan.trimmed == 1  # ("Product Analyst", "Pune") rotates in later


def test_cap_never_exceeded_and_rotation_reaches_every_pair():
    users = [PlanUser(u, ["Product Analyst", "Data Analyst"], ["Bengaluru", "Pune", "Mumbai", "Hyderabad"], "", str(u))
             for u in (1, 2, 3)]
    seen: set = set()
    plans = [build_plan(users, SITES, CATALOG, run_no=n, cap=14, max_custom=3) for n in range(8)]
    for p in plans:
        assert len(p.linkedin) + 2 * len(p.pairs) <= 14
        seen |= set(p.pairs)
    assert seen == {(q, c) for q in ("Product Analyst", "Data Analyst") for c in ("Bengaluru", "Pune", "Mumbai", "Hyderabad")}


def test_custom_queries_capped_oldest_first():
    users = [PlanUser(u, [f"Custom {u}"], ["Pune"], f"Custom {u}", f"2026-10-0{u}") for u in (4, 1, 3, 2)]
    plan = build_plan(users, SITES, CATALOG, run_no=0, cap=100, max_custom=3)
    assert sorted(plan.linkedin) == ["Custom 1", "Custom 2", "Custom 3"]


def test_no_linkedin_site_and_empty_users():
    assert build_plan([], SITES, CATALOG, 0, 60, 3) == Plan([], [], 0, 0)
    plan = build_plan([OWNER], ["naukri"], CATALOG, 0, 60, 3)
    assert plan.linkedin == [] and plan.planned == 25
```

Append to `tests/test_sources_jobspy.py`:
```python
def test_plan_overrides_searches():
    from jobseeker.config import SearchConfig
    from jobseeker.sources.jobspy_source import JobSpySource

    calls = []
    src = JobSpySource("naukri", SearchConfig(), scrape=lambda **kw: calls.append((kw["search_term"], kw["location"])) or [],
                       sleep=lambda s: None, plan=[("Data Analyst", "Mumbai")])
    src.fetch(None)
    assert calls == [("Data Analyst", "Mumbai")]
```

- [ ] **Step 2: Run them and check they fail.** Expected: `ModuleNotFoundError: jobseeker.pipeline.plan`; `TypeError: unexpected keyword 'plan'`.

- [ ] **Step 3: Implement `plan.py`**

```python
# src/jobseeker/pipeline/plan.py
"""Which job-site searches to run: the union of every user's roles × places, capped, fair, rotating."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from jobseeker.config import Preferences


@dataclass(frozen=True)
class PlanUser:
    user_id: int
    queries: list[str]
    locations: list[str]
    custom: str
    prefs_updated_at: str


@dataclass(frozen=True)
class Plan:
    linkedin: list[str]
    pairs: list[tuple[str, str]]
    planned: int
    trimmed: int

    def for_site(self, site: str) -> list[tuple[str, str]]:
        return [(q, "India") for q in self.linkedin] if site == "linkedin" else list(self.pairs)


def plan_users(rows: list[tuple[int, Preferences, str, str]]) -> list[PlanUser]:
    out = []
    for user_id, prefs, custom, updated_at in rows:
        locations = list(prefs.cities) + (["India"] if prefs.remote_india_ok else [])
        out.append(PlanUser(user_id, list(dict.fromkeys(prefs.search.queries)), locations, custom, updated_at))
    return out


def build_plan(users: list[PlanUser], sites: list[str], catalog: set[str], run_no: int, cap: int,
               max_custom: int) -> Plan:
    customs = [c for _, c in sorted({(u.prefs_updated_at, u.custom) for u in users if u.custom})]
    allowed = catalog | set(list(dict.fromkeys(customs))[:max_custom])
    wants = {u.user_id: [q for q in u.queries if q in allowed] for u in users}
    query_demand = Counter(q for qs in wants.values() for q in set(qs))

    def query_key(q: str):
        return (q not in catalog, -query_demand[q], q)

    linkedin: list[str] = []
    budget = cap
    if "linkedin" in sites:
        for q in sorted(query_demand, key=query_key):
            if budget < 1:
                break
            linkedin.append(q)
            budget -= 1

    pair_cost = sum(1 for s in sites if s != "linkedin")
    if pair_cost == 0 or not users:
        return Plan(linkedin, [], len(linkedin), 0)
    user_pairs = {u.user_id: [(q, loc) for q in wants[u.user_id] for loc in u.locations] for u in users}
    pair_demand = Counter(p for ps in user_pairs.values() for p in set(ps))
    for uid, ps in user_pairs.items():
        ps.sort(key=lambda p: (-pair_demand[p], p[0] not in catalog, p))

    order = sorted(user_pairs)
    shift = run_no % len(order)
    order = order[shift:] + order[:shift]
    fair: list[tuple[str, str]] = []  # round-robin over users, skipping pairs already taken
    taken: set = set()
    idx = dict.fromkeys(order, 0)
    while any(idx[u] < len(user_pairs[u]) for u in order):
        for u in order:
            ps = user_pairs[u]
            while idx[u] < len(ps) and ps[idx[u]] in taken:
                idx[u] += 1
            if idx[u] < len(ps):
                taken.add(ps[idx[u]])
                fair.append(ps[idx[u]])
                idx[u] += 1

    slots = budget // pair_cost
    first_round = [user_pairs[u][0] for u in order if user_pairs[u]]
    first_round = list(dict.fromkeys(first_round))[:slots]
    rest = [p for p in fair if p not in set(first_round)]
    left = slots - len(first_round)
    if len(rest) <= left:
        chosen, trimmed = rest, 0
    else:
        start = (run_no * left) % len(rest) if left else 0
        chosen = [rest[(start + i) % len(rest)] for i in range(left)]
        trimmed = len(rest) - left
    pairs = first_round + chosen
    return Plan(linkedin, pairs, len(linkedin) + pair_cost * len(pairs), trimmed)
```

- [ ] **Step 4: Plan-driven sources**

`JobSpySource.__init__` gains `plan: list[tuple[str, str]] | None = None` (stored as `self.plan`). `searches()` starts with `if self.plan is not None: return list(self.plan)`.

`build_sources(companies, discovered=(), search=None, plan=None)`, last part:
```python
    if search is not None:
        for site in search.sites:
            site_plan = plan.for_site(site) if plan is not None else None
            if site_plan == []:
                continue  # nothing planned for this site this run
            sources.append(JobSpySource(site, search, plan=site_plan))
    return sources
```

- [ ] **Step 5: Run the tests:** `tests/test_plan.py tests/test_sources_jobspy.py tests/test_run_discovery.py`, then the full suite. Expected: PASS. Today's callers pass no plan, so behaviour is unchanged.

- [ ] **Step 6: Commit** — `git add src/jobseeker/pipeline/plan.py src/jobseeker/sources/jobspy_source.py src/jobseeker/sources/registry.py tests/test_plan.py tests/test_sources_jobspy.py && git commit -m "feat(pipeline): capped, fair, rotating search plan across users"`

---

### Task 7: `fetch_shared`

**Files:**
- Create: `src/jobseeker/pipeline/fetch.py`
- Test: `tests/test_fetch_shared.py` (new)

**Interfaces:**
- Produces:
  - `FetchStats(fetched=0, new=0, duplicates=0, discovered=0, searches_planned=0, searches_run=0, searches_trimmed=0, described=0, errors=[])` (dataclass);
  - `fetch_shared(conn, sources, client, now, generic_words: set[str], stats: FetchStats, heartbeat=lambda: None) -> FetchStats`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_shared.py
from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.pipeline.fetch import FetchStats, fetch_shared
from tests.test_run import StaticSource, raw  # reuse today's source fakes

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def test_writes_jobs_only(tmp_path):
    conn = connect(tmp_path / "db")
    beats = []
    stats = fetch_shared(conn, [StaticSource("lever:cred", [raw(), raw(source_job_id="2", title="SDE II")])], None, NOW,
                         set(), FetchStats(), heartbeat=lambda: beats.append(1))
    assert (stats.fetched, stats.new) == (2, 2) and beats == [1]
    for table in ("user_jobs", "scores", "applications"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_one_failing_source_is_recorded(tmp_path):
    conn = connect(tmp_path / "db")
    stats = fetch_shared(conn, [StaticSource("lever:x", error=RuntimeError("boom")), StaticSource("lever:cred", [raw()])],
                         None, NOW, set(), FetchStats())
    assert stats.new == 1 and stats.errors == ["lever:x: RuntimeError: boom"]


def test_discovery_ignores_any_users_blocklist(tmp_path, monkeypatch):
    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO blocklist (user_id, company, reason, at) VALUES (1, 'cred', 'not interested', 't')")
    conn.commit()
    seen = {}
    monkeypatch.setattr("jobseeker.pipeline.fetch.discover",
                        lambda conn, client, s, known, now, generic: seen.update(known=known) or 0)
    src = StaticSource("naukri", [raw(source="naukri")])
    src.discovers = True
    fetch_shared(conn, [src], object(), NOW, set(), FetchStats())
    assert "cred" not in seen["known"]
```

- [ ] **Step 2: Run it and check it fails.** Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement** (from `run.py:86-126` with the per-user parts removed)

```python
# src/jobseeker/pipeline/fetch.py
"""Stage 2: fetch every planned source once and store jobs. No per-user verdicts, no AI."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from jobseeker.db.companies import bump_jobs_seen, mark_inactive
from jobseeker.db.jobs import upsert_job
from jobseeker.pipeline.discovery import discover
from jobseeker.pipeline.normalize import normalize, normalize_company, normalize_title


@dataclass
class FetchStats:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    discovered: int = 0
    searches_planned: int = 0
    searches_run: int = 0
    searches_trimmed: int = 0
    described: int = 0
    errors: list[str] = field(default_factory=list)


def fetch_shared(conn, sources, client, now: datetime, generic_words: set[str], stats: FetchStats,
                 heartbeat: Callable[[], None] = lambda: None) -> FetchStats:
    known = {normalize_company(s.company.name) for s in sources if hasattr(s, "company")}
    seen: dict[str, tuple[str, set[str]]] = {}
    for src in sources:
        try:
            raws = src.fetch(client)
        except Exception as e:  # one broken source must never kill the run
            stats.errors.append(f"{src.name}: {type(e).__name__}: {e}")
            norm = getattr(src, "discovered_as", None)
            if norm and isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                mark_inactive(conn, norm, now)
            heartbeat()
            continue
        stats.errors += [f"{src.name}: {w}" for w in getattr(src, "warnings", [])]
        stats.searches_run += len(src.searches()) if hasattr(src, "searches") else 0
        stats.fetched += len(raws)
        for r in raws:
            job = normalize(r)
            if getattr(src, "discovers", False):
                seen.setdefault(normalize_company(job.company), (job.company, set()))[1].add(normalize_title(job.title))
            _, is_new = upsert_job(conn, job, now)
            if is_new:
                stats.new += 1
                bump_jobs_seen(conn, normalize_company(job.company))  # counts every new job (definition change)
            else:
                stats.duplicates += 1
        heartbeat()
    if client is not None and seen:
        stats.discovered = discover(conn, client, seen, known, now, generic=generic_words)
    return stats
```

`bump_jobs_seen` returned False for companies not yet recorded, and the old code re-bumped those after discovery. Keep that, as it was:
```python
            if is_new:
                stats.new += 1
                norm = normalize_company(job.company)
                if not bump_jobs_seen(conn, norm):
                    unrecorded[norm] += 1
```
That needs `unrecorded: Counter[str] = Counter()` before the loop. After `discover`, add `for norm, n in unrecorded.items(): bump_jobs_seen(conn, norm, n)` exactly as `run.py:125-126`. Use this version, not the one-line bump above.

- [ ] **Step 4: Run the tests.** Expected: PASS, green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/pipeline/fetch.py tests/test_fetch_shared.py && git commit -m "feat(pipeline): fetch_shared writes jobs once for everyone"`

---

### Task 8: `evaluate` (reusing `verdict`) and `describe_shared`

**Files:**
- Modify: `src/jobseeker/pipeline/evaluate.py` (spec 3): add `evaluate` next to `verdict`/`reevaluate`. `src/jobseeker/db/jobs.py`: add `set_verdict` and `linkedin_picks`.
- Create: `src/jobseeker/pipeline/describe.py`
- Test: `tests/test_evaluate.py` (new), `tests/test_describe_shared.py` (new)

**Interfaces:**
- Produces:
  - `EvalStats(evaluated=0, filtered=0, below_cutoff=0)`;
  - `evaluate(conn, user_id, prefs, facts, now, heartbeat=lambda: None) -> EvalStats`. It calls spec 3's `verdict` with `scored=False` for a job new to this user (cutoff applies) and `scored=True` for a changed description (no cutoff, spec §4.4). `prefs.min_prescore` comes from `effective_prefs`;
  - `set_verdict(conn, user_id, job_id, filter_reason, prescore, jd_hash, now) -> None` (no commit);
  - `linkedin_picks(conn, user_id, cap) -> list[int]`;
  - `DescribeStats(attempted=0, described=0, failed=0, errors=[])`;
  - `describe_shared(conn, picks: list[list[int]], cap: int, describe, heartbeat=lambda: None) -> DescribeStats`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_evaluate.py
from datetime import UTC, datetime, timedelta

from jobseeker.db.core import connect
from jobseeker.db.jobs import get_user_job, upsert_job
from jobseeker.pipeline.evaluate import evaluate
from tests.factories import make_job

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def _db(tmp_path):
    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'roomie@example.com', 't')")
    conn.commit()
    return conn


def test_new_jobs_get_verdicts_per_user(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    ok, _ = upsert_job(conn, make_job(source_job_id="ok", fingerprint="f1", posted_at=NOW), NOW)
    sde, _ = upsert_job(conn, make_job(source_job_id="sde", fingerprint="f2", title="Software Engineer", posted_at=NOW), NOW)
    stats = evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW)
    assert stats.evaluated == 2 and stats.filtered == 1
    assert get_user_job(conn, 1, ok)["filter_reason"] is None and get_user_job(conn, 1, ok)["prescore"] is not None
    assert get_user_job(conn, 1, sde)["filter_reason"]
    assert get_user_job(conn, 2, ok) is None  # other users untouched
    assert evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW).evaluated == 0  # nothing new


def test_low_prescore_cutoff_only_for_new_jobs(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    j, _ = upsert_job(conn, make_job(source_job_id="a", fingerprint="fa", posted_at=NOW, jd_text="x"), NOW)
    evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 999}), facts, NOW)
    assert get_user_job(conn, 1, j)["filter_reason"].startswith("low pre-score: ")
    conn.execute("UPDATE jobs SET jd_text = 'SQL A/B testing 2-4 years', jd_hash = 'changed' WHERE id = ?", (j,))
    conn.commit()
    assert evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 999}), facts, NOW).evaluated == 1
    assert get_user_job(conn, 1, j)["filter_reason"] is None  # a changed description re-judges without the cutoff


def test_old_jobs_are_not_evaluated(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    upsert_job(conn, make_job(source_job_id="old", fingerprint="fo", posted_at=NOW - timedelta(days=30)),
               NOW - timedelta(days=30))
    assert evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW).evaluated == 0


def test_late_joiner_gets_verdicts_for_existing_jobs(tmp_path, prefs, facts):
    conn = _db(tmp_path)
    j, _ = upsert_job(conn, make_job(source_job_id="ok", fingerprint="f1", posted_at=NOW), NOW)
    evaluate(conn, 1, prefs.model_copy(update={'min_prescore': 0}), facts, NOW)
    evaluate(conn, 2, prefs.model_copy(update={'min_prescore': 0}), facts, NOW)
    assert get_user_job(conn, 2, j) is not None
```

```python
# tests/test_describe_shared.py
from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.pipeline.describe import describe_shared


def _jobs(conn, n):
    ids = []
    for i in range(n):
        cur = conn.execute("""INSERT INTO jobs (source, source_job_id, company, title, location, location_city, remote,
                              jd_text, jd_hash, apply_url, fingerprint, first_seen_at)
                              VALUES ('linkedin', ?, 'C', 'PA', 'B', 'B', 0, '', 'h', 'u', ?, 't')""", (f"li-{i}", f"fp{i}"))
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def test_interleaves_dedups_and_caps(tmp_path):
    conn = connect(tmp_path / "db")
    a, b, c, d = _jobs(conn, 4)
    asked = []
    stats = describe_shared(conn, [[a, b, c], [c, d]], cap=3, describe=lambda s, i: asked.append(i) or "JD text")
    assert asked == ["li-0", "li-2", "li-1"] and stats.described == 3  # u1#1, u2#1, u1#2 (u2#2 = dup of c is skipped)
    assert conn.execute("SELECT jd_text FROM jobs WHERE id = ?", (a,)).fetchone()[0] == "JD text"


def test_stops_after_two_consecutive_failures(tmp_path):
    conn = connect(tmp_path / "db")
    ids = _jobs(conn, 4)
    stats = describe_shared(conn, [ids], cap=10, describe=lambda s, i: "")
    assert stats.attempted == 2 and stats.failed == 2
    assert stats.errors == ["linkedin descriptions: 2 failed (last: empty description)"]
    assert conn.execute("SELECT jd_attempts FROM jobs WHERE id = ?", (ids[0],)).fetchone()[0] == 1
```

- [ ] **Step 2: Run them and check they fail.** Expected: ImportErrors.

- [ ] **Step 3: Implement**

In `src/jobseeker/db/jobs.py`:
```python
def set_verdict(conn: sqlite3.Connection, user_id: int, job_id: int, filter_reason: str | None,
                prescore: int | None, jd_hash_value: str, now: datetime) -> None:
    """Write one user's verdict on one job (caller commits; evaluate writes thousands at once)."""
    conn.execute(
        """INSERT INTO user_jobs (user_id, job_id, filter_reason, prescore, jd_hash, evaluated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (user_id, job_id) DO UPDATE SET filter_reason = excluded.filter_reason,
             prescore = excluded.prescore, jd_hash = excluded.jd_hash, evaluated_at = excluded.evaluated_at""",
        (user_id, job_id, filter_reason, prescore, jd_hash_value, iso(now)))


def linkedin_picks(conn: sqlite3.Connection, user_id: int, cap: int) -> list[int]:
    rows = conn.execute(
        """SELECT j.id FROM jobs j JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u
           WHERE uj.filter_reason IS NULL AND j.source = 'linkedin' AND TRIM(j.jd_text) = '' AND j.jd_attempts < 2
           AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id)
           ORDER BY COALESCE(uj.prescore, -1) DESC, j.id LIMIT :cap""", {"u": user_id, "cap": cap}).fetchall()
    return [r["id"] for r in rows]
```

In `src/jobseeker/pipeline/evaluate.py` (spec 3's module):
```python
@dataclass
class EvalStats:
    evaluated: int = 0
    filtered: int = 0
    below_cutoff: int = 0


def evaluate(conn, user_id: int, prefs, facts, now, heartbeat: Callable[[], None] = lambda: None) -> EvalStats:
    """Verdicts for live jobs this user has never judged, or whose description changed. Never touches applications."""
    expire_unscored(conn, user_id, now, prefs.max_age_days)
    blocked = blocked_companies(conn, user_id)
    rows = conn.execute(
        """SELECT j.*, uj.job_id AS uj_job FROM jobs j
           LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = ?
           WHERE COALESCE(j.posted_at, j.first_seen_at) >= ? AND (uj.job_id IS NULL OR uj.jd_hash != j.jd_hash)
           ORDER BY j.id""", (user_id, iso(now - timedelta(days=prefs.max_age_days)))).fetchall()
    stats = EvalStats()
    for i, row in enumerate(rows, 1):
        new = row["uj_job"] is None
        # verdict's `scored` flag means "skip the pre-score cutoff": True for a changed description (spec §4.4)
        reason, points = verdict(job_from_row(dict(row)), prefs, facts, now, blocked, not new)
        set_verdict(conn, user_id, row["id"], reason, points, row["jd_hash"], now)
        stats.evaluated += 1
        if reason and reason.startswith("low pre-score"):
            stats.below_cutoff += 1
        elif reason:
            stats.filtered += 1
        if i % 500 == 0:
            conn.commit()
            heartbeat()
    conn.commit()
    return stats
```
`reevaluate` already calls `verdict`, so both paths share one rule. Imports to add to `evaluate.py`: `from dataclasses import dataclass`, `from collections.abc import Callable`, `from datetime import timedelta`, `set_verdict` and `expire_unscored` from `db.jobs`.

`src/jobseeker/pipeline/describe.py`:
```python
"""Stage 4: fetch LinkedIn descriptions for the jobs users most likely want, shared and interleaved."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from jobseeker.db.jobs import record_jd_attempt, set_jd_text

MAX_CONSECUTIVE_FAILURES = 2


@dataclass
class DescribeStats:
    attempted: int = 0
    described: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def describe_shared(conn, picks: list[list[int]], cap: int, describe: Callable[[str, str], str],
                    heartbeat: Callable[[], None] = lambda: None) -> DescribeStats:
    order: list[int] = []
    for rank in range(max((len(p) for p in picks), default=0)):
        for p in picks:
            if rank < len(p) and p[rank] not in order:
                order.append(p[rank])
    stats, consecutive, last = DescribeStats(), 0, ""
    for job_id in order:
        if stats.attempted >= cap or consecutive >= MAX_CONSECUTIVE_FAILURES:
            break
        row = conn.execute("SELECT source, source_job_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        stats.attempted += 1
        try:
            text = describe(row["source"], row["source_job_id"])
            error = "" if text else "empty description"
        except Exception as e:
            text, error = "", f"{type(e).__name__}: {e}"
        if text:
            set_jd_text(conn, job_id, text)
            stats.described += 1
            consecutive = 0
        else:
            record_jd_attempt(conn, job_id)
            stats.failed += 1
            consecutive += 1
            last = error
        heartbeat()
    if stats.failed:
        stats.errors.append(f"linkedin descriptions: {stats.failed} failed (last: {last})")
    return stats
```

The interleave test's expected order (`li-0, li-2, li-1`) is: rank 0 gives `a`, `c`; rank 1 gives `b` (and `d`, cut off by the cap of 3).

- [ ] **Step 4: Run the tests:** `tests/test_evaluate.py tests/test_describe_shared.py`, spec 3's reevaluate tests, then the full suite. Expected: PASS, green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/pipeline/evaluate.py src/jobseeker/pipeline/describe.py src/jobseeker/db/jobs.py tests/test_evaluate.py tests/test_describe_shared.py && git commit -m "feat(pipeline): per-user evaluate and shared, interleaved LinkedIn describe"`

---

### Task 9: Freshness by `profile_hash` in `jobs_needing_score`

**Files:**
- Modify: `src/jobseeker/db/jobs.py` (`jobs_needing_score`, as spec 2 left it)
- Test: `tests/test_db_jobs.py` (append)

**Interfaces:**
- Produces: `jobs_needing_score(conn, user_id, rubric_version, limit, force=False, with_jd=False, profile_hash: str | None = None, exclude: set[int] = frozenset())`.
  - With `profile_hash`, a score counts as fresh only when its `profile_hash` matches too.
  - `exclude` drops ids already handled in this run.
  - Only **live** jobs (within the user's `max_age_days`) are returned; that's enforced by `evaluate`'s `expire_unscored` plus `user_jobs` presence.

- [ ] **Step 1: Write the failing test** (append to `tests/test_db_jobs.py`):

```python
def test_profile_hash_makes_scores_stale(tmp_path):
    from jobseeker.db.jobs import jobs_needing_score, save_score, set_prescore
    from jobseeker.models import ScoreResult

    conn = connect(tmp_path / "db.sqlite")
    a, _ = upsert_job(conn, make_job(source_job_id="a", fingerprint="fa", jd_text="SQL"))
    set_prescore(conn, 1, a, 50)
    h = conn.execute("SELECT jd_hash FROM jobs WHERE id = ?", (a,)).fetchone()[0]
    save_score(conn, 1, a, ScoreResult(score=80, breakdown={}, matches=[], gaps=[], recommendation="apply",
                                       role_family="x"), "m", "v1", h, profile_hash="p1")
    assert jobs_needing_score(conn, 1, "v1", 10, with_jd=True, profile_hash="p1") == []
    assert [r["id"] for r in jobs_needing_score(conn, 1, "v1", 10, with_jd=True, profile_hash="p2")] == [a]
    assert jobs_needing_score(conn, 1, "v1", 10, with_jd=True, profile_hash="p2", exclude={a}) == []
    assert [r["id"] for r in jobs_needing_score(conn, 1, "v1", 10, force=True, exclude=set())] == [a]
```

- [ ] **Step 2: Run it and check it fails.** Expected: `TypeError: unexpected keyword 'profile_hash'`.

- [ ] **Step 3: Implement.** In `jobs_needing_score`, extend spec 2's `fresh` clause and add the exclude:
```python
    fresh = "" if force else """AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id
                                    AND s.rubric_version = :rv AND s.jd_hash = j.jd_hash
                                    AND (:ph IS NULL OR s.profile_hash = :ph))"""
    skip = f"AND j.id NOT IN ({','.join(str(int(i)) for i in exclude)})" if exclude else ""
    sql = f"SELECT j.*, uj.prescore AS uj_prescore FROM jobs j {_UJ} WHERE uj.filter_reason IS NULL {fresh} {skip} {tail}"
    params = {"u": user_id, "rv": rubric_version, "limit": limit, "ph": profile_hash}
```
Spec 2's `_UJ` is a LEFT JOIN, so jobs with no `user_jobs` row still come back. For the pipeline, a job must have been evaluated first: add `AND uj.job_id IS NOT NULL` **only when `profile_hash` is given**. That's the pipeline call, so old callers keep their behaviour.

- [ ] **Step 4: Run the tests.** Expected: PASS, green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/db/jobs.py tests/test_db_jobs.py && git commit -m "feat(db): profile_hash-aware score freshness and per-run exclusions"`

---

### Task 10: Round-robin scoring

**Files:**
- Create: `src/jobseeker/pipeline/score.py`
- Test: `tests/test_score_round_robin.py` (new)

**Interfaces:**
- Consumes: Task 9; spec 2's `Budget`, `Limit`, `ensure_application`, `save_score`; `transition`, `get_status`.
- Produces:
  - `UserStats(evaluated=0, filtered=0, below_cutoff=0, candidates=0, scored=0, shortlisted=0, drafted=0, score_share_left=0, stopped_by="", errors=[])`;
  - `Scorer(user_id, prefs, facts, profile_hash, stats: UserStats, force=False)` (dataclass with `room`, `cap_reason`, `done: set[int]`);
  - `score_round_robin(conn, scorers: list[Scorer], llm, rubric, cfg, now, heartbeat=lambda: None) -> str | None` (the global stop reason).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_score_round_robin.py
from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.jobs import set_prescore, upsert_job
from jobseeker.llm import LLMQuotaExceeded, LLMUnavailable
from jobseeker.pipeline.score import Scorer, UserStats, score_round_robin
from jobseeker.scoring.scorer import LLMScore
from tests.factories import make_job
from tests.fakes import FakeLLM

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)
SCORE = dict(role_family="pa", required_years=2, role_fit=30, experience_fit=25, skills_match=15, company=15,
             location_pay=7, matches=["SQL"], gaps=[])


def _setup(tmp_path, users=(1, 2, 3), jobs_per_user=12):
    conn = connect(tmp_path / "db")
    for u in users:
        if u != 1:
            conn.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, 't')", (u, f"u{u}@x"))
    for i in range(jobs_per_user):
        j, _ = upsert_job(conn, make_job(source_job_id=f"j{i}", fingerprint=f"f{i}", jd_text="SQL"), NOW)
        for u in users:
            set_prescore(conn, u, j, 100 - i)
    conn.commit()
    return conn


def _cfg(global_scores=150, per_run=80, batch=5):
    from jobseeker.config import AppConfig
    cfg = AppConfig()
    cfg.budgets.global_scores_per_day, cfg.budgets.score_per_run, cfg.budgets.score_batch = global_scores, per_run, batch
    return cfg


def _scorers(prefs, facts, users=(1, 2, 3), force=False):
    return [Scorer(u, prefs, facts, "h", UserStats(), force=force) for u in users]


def test_batches_interleave(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path)
    order = []
    llm = FakeLLM(handler=lambda schema, prompt: SCORE)
    import jobseeker.pipeline.score as score_mod
    real = score_mod.save_score
    score_mod_save = lambda conn, uid, *a, **k: order.append(uid) or real(conn, uid, *a, **k)  # noqa: E731
    score_mod.save_score = score_mod_save
    try:
        score_round_robin(conn, _scorers(prefs, facts), llm, rubric, _cfg(global_scores=30), NOW)
    finally:
        score_mod.save_score = real
    assert order[:15] == [1] * 5 + [2] * 5 + [3] * 5


def test_share_and_global_cap(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path)
    scorers = _scorers(prefs, facts)
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(global_scores=30), NOW)
    assert [s.stats.scored for s in scorers] == [10, 10, 10]  # share = 30 // 3, no pooling
    assert all(s.stats.stopped_by == "share" for s in scorers)


def test_stop_reasons_are_precise(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1, 2), jobs_per_user=3)
    scorers = _scorers(prefs, facts, users=(1, 2))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(per_run=2), NOW)
    assert [s.stats.stopped_by for s in scorers] == ["run_cap", "run_cap"]
    scorers = _scorers(prefs, facts, users=(1, 2))
    score_round_robin(conn, scorers, FakeLLM(handler=lambda s, p: SCORE), rubric, _cfg(), NOW)
    assert [s.stats.stopped_by for s in scorers] == ["no_candidates", "no_candidates"]


def test_quota_and_unavailable_stop_everyone(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path)
    def quota(schema, prompt):
        raise LLMQuotaExceeded("gone")
    scorers = _scorers(prefs, facts)
    assert score_round_robin(conn, scorers, FakeLLM(handler=quota), rubric, _cfg(), NOW) == "quota"
    assert {s.stats.stopped_by for s in scorers} == {"quota"}
    def down(schema, prompt):
        raise LLMUnavailable("down")
    assert score_round_robin(conn, _scorers(prefs, facts), FakeLLM(handler=down), rubric, _cfg(), NOW) == "unavailable"


def test_force_scores_each_job_once(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1,), jobs_per_user=4)
    llm = FakeLLM(handler=lambda s, p: SCORE)
    (s,) = _scorers(prefs, facts, users=(1,), force=True)
    score_round_robin(conn, [s], llm, rubric, _cfg(), NOW)
    assert s.stats.scored == 4 and s.stats.stopped_by == "no_candidates"


def test_apply_shortlists_new_application(tmp_path, prefs, facts, rubric):
    conn = _setup(tmp_path, users=(1,), jobs_per_user=1)
    (s,) = _scorers(prefs, facts, users=(1,))
    score_round_robin(conn, [s], FakeLLM(handler=lambda sc, p: SCORE), rubric, _cfg(), NOW)
    assert conn.execute("SELECT status FROM applications WHERE user_id = 1").fetchone()[0] in ("shortlisted", "new")
    assert s.stats.shortlisted == (1 if conn.execute("SELECT recommendation FROM scores").fetchone()[0] == "apply" else 0)
```

- [ ] **Step 2: Run it and check it fails.** Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/jobseeker/pipeline/score.py
"""Stage 6: score in batches of N per user, round-robin, inside each user's daily share and the global cap."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from jobseeker.clock import app_now
from jobseeker.db.applications import ensure_application, get_status, transition
from jobseeker.db.jobs import job_from_row, jobs_needing_score, save_score
from jobseeker.db.usage import Budget, Limit
from jobseeker.llm import LLMError, LLMQuotaExceeded, LLMUnavailable
from jobseeker.scoring.scorer import score_job


@dataclass
class UserStats:
    evaluated: int = 0
    filtered: int = 0
    below_cutoff: int = 0
    candidates: int = 0
    scored: int = 0
    shortlisted: int = 0
    drafted: int = 0
    score_share_left: int = 0
    stopped_by: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class Scorer:
    user_id: int
    prefs: object
    facts: object
    profile_hash: str
    stats: UserStats
    force: bool = False
    room: int = 0
    cap_reason: str = "share"
    done: set[int] = field(default_factory=set)
    budget: Budget | None = None


def _prepare(conn, scorers: list[Scorer], cfg, now: datetime) -> None:
    b = cfg.budgets
    share = b.global_scores_per_day // max(1, len(scorers))
    for s in scorers:
        s.budget = Budget(conn, s.user_id, {"score": Limit("day", b.global_scores_per_day, share)}, app_now(now))
        left = max(0, share - int(s.budget.used("score")))
        s.room = min(b.score_per_run, left)
        s.cap_reason = "run_cap" if b.score_per_run < left else "share"
        s.stats.score_share_left = left


def score_round_robin(conn, scorers: list[Scorer], llm, rubric, cfg, now: datetime,
                      heartbeat: Callable[[], None] = lambda: None) -> str | None:
    _prepare(conn, scorers, cfg, now)
    active = []
    for s in scorers:
        if s.room > 0:
            active.append(s)
        else:
            s.stats.stopped_by = "share"
    stop: str | None = None
    while active and stop is None:
        for s in list(active):
            n = min(cfg.budgets.score_batch, s.room)
            rows = jobs_needing_score(conn, s.user_id, rubric.version, n, force=s.force, with_jd=True,
                                      profile_hash=s.profile_hash, exclude=s.done)
            if not rows:
                s.stats.stopped_by = "no_candidates"
                active.remove(s)
                continue
            for row in rows:
                if not s.budget.can("score"):
                    stop = "global_cap" if s.budget.used_all("score") + 1 > s.budget.limits["score"].global_cap \
                        else None
                    s.stats.stopped_by = stop or "share"
                    break
                s.done.add(row["id"])
                try:
                    result = score_job(llm, job_from_row(row), s.facts, s.prefs, rubric, cfg.models.scoring)
                except LLMQuotaExceeded as e:
                    stop = "quota"
                    s.stats.errors.append(f"scoring stopped: {e}")
                    break
                except LLMUnavailable as e:
                    stop = "unavailable"
                    s.stats.errors.append(f"scoring stopped: {e}")
                    break
                except LLMError as e:
                    s.stats.errors.append(f"score job {row['id']}: {e}")
                    continue
                model = getattr(llm, "last_model", None) or cfg.models.scoring
                save_score(conn, s.user_id, row["id"], result, model, rubric.version, row["jd_hash"],
                           profile_hash=s.profile_hash)
                s.budget.spend("score")
                s.room -= 1
                s.stats.scored += 1
                s.stats.score_share_left -= 1
                app_id = ensure_application(conn, s.user_id, row["id"], now)
                if result.recommendation == "apply" and get_status(conn, app_id) == "new":
                    transition(conn, app_id, "shortlisted", {"score": result.score}, now)
                    s.stats.shortlisted += 1
            heartbeat()
            if stop:
                break
            if s.stats.stopped_by:
                active.remove(s)
            elif s.room <= 0:
                s.stats.stopped_by = s.cap_reason
                active.remove(s)
    if stop:
        for s in scorers:
            if not s.stats.stopped_by or s in active:
                s.stats.stopped_by = stop
    return stop
```

- [ ] **Step 4: Run the tests.** Expected: PASS. In `test_batches_interleave`, patching the module attribute works because `score.py` calls `save_score` through its module global. Green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/pipeline/score.py tests/test_score_round_robin.py && git commit -m "feat(pipeline): round-robin scoring with per-user shares and the global cap"`

---

### Task 11: Round-robin drafting

**Files:**
- Create: `src/jobseeker/pipeline/draft.py`; `draft_application` moves here from `run.py:51-62`, unchanged except that it receives the user's prefs and facts.
- Test: `tests/test_draft_round_robin.py` (new)

**Interfaces:**
- Produces:
  - `drafts_enabled(user) -> bool` (until spec 5: `user.is_admin`);
  - `apps_needing_drafts(conn, user_id, limit, exclude) -> list[int]`;
  - `Drafter(user_id, prefs, facts, stats)`;
  - `draft_round_robin(conn, drafters, llm, cfg, now, heartbeat=lambda: None) -> str | None`;
  - `draft_application(conn, app_id, llm, facts, prefs, now=None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_draft_round_robin.py
from datetime import UTC, datetime

from jobseeker.db.applications import ensure_application, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import save_score, upsert_job
from jobseeker.db.users import User
from jobseeker.models import ScoreResult
from jobseeker.outreach.drafter import DraftBundle
from jobseeker.pipeline.draft import Drafter, draft_round_robin, drafts_enabled
from jobseeker.pipeline.score import UserStats
from tests.factories import make_job
from tests.fakes import FakeLLM
from tests.test_run import DRAFT

NOW = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)


def _shortlist(conn, user_id, n):
    for i in range(n):
        j, _ = upsert_job(conn, make_job(source_job_id=f"{user_id}-{i}", fingerprint=f"f{user_id}{i}"), NOW)
        save_score(conn, user_id, j, ScoreResult(score=90 - i, breakdown={}, matches=[], gaps=[], recommendation="apply",
                                                 role_family="x"), "m", "v1", "h")
        transition(conn, ensure_application(conn, user_id, j, NOW), "shortlisted")


def test_only_admin_drafts_until_outreach_lands():
    assert drafts_enabled(User(1, "o@x", "O", True, None)) and not drafts_enabled(User(2, "r@x", "R", False, None))


def test_two_per_user_round_robin_within_share(tmp_path, prefs, facts):
    from jobseeker.config import AppConfig

    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'r@x', 't')")
    _shortlist(conn, 1, 5)
    _shortlist(conn, 2, 5)
    cfg = AppConfig()
    cfg.budgets.global_drafts_per_day = 6
    order = []
    llm = FakeLLM(handler=lambda schema, prompt: order.append(1) or DRAFT)
    drafters = [Drafter(u, prefs, facts, UserStats()) for u in (1, 2)]
    draft_round_robin(conn, drafters, llm, cfg, NOW)
    assert [d.stats.drafted for d in drafters] == [3, 3]  # share = 6 // 2
    statuses = [r[0] for r in conn.execute("SELECT a.user_id FROM applications a WHERE status = 'drafted' ORDER BY a.id")]
    assert statuses.count(1) == 3 and statuses.count(2) == 3
```

- [ ] **Step 2: Run it and check it fails.** Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/jobseeker/pipeline/draft.py
"""Stage 7: AI drafts for eligible users, best score first, round-robin, inside each user's daily share."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from jobseeker.clock import app_now
from jobseeker.db.applications import get_application, get_status, save_draft, set_suggestion, transition
from jobseeker.db.jobs import get_job, job_from_row
from jobseeker.db.usage import Budget, Limit
from jobseeker.llm import LLMError, LLMQuotaExceeded, LLMUnavailable
from jobseeker.outreach.drafter import draft_outreach


def drafts_enabled(user) -> bool:
    """Until sub-project 5 adds users.outreach_enabled, only the owner (admin) gets AI drafts."""
    return bool(user.is_admin)


def draft_application(conn, app_id: int, llm, facts, prefs, now: datetime | None = None) -> None:
    app = get_application(conn, app_id)
    job = job_from_row(get_job(conn, app["job_id"]))
    result = draft_outreach(llm, job, facts, prefs, prefs.models.drafting)
    b = result.bundle
    save_draft(conn, app_id, "email", b.email_subject, b.email_body)
    save_draft(conn, app_id, "li_note", "", b.li_note)
    save_draft(conn, app_id, "li_dm", "", b.li_dm)
    set_suggestion(conn, app_id, b.contact_role, b.contact_reason, result.linkedin_search_url, result.warnings)
    if get_status(conn, app_id) in ("new", "shortlisted"):
        transition(conn, app_id, "drafted", {"warnings": len(result.warnings)}, now)


def apps_needing_drafts(conn, user_id: int, limit: int, exclude: set[int]) -> list[int]:
    skip = f"AND a.id NOT IN ({','.join(str(int(i)) for i in exclude)})" if exclude else ""
    rows = conn.execute(
        f"""SELECT a.id FROM applications a
            JOIN scores s ON s.id = (SELECT id FROM scores WHERE job_id = a.job_id AND user_id = a.user_id
                                     ORDER BY id DESC LIMIT 1)
            LEFT JOIN user_jobs uj ON uj.user_id = a.user_id AND uj.job_id = a.job_id
            WHERE a.user_id = ? AND a.status = 'shortlisted' {skip}
            ORDER BY s.score DESC, COALESCE(uj.prescore, -1) DESC LIMIT ?""", (user_id, limit)).fetchall()
    return [r["id"] for r in rows]


@dataclass
class Drafter:
    user_id: int
    prefs: object
    facts: object
    stats: object
    room: int = 0
    done: set[int] = field(default_factory=set)
    budget: Budget | None = None


def draft_round_robin(conn, drafters: list[Drafter], llm, cfg, now: datetime,
                      heartbeat: Callable[[], None] = lambda: None) -> str | None:
    b = cfg.budgets
    share = b.global_drafts_per_day // max(1, len(drafters))
    for d in drafters:
        d.budget = Budget(conn, d.user_id, {"draft": Limit("day", b.global_drafts_per_day, share)}, app_now(now))
        d.room = min(b.draft_per_run, max(0, share - int(d.budget.used("draft"))))
    active = [d for d in drafters if d.room > 0]
    stop: str | None = None
    while active and stop is None:
        for d in list(active):
            ids = apps_needing_drafts(conn, d.user_id, min(b.draft_batch, d.room), d.done)
            if not ids:
                active.remove(d)
                continue
            for app_id in ids:
                if not d.budget.can("draft"):
                    active.remove(d)
                    break
                d.done.add(app_id)
                try:
                    draft_application(conn, app_id, llm, d.facts, d.prefs, now)
                except (LLMQuotaExceeded, LLMUnavailable) as e:
                    d.stats.errors.append(f"drafting stopped: {e}")
                    stop = "quota" if isinstance(e, LLMQuotaExceeded) else "unavailable"
                    break
                except LLMError as e:
                    d.stats.errors.append(f"draft application {app_id}: {e}")
                    continue
                d.budget.spend("draft")
                d.room -= 1
                d.stats.drafted += 1
            heartbeat()
            if stop:
                break
            if d in active and d.room <= 0:
                active.remove(d)
    return stop
```

- [ ] **Step 4: Run the tests.** Expected: PASS, green. `run.py` still has its own copy of `draft_application`; Task 12 removes it.

- [ ] **Step 5: Commit** — `git add src/jobseeker/pipeline/draft.py tests/test_draft_round_robin.py && git commit -m "feat(pipeline): round-robin drafting for eligible users within shares"`

---

### Task 12: `run_all`, and replacing `run_daily`

**Files:**
- Modify: `src/jobseeker/pipeline/run.py`. Replace `RunStats`, `_rank`, `_fetch`, `_select`, `_fill_linkedin_descriptions`, `_run`, `run_daily`, `draft_application` and `_apps_needing_drafts` with `run_all` plus `RunReport`.
- Create (only if extras aren't built): `src/jobseeker/push/notify.py` and `src/jobseeker/backup/nightly.py` stubs with the exact signatures from the Dependencies section.
- Modify: `src/jobseeker/web/onboarding.py`'s `first_evaluation` (spec 3) stays on `reevaluate`; nothing to change there.
- Modify tests: `tests/test_run.py`, `tests/test_run_discovery.py`, `tests/test_run_notes.py`
- Test: `tests/test_run_all.py` (new)

**Interfaces:**
- Consumes: Tasks 2 and 4–11; spec 3's `load_user_context(conn, user_id, cfg)` (the default `context`); extras' `notify_new_matches`.
- Produces:
  - `RunReport(fetch_run_id: int | None, fetch: FetchStats | None, users: dict[int, UserStats], aborted: str | None)`;
  - `run_all(conn, *, users, trigger, fetch, plan_cap, client, llm, cfg, rubric, now, companies=(), describe=None, sources_factory=build_sources, context=None, notify=…, force_users=frozenset(), heartbeat=lambda: None, clock=lambda: datetime.now(UTC)) -> RunReport`. `context(conn, user_id) -> (Preferences, Facts | None)` defaults to spec 3's `load_user_context(conn, user_id, cfg)`.

- [ ] **Step 1: Write the golden test FIRST, against today's `run_daily`, and record its output**

```python
# tests/test_run_all.py
from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.users import user_by_id
from tests.fakes import FakeLLM
from tests.test_run import DRAFT, SCORE, StaticSource, handler, raw

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)

GOLDEN_JOBS = [raw(source_job_id=str(i), title=t, apply_url=f"https://jobs.lever.co/cred/{i}")
               for i, t in enumerate(["Senior Product Analyst", "Product Analyst", "Software Engineer",
                                      "Growth Analyst", "Data Scientist"])]


def owner_outcome(conn):
    verdicts = [tuple(r) for r in conn.execute(
        "SELECT j.source_job_id, uj.filter_reason IS NULL FROM user_jobs uj JOIN jobs j ON j.id = uj.job_id "
        "WHERE uj.user_id = 1 ORDER BY j.source_job_id")]
    shortlist = [r[0] for r in conn.execute(
        "SELECT j.source_job_id FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.user_id = 1 "
        "AND a.status IN ('shortlisted', 'drafted') ORDER BY j.source_job_id")]
    scored = [r[0] for r in conn.execute(
        "SELECT j.source_job_id FROM scores s JOIN jobs j ON j.id = s.job_id WHERE s.user_id = 1 ORDER BY s.id")]
    return verdicts, shortlist, scored
```

Before writing `run_all`, run `run_daily` on `GOLDEN_JOBS` with the owner's `prefs`, `rubric` and `facts`, and print `owner_outcome(conn)`. Run it as a one-off: `FORCE_COLOR= uv run python -c "…"`, or a temporary test with `print` plus `-s`. Paste the three lists into the file as `GOLDEN = (…)`.

**This is the frozen expectation.** The scored order in it is the owner's prescore order.

- [ ] **Step 2: Write the remaining failing tests** (same file):

```python
def _cfg(prefs):
    """The fixture AppConfig equivalent of the owner's prefs (spec 3's app.example.yaml has the same values)."""
    from jobseeker.config import REPO_ROOT, load_app_config
    return load_app_config(REPO_ROOT / "config" / "app.example.yaml")


def _run(conn, prefs, rubric, facts, *, users, trigger="cli", notify=None, sources=GOLDEN_JOBS, llm=None):
    from jobseeker.pipeline.run import run_all
    calls = []
    report = run_all(conn, users=users, trigger=trigger, fetch=True, plan_cap=60, client=None,
                     llm=llm or FakeLLM(handler=handler), cfg=_cfg(prefs), rubric=rubric, now=NOW,
                     describe=lambda s, i: "",
                     sources_factory=lambda *a, **k: [StaticSource("lever:cred", list(sources))],
                     context=lambda conn, uid: (prefs, facts),
                     notify=notify or (lambda c, uid, started, now: calls.append((uid, started, c.in_transaction)) or None))
    return report, calls


def test_golden_owner_alone_matches_run_daily(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)])
    assert report.aborted is None
    assert owner_outcome(conn) == GOLDEN


def test_runs_rows_link_user_to_fetch(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule")
    fetch = conn.execute("SELECT * FROM runs WHERE kind = 'fetch'").fetchone()
    user = conn.execute("SELECT * FROM runs WHERE kind = 'user'").fetchone()
    assert fetch["trigger"] == "schedule" and fetch["user_id"] is None and fetch["finished_at"]
    assert user["parent_id"] == fetch["id"] and user["user_id"] == 1 and user["finished_at"]


def test_notify_called_after_scoring_outside_transactions(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    _, calls = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule")
    assert len(calls) == 1 and calls[0][0] == 1 and calls[0][2] is False
    _, calls = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="cli")
    assert calls == []


def test_notify_failure_becomes_a_note(tmp_path, prefs, rubric, facts):
    conn = connect(tmp_path / "db")
    def boom(*a):
        raise RuntimeError("x")
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule", notify=boom)
    assert "Couldn't send the match alert" in report.users[1].errors and report.aborted is None
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)], trigger="schedule",
                     notify=lambda *a: "Couldn't send the match alert")
    assert report.users[1].errors.count("Couldn't send the match alert") == 1


def test_user_without_facts_is_skipped(tmp_path, prefs, rubric, facts):
    from jobseeker.pipeline.run import run_all
    conn = connect(tmp_path / "db")
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'roomie@example.com', 't')")
    conn.commit()
    report = run_all(conn, users=[user_by_id(conn, 1), user_by_id(conn, 2)], trigger="cli", fetch=True, plan_cap=60,
                     client=None, llm=FakeLLM(handler=handler), cfg=_cfg(prefs), rubric=rubric, now=NOW,
                     describe=lambda s, i: "", sources_factory=lambda *a, **k: [StaticSource("lever:cred", GOLDEN_JOBS)],
                     context=lambda conn, uid: (prefs, facts if uid == 1 else None), notify=lambda *a: None)
    assert report.aborted is None and report.users[1].scored > 0
    assert report.users[2].errors == ["No resume facts yet, so nothing was scored"]


def test_crash_closes_every_run_row(tmp_path, prefs, rubric, facts, monkeypatch):
    conn = connect(tmp_path / "db")
    monkeypatch.setattr("jobseeker.pipeline.run.score_round_robin", lambda *a, **k: 1 / 0)
    report, _ = _run(conn, prefs, rubric, facts, users=[user_by_id(conn, 1)])
    assert report.aborted.startswith("run aborted: ZeroDivisionError")
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE finished_at IS NULL").fetchone()[0] == 0
```

- [ ] **Step 3: Run them and check they fail.** Expected: ImportError `run_all` (the golden test fails the same way).

- [ ] **Step 4: Implement `run_all`** (replace the body of `src/jobseeker/pipeline/run.py`):

```python
"""The daily run, for everyone: fetch once, then evaluate, describe, score and draft per user, fairly."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from jobseeker.db.locks import LockLost
from jobseeker.db.runs import finish_run, start_run
from jobseeker.llm import FallbackLLM
from jobseeker.pipeline.describe import describe_shared
from jobseeker.pipeline.discovery import GENERIC_WORDS
from jobseeker.pipeline.draft import Drafter, draft_round_robin, drafts_enabled
from jobseeker.pipeline.evaluate import evaluate
from jobseeker.pipeline.fetch import FetchStats, fetch_shared
from jobseeker.pipeline.normalize import normalize_title
from jobseeker.pipeline.plan import build_plan, plan_users
from jobseeker.pipeline.profile_hash import profile_hash
from jobseeker.pipeline.score import Scorer, UserStats, score_round_robin
from jobseeker.db.jobs import linkedin_picks
from jobseeker.sources.registry import build_sources

ALERT_NOTE = "Couldn't send the match alert"
NO_FACTS = "No resume facts yet, so nothing was scored"


@dataclass
class RunReport:
    fetch_run_id: int | None = None
    fetch: FetchStats | None = None
    users: dict[int, UserStats] = field(default_factory=dict)
    aborted: str | None = None




def _default_notify(conn, user_id, started, now):
    from jobseeker.push.notify import notify_new_matches
    return notify_new_matches(conn, user_id, started, now)


def _custom_and_updated(conn, user_id: int) -> tuple[str, str]:
    row = conn.execute("SELECT json_extract(data, '$.custom_role') AS c, updated_at FROM user_prefs WHERE user_id = ?",
                       (user_id,)).fetchone()
    return ((row["c"] or ""), row["updated_at"]) if row else ("", "")


def run_all(conn, *, users, trigger: str, fetch: bool, plan_cap: int, client, llm, cfg, rubric, now: datetime,
            companies=(), describe=None, sources_factory=build_sources, context=None,
            notify=_default_notify, force_users: frozenset[int] = frozenset(),
            heartbeat: Callable[[], None] = lambda: None,
            clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> RunReport:
    if describe is None:
        from jobseeker.sources.jobspy_source import fetch_description as describe
    llm = FallbackLLM(llm, cfg.models.fallbacks)  # one chain for the whole run
    if context is None:
        from jobseeker.db.profile import load_user_context
        context = lambda c, uid: load_user_context(c, uid, cfg)  # noqa: E731
    report = RunReport(users={u.id: UserStats() for u in users})
    user_runs: dict[int, int] = {}
    contexts: dict[int, tuple] = {}
    try:
        for u in users:
            prefs, facts = context(conn, u.id)
            if facts is None:
                report.users[u.id].errors.append(NO_FACTS)
            else:
                contexts[u.id] = (prefs, facts)
        if fetch:
            from jobseeker.db.companies import active_companies
            run_no = conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'fetch'").fetchone()[0]
            report.fetch_run_id = start_run(conn, now, None, kind="fetch", trigger=trigger)
            report.fetch = FetchStats()
            catalog = {r.query for r in cfg.roles}
            planners = plan_users([(uid, p, *_custom_and_updated(conn, uid)) for uid, (p, _) in contexts.items()])
            plan = build_plan(planners, list(cfg.search.sites), catalog, run_no, plan_cap, cfg.search.max_custom_queries)
            report.fetch.searches_planned, report.fetch.searches_trimmed = plan.planned, plan.trimmed
            words = GENERIC_WORDS | {w for q in plan.linkedin + [q for q, _ in plan.pairs] for w in normalize_title(q).split()}
            sources = sources_factory(list(companies), active_companies(conn), cfg.search, plan)
            fetch_shared(conn, sources, client, now, words, report.fetch, heartbeat)
        for u in users:
            user_runs[u.id] = start_run(conn, now, u.id, kind="user", trigger=trigger, parent_id=report.fetch_run_id)
        for uid, (prefs, facts) in contexts.items():
            ev = evaluate(conn, uid, prefs, facts, now, heartbeat)
            st = report.users[uid]
            st.evaluated, st.filtered, st.below_cutoff = ev.evaluated, ev.filtered, ev.below_cutoff
        if fetch and contexts:
            cap = cfg.search.linkedin_descriptions_per_run
            d = describe_shared(conn, [linkedin_picks(conn, uid, cap) for uid in contexts], cap, describe, heartbeat)
            report.fetch.described = d.described
            report.fetch.errors += d.errors
            for uid, (prefs, facts) in contexts.items():
                evaluate(conn, uid, prefs, facts, now, heartbeat)  # picks up changed jd_hash only
        scorers = [Scorer(uid, p, f, profile_hash(p, f), report.users[uid], force=uid in force_users)
                   for uid, (p, f) in contexts.items()]
        stop = score_round_robin(conn, scorers, llm, rubric, cfg, now, heartbeat)
        if trigger in ("schedule", "fetch_now"):
            for uid in contexts:
                started = conn.execute("SELECT started_at FROM runs WHERE id = ?", (user_runs[uid],)).fetchone()[0]
                try:
                    note = notify(conn, uid, datetime.fromisoformat(started), now)
                except Exception:
                    note = ALERT_NOTE
                if note:
                    report.users[uid].errors.append(note)
        same_model = cfg.models.drafting == cfg.models.scoring
        if not (stop == "unavailable" or (stop == "quota" and same_model)):
            eligible = [u for u in users if u.id in contexts and drafts_enabled(u)]
            drafters = [Drafter(u.id, *contexts[u.id], report.users[u.id]) for u in eligible]
            draft_round_robin(conn, drafters, llm, cfg, now, heartbeat)
    except LockLost:
        report.aborted = "run superseded"
    except Exception as e:  # the run log must always be closed
        report.aborted = f"run aborted: {type(e).__name__}: {e}"
    finally:
        end = clock()
        if report.fetch_run_id is not None:
            data = asdict(report.fetch)
            errors = data.pop("errors") + ([report.aborted] if report.aborted else [])
            finish_run(conn, report.fetch_run_id, data, errors, end)
        for uid, run_id in user_runs.items():
            data = asdict(report.users[uid])
            errors = data.pop("errors") + ([report.aborted] if report.aborted else [])
            finish_run(conn, run_id, data, errors, end)
    return report
```

`cfg.roles` holds spec 3's `Role(label, query, allow)` entries. The existing `build_sources(companies, discovered, search)` gains `plan` (Task 6), so `sources_factory(list(companies), …, cfg.search, plan)` matches it positionally.

**If extras aren't built yet,** create stubs:
- `src/jobseeker/push/notify.py`, with `def notify_new_matches(conn, user_id, run_started_at, now): return None`;
- `src/jobseeker/backup/nightly.py`, with `BackupResult` as in the extras plan and `def nightly_backup(conn, settings, now, force=False): return BackupResult(None, True, False, None, True)`.

Add `__init__.py` files as needed.

- [ ] **Step 5: Move the old suites to `run_all`**

- **`tests/test_run.py`:** replace the module helper `_run(conn, sources, llm, prefs, rubric, facts)` with:
  ```python
  def _run(conn, sources, llm, prefs, rubric, facts):
      from jobseeker.db.users import user_by_id
      from jobseeker.pipeline.run import run_all
      from tests.test_run_all import _cfg
      report = run_all(conn, users=[user_by_id(conn, 1)], trigger="cli", fetch=True, plan_cap=60, client=None, llm=llm,
                       cfg=_cfg(prefs), rubric=rubric, now=NOW, describe=lambda s, i: "",
                       sources_factory=lambda *a, **k: list(sources), context=lambda c, uid: (prefs, facts),
                       notify=lambda *a: None)
      return report
  ```
  Map each assertion as follows:
  - `stats.fetched/new/duplicates/discovered` → `report.fetch.<field>`;
  - `stats.filtered/below_cutoff/scored/shortlisted/drafted/candidates` → `report.users[1].<field>`;
  - `stats.errors` → `report.fetch.errors + report.users[1].errors`.

  Tests that called `run_daily(..., fetch=False, force_rescore=True)` become `run_all(..., fetch=False, force_users=frozenset({1}))`. `last_run(conn, 1)` keeps working (it now returns the user run).
- **`tests/test_run_discovery.py`:** the same helper swap. Its `bump_jobs_seen` expectations change by definition (spec §4.3: every new job counts, not only those passing the owner's prefilter). Update the expected counts and note the definition change in a comment.
- **`tests/test_run_notes.py`:** unchanged apart from the `client_as` switch done by spec 2.
- **`tests/test_db_jobs.py`:** tests for spec 2's `set_filter_reason`/`set_prescore` stay; nothing here uses `run_daily`.

Then delete `run_daily` and the old helpers from `run.py`, and check that nothing references them: `grep -rn "run_daily\|_apps_needing_drafts\|RunStats" src tests` returns nothing.

- [ ] **Step 6: Run the tests:** `FORCE_COLOR= uv run pytest --color=no tests/test_run_all.py tests/test_run.py tests/test_run_discovery.py tests/test_run_notes.py`, then the full suite. Expected: PASS, with the golden test equal to the frozen `run_daily` output. Green.

- [ ] **Step 7: Commit** — `git add -A src/jobseeker/pipeline src/jobseeker/push src/jobseeker/backup tests/test_run_all.py tests/test_run.py tests/test_run_discovery.py && git commit -m "feat(pipeline): run_all replaces run_daily (fetch once, fair per-user stages, alerts after scoring)"`

---

### Task 13: `jobseeker tick`, `run`, `rescore`, backup and ping

**Files:**
- Create: `src/jobseeker/pipeline/tick.py`, `src/jobseeker/db/run_requests.py`
- Modify: `src/jobseeker/cli.py` (`tick`; `run [--user EMAIL] [--no-fetch]`; `rescore --user EMAIL`; `_run` is removed; `run` no longer calls `backup`)
- Test: `tests/test_tick.py` (new), `tests/test_cli_run.py` (new)

**Interfaces:**
- Produces:
  - `run_requests.py`: `queue(conn, user_id, now) -> int`, `next_queued(conn) -> dict | None`, `mark(conn, req_id, status, now, run_id=None)`, `fail_stuck(conn, now, minutes) -> int`, `last_fetch_now_started(conn, user_id) -> str | None`, `fetch_now_count_today(conn, now) -> int`, `pending(conn, user_id) -> dict | None`;
  - `tick.py`: `active_users(conn) -> list[User]`, `scheduled_due(conn, cfg, now) -> bool`, `ping(url, ok, get=httpx.get) -> None`, `tick(conn, *, settings, cfg, now, run, backup=nightly_backup, ping_fn=ping, holder) -> str`, which returns `busy`, `scheduled`, `fetch_now` or `idle`. Here `run(trigger, users, plan_cap) -> RunReport`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tick.py
from datetime import UTC, datetime, timedelta

from jobseeker.backup.nightly import BackupResult
from jobseeker.config import AppConfig
from jobseeker.db.core import connect
from jobseeker.db.locks import acquire
from jobseeker.db.runs import finish_run, start_run
from jobseeker.pipeline.run import RunReport
from jobseeker.pipeline.tick import scheduled_due, tick

CFG = AppConfig()
OK = BackupResult(None, True, True, None)


def _db(tmp_path):
    conn = connect(tmp_path / "db")
    conn.execute("UPDATE user_prefs SET onboarded_at = 't' WHERE user_id = 1")  # the owner is active
    conn.commit()
    return conn


def _tick(conn, now, *, report=None, backup=lambda c, s, n: OK, pings=None, runs=None):
    def run(trigger, users, plan_cap):
        (runs if runs is not None else []).append((trigger, [u.id for u in users], plan_cap))
        rid = start_run(conn, now, None, kind="fetch", trigger=trigger)
        finish_run(conn, rid, {}, [], now)
        return report or RunReport(fetch_run_id=rid)
    return tick(conn, settings=None, cfg=CFG, now=now, run=run, backup=backup,
                ping_fn=lambda url, ok: (pings if pings is not None else []).append(ok), holder="me:1")


def test_schedule_due_in_ist(tmp_path):
    conn = _db(tmp_path)
    assert not scheduled_due(conn, CFG, datetime(2026, 10, 11, 5, 44, tzinfo=UTC))
    assert scheduled_due(conn, CFG, datetime(2026, 10, 11, 5, 45, tzinfo=UTC))
    assert scheduled_due(conn, CFG, datetime(2026, 10, 11, 17, 30, tzinfo=UTC))  # catch-up after downtime
    rid = start_run(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), None, kind="fetch", trigger="schedule")
    finish_run(conn, rid, {}, [], datetime(2026, 10, 11, 6, 30, tzinfo=UTC))
    assert not scheduled_due(conn, CFG, datetime(2026, 10, 11, 7, 0, tzinfo=UTC))
    assert scheduled_due(conn, CFG, datetime(2026, 10, 12, 5, 50, tzinfo=UTC))  # next IST day


def test_crashed_attempts_retry_at_most_twice(tmp_path):
    conn = _db(tmp_path)
    t = datetime(2026, 10, 11, 5, 45, tzinfo=UTC)
    start_run(conn, t, None, kind="fetch", trigger="schedule")  # crashed: never finished
    assert scheduled_due(conn, CFG, t + timedelta(minutes=30))
    start_run(conn, t + timedelta(minutes=30), None, kind="fetch", trigger="schedule")
    assert not scheduled_due(conn, CFG, t + timedelta(hours=2))


def test_scheduled_tick_runs_backup_and_pings(tmp_path):
    conn = _db(tmp_path)
    runs, pings = [], []
    assert _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), runs=runs, pings=pings) == "scheduled"
    assert runs == [("schedule", [1], 60)] and pings == [True]


def test_failed_run_still_backs_up_and_pings_fail(tmp_path):
    conn = _db(tmp_path)
    backups, pings = [], []
    _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), report=RunReport(aborted="run aborted: X"),
          backup=lambda c, s, n: backups.append(1) or OK, pings=pings)
    assert backups == [1] and pings == [False]


def test_backup_not_ok_or_raising_pings_fail(tmp_path):
    for backup in (lambda c, s, n: BackupResult(None, False, False, "HTTP 500"),
                   lambda c, s, n: (_ for _ in ()).throw(OSError("disk"))):
        conn = _db(tmp_path / str(id(backup)))
        pings = []
        _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), backup=backup, pings=pings)
        assert pings == [False]


def test_skipped_backup_counts_as_ok(tmp_path):
    conn = _db(tmp_path)
    pings = []
    _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC), backup=lambda c, s, n: BackupResult(None, True, True, None, True),
          pings=pings)
    assert pings == [True]


def test_fetch_now_runs_one_user_without_backup_or_ping(tmp_path):
    from jobseeker.db.run_requests import queue
    conn = _db(tmp_path)
    now = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)  # before 11:15 IST, so nothing scheduled
    queue(conn, 1, now)
    runs, pings, backups = [], [], []
    assert _tick(conn, now, runs=runs, pings=pings, backup=lambda c, s, n: backups.append(1) or OK) == "fetch_now"
    assert runs == [("fetch_now", [1], 30)] and pings == [] and backups == []
    assert conn.execute("SELECT status FROM run_requests").fetchone()[0] == "done"


def test_busy_lock_exits_quietly(tmp_path):
    conn = _db(tmp_path)
    acquire(conn, "run", "other:2", datetime(2026, 10, 11, 5, 40, tzinfo=UTC), 15)
    assert _tick(conn, datetime(2026, 10, 11, 5, 45, tzinfo=UTC)) == "busy"


def test_stuck_running_request_is_failed_after_takeover(tmp_path):
    from jobseeker.db.run_requests import mark, queue
    conn = _db(tmp_path)
    t = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)
    mark(conn, queue(conn, 1, t), "running", t)
    _tick(conn, t + timedelta(minutes=20))
    assert conn.execute("SELECT status FROM run_requests").fetchone()[0] == "failed"
```

```python
# tests/test_cli_run.py
from datetime import UTC, datetime

from typer.testing import CliRunner

from jobseeker.cli import app
from jobseeker.db.core import connect
from jobseeker.db.locks import acquire


def test_cli_run_refuses_when_locked(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    conn = connect(settings.db_path)
    acquire(conn, "run", "other:2", datetime.now(UTC), 15)
    result = CliRunner().invoke(app, ["run"])
    assert result.exit_code == 1 and "A run is in progress since" in result.output


def test_tick_command_exits_zero_when_busy(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    acquire(connect(settings.db_path), "run", "other:2", datetime.now(UTC), 15)
    result = CliRunner().invoke(app, ["tick"])
    assert result.exit_code == 0 and "busy" in result.output
```

The tests assume a fresh DB has the owner's `user_prefs` row (spec 3 seeds `user_prefs(1)` with `onboarding_step='roles'`). The `UPDATE` in `_db` marks the owner onboarded. If no row exists, `_db` inserts it instead: `INSERT OR IGNORE INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at) VALUES (1, '{}', 1, NULL, 't', 't')`.

- [ ] **Step 2: Run them and check they fail.** Expected: ImportErrors.

- [ ] **Step 3: Implement `run_requests.py`**

```python
# src/jobseeker/db/run_requests.py
"""Fetch-now requests: queued by the web, run by the next tick."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from jobseeker.clock import app_today, day_start_utc
from jobseeker.db.core import iso


def queue(conn: sqlite3.Connection, user_id: int, now: datetime) -> int:
    cur = conn.execute("INSERT INTO run_requests (user_id, requested_at, status) VALUES (?, ?, 'queued')",
                       (user_id, iso(now)))
    conn.commit()
    return cur.lastrowid


def next_queued(conn) -> dict | None:
    row = conn.execute("SELECT * FROM run_requests WHERE status = 'queued' ORDER BY requested_at, id LIMIT 1").fetchone()
    return dict(row) if row else None


def pending(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM run_requests WHERE user_id = ? AND status IN ('queued', 'running') "
                       "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return dict(row) if row else None


def mark(conn, req_id: int, status: str, now: datetime, run_id: int | None = None) -> None:
    done = iso(now) if status in ("done", "failed") else None
    conn.execute("UPDATE run_requests SET status = ?, run_id = COALESCE(?, run_id), finished_at = ? WHERE id = ?",
                 (status, run_id, done, req_id))
    conn.commit()


def fail_stuck(conn, now: datetime, minutes: int) -> int:
    """A 'running' request whose run died (no live lock holder) is closed as failed after the takeover window."""
    cur = conn.execute("UPDATE run_requests SET status = 'failed', finished_at = ? WHERE status = 'running' "
                       "AND requested_at < ?", (iso(now), iso(now - timedelta(minutes=minutes))))
    conn.commit()
    return cur.rowcount


def last_fetch_now_started(conn, user_id: int) -> str | None:
    row = conn.execute("SELECT MAX(started_at) FROM runs WHERE kind = 'user' AND trigger = 'fetch_now' AND user_id = ?",
                       (user_id,)).fetchone()
    return row[0]


def fetch_now_count_today(conn, now: datetime) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'fetch' AND trigger = 'fetch_now' AND started_at >= ?",
                        (iso(day_start_utc(app_today(now))),)).fetchone()[0]
```

`fail_stuck` is called only by a tick that **holds** the lock. So any request still `running` belongs to a dead run, and the age check (by `requested_at`) is a safety margin.

- [ ] **Step 4: Implement `tick.py`**

```python
# src/jobseeker/pipeline/tick.py
"""The only host hook: run every 5 minutes. The schedule, catch-up, Fetch now and the nightly backup live here."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from jobseeker.backup.nightly import nightly_backup
from jobseeker.clock import app_now, app_today, day_start_utc
from jobseeker.db import run_requests
from jobseeker.db.applications import wake_snoozed
from jobseeker.db.core import iso
from jobseeker.db.locks import acquire, release
from jobseeker.db.users import user_by_id

log = logging.getLogger(__name__)


def active_users(conn) -> list:
    rows = conn.execute("""SELECT u.id FROM users u JOIN user_prefs p ON p.user_id = u.id
                           WHERE p.onboarded_at IS NOT NULL AND u.disabled_at IS NULL ORDER BY u.id""").fetchall()
    return [user_by_id(conn, r["id"]) for r in rows]


def scheduled_due(conn, cfg, now: datetime) -> bool:
    local = app_now(now)
    if local.time() < cfg.schedule.daily_time():
        return False
    since = iso(day_start_utc(app_today(now)))
    rows = conn.execute("SELECT finished_at FROM runs WHERE kind = 'fetch' AND trigger = 'schedule' AND started_at >= ?",
                        (since,)).fetchall()
    if any(r["finished_at"] for r in rows):
        return False
    return len(rows) < cfg.schedule.max_attempts_per_day


def ping(url: str, ok: bool, get=httpx.get) -> None:
    if not url:
        return
    try:
        get(url if ok else url.rstrip("/") + "/fail", timeout=5.0)
    except Exception as e:  # a dead pinger must never fail the tick
        log.warning("health ping failed: %s", e)


def tick(conn, *, settings, cfg, now: datetime, run, backup=nightly_backup, ping_fn=None, holder: str) -> str:
    wake_snoozed(conn, now)
    if not acquire(conn, "run", holder, now, cfg.lock.takeover_after_minutes):
        return "busy"
    try:
        run_requests.fail_stuck(conn, now, cfg.lock.takeover_after_minutes)
        if scheduled_due(conn, cfg, now):
            report = run("schedule", active_users(conn), cfg.search.max_searches_per_run)
            try:
                result = backup(conn, settings, now)
                backup_ok = result.ok
            except Exception as e:
                log.error("backup failed: %s", e)
                backup_ok = False
            ok = report.aborted is None and backup_ok
            (ping_fn or (lambda url, good: ping(url, good)))(getattr(settings, "healthcheck_ping_url", ""), ok)
            return "scheduled"
        req = run_requests.next_queued(conn)
        if req:
            run_requests.mark(conn, req["id"], "running", now)
            user = user_by_id(conn, req["user_id"])
            report = run("fetch_now", [user], cfg.search.max_searches_fetch_now)
            run_requests.mark(conn, req["id"], "failed" if report.aborted else "done", now, report.fetch_run_id)
            return "fetch_now"
        return "idle"
    finally:
        release(conn, "run", holder)
```

`ping_fn` gets `(url, ok)`. The tests pass a recorder that ignores the url.

- [ ] **Step 5: Wire the CLI** (`src/jobseeker/cli.py`). Remove `_run` and the old `run`/`rescore`, then add:

```python
def _pipeline(settings, conn):
    """Everything run_all needs on the real system, built once per command."""
    from jobseeker.config import load_app_config, load_companies, load_rubric
    from jobseeker.llm import build_llm

    cfg = load_app_config(settings.app_config_path)
    return cfg, load_rubric(cfg.rubric_path), load_companies(cfg.companies_path), build_llm(settings)


def _runner(settings, conn, now, holder, force_users=frozenset(), fetch=True):
    from jobseeker.db.locks import heartbeat
    from jobseeker.pipeline.run import run_all
    from jobseeker.sources.http import make_client

    cfg, rubric, companies, llm = _pipeline(settings, conn)

    def run(trigger, users, plan_cap):
        with make_client() as client:
            return run_all(conn, users=users, trigger=trigger, fetch=fetch, plan_cap=plan_cap, client=client, llm=llm,
                           cfg=cfg, rubric=rubric, now=now, companies=companies, force_users=force_users,
                           heartbeat=lambda: heartbeat(conn, "run", holder, datetime.now(UTC)))
    return cfg, run


@app.command()
def tick() -> None:
    """Called every 5 minutes by the host: runs the daily schedule, Fetch now requests and the nightly backup."""
    from jobseeker.db.locks import holder_id
    from jobseeker.pipeline.tick import tick as do_tick

    settings, now = Settings(), datetime.now(UTC)
    conn = connect(settings.db_path)
    holder = holder_id()
    cfg, run = _runner(settings, conn, now, holder)
    typer.echo(do_tick(conn, settings=settings, cfg=cfg, now=now, run=run, holder=holder))


@app.command()
def run(user: str = typer.Option("", "--user", help="Only this user's email (default: everyone active)."),
        no_fetch: bool = typer.Option(False, "--no-fetch", help="Skip the job-site fetch.")) -> None:
    """Run the pipeline now, by hand (takes the same lock as tick)."""
    _manual(user, fetch=not no_fetch, force=False)


@app.command()
def rescore(user: str = typer.Option(..., "--user", help="The user's email.")) -> None:
    """Re-score one user's open jobs now (after editing rubric.yaml)."""
    _manual(user, fetch=False, force=True)


def _manual(email: str, fetch: bool, force: bool) -> None:
    from jobseeker.clock import app_now
    from jobseeker.db.locks import acquire, held_since, holder_id, release
    from jobseeker.pipeline.tick import active_users

    settings, now = Settings(), datetime.now(UTC)
    conn = connect(settings.db_path)
    holder = holder_id()
    users = [u for u in active_users(conn) if not email or u.email == email.lower()]
    if email and not users:
        typer.echo(f"No active user {email}", err=True)
        raise typer.Exit(1)
    cfg, run_fn = _runner(settings, conn, now, holder, frozenset(u.id for u in users) if force else frozenset(), fetch)
    if not acquire(conn, "run", holder, now, cfg.lock.takeover_after_minutes):
        since = app_now(datetime.fromisoformat(held_since(conn, "run"))).strftime("%H:%M")
        typer.echo(f"A run is in progress since {since}", err=True)
        raise typer.Exit(1)
    try:
        report = run_fn("cli", users, cfg.search.max_searches_per_run)
    finally:
        release(conn, "run", holder)
    typer.echo(json.dumps({"fetch": report.fetch and asdict(report.fetch),
                           "users": {k: asdict(v) for k, v in report.users.items()}, "aborted": report.aborted},
                          indent=2))
```

Add `from dataclasses import asdict` and `from datetime import UTC, datetime` at the top of `cli.py`.

`cli.py`'s `typer.echo(err=True)` messages land in `result.output` with `CliRunner()`, whose default mixes stderr. If the project's Typer version separates them, assert on `result.stderr` instead.

In `test_cli_run_refuses_when_locked`, the lock is checked **before** `_pipeline` builds anything. Move the `acquire` check above `_runner(...)` in `_manual` if `load_app_config` needs files the test home lacks.

- [ ] **Step 6: Run the tests:** `tests/test_tick.py tests/test_cli_run.py`, then the full suite. Expected: PASS, green.

- [ ] **Step 7: Commit** — `git add src/jobseeker/pipeline/tick.py src/jobseeker/db/run_requests.py src/jobseeker/cli.py tests/test_tick.py tests/test_cli_run.py && git commit -m "feat(pipeline): jobseeker tick with IST schedule, catch-up, Fetch now, backup and ping"`

---

### Task 14: Fetch now (web)

**Files:**
- Create: `src/jobseeker/web/fetch_now.py`, `src/jobseeker/web/templates/_fetch_now.html`
- Modify:
  - `src/jobseeker/web/app.py` (include the router);
  - `templates/today.html` (header area), spec 3's `settings.html` (Account card) and `onboarding/done.html`: `{% include "_fetch_now.html" %}`;
  - each of those routes passes `fetch_now=fetch_now_state(conn, user.id, now, cfg)`.
- Test: `tests/test_web_fetch_now.py` (new)

**Interfaces:**
- Produces:
  - `fetch_now_state(conn, user_id, now, cfg) -> dict` with `{"state": "ready" | "queued" | "running" | "done" | "wait" | "used_up", "text": str, "poll": bool}`;
  - `POST /fetch-now` and `GET /fetch-now/status` (fragment).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_fetch_now.py
from datetime import UTC, datetime, timedelta

from jobseeker.config import AppConfig
from jobseeker.db.core import connect
from jobseeker.db.locks import acquire
from jobseeker.db.runs import finish_run, start_run
from jobseeker.web.fetch_now import fetch_now_state

CFG = AppConfig()
NOW = datetime(2026, 10, 11, 8, 35, tzinfo=UTC)  # 14:05 IST


def test_queue_then_already_queued(client_as, settings):
    c = client_as(1, follow_redirects=False)
    r = c.post("/fetch-now")
    assert r.status_code == 303 and "Queued" in r.headers["location"] or "queued" in r.headers["location"].lower()
    r = c.post("/fetch-now")
    assert "Already%20queued" in r.headers["location"] or "Already queued" in r.headers["location"]
    assert connect(settings.db_path).execute("SELECT COUNT(*) FROM run_requests").fetchone()[0] == 1


def test_wait_two_hours_since_last_start(settings):
    conn = connect(settings.db_path)
    rid = start_run(conn, NOW - timedelta(minutes=30), 1, kind="user", trigger="fetch_now")
    finish_run(conn, rid, {}, [], NOW)
    s = fetch_now_state(conn, 1, NOW, CFG)
    assert s["state"] == "wait" and s["text"] == "Next possible at 15:35"


def test_global_daily_limit(settings):
    conn = connect(settings.db_path)
    for i in range(6):
        start_run(conn, NOW - timedelta(minutes=i), None, kind="fetch", trigger="fetch_now")
    assert fetch_now_state(conn, 2, NOW, CFG)["state"] == "used_up"


def test_queued_while_locked_says_after_current_run(client_as, settings):
    conn = connect(settings.db_path)
    acquire(conn, "run", "x:1", datetime.now(UTC), 15)
    r = client_as(1, follow_redirects=False).post("/fetch-now")
    assert "after the current run" in r.headers["location"].replace("%20", " ")


def test_status_fragment_polls_only_while_pending(client_as):
    c = client_as(1)
    assert 'hx-trigger="every 10s"' not in c.get("/fetch-now/status").text
    c.post("/fetch-now")
    assert 'hx-trigger="every 10s"' in c.get("/fetch-now/status").text


def test_requires_session(anon_client):
    assert anon_client().post("/fetch-now", follow_redirects=False).status_code in (303, 401)
```

- [ ] **Step 2: Run it and check it fails.** Expected: ImportError / 404.

- [ ] **Step 3: Implement**

```python
# src/jobseeker/web/fetch_now.py
"""'Fetch now': the web only queues; the next tick (within 5 minutes) runs it."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from jobseeker.clock import app_now
from jobseeker.db import run_requests
from jobseeker.db.locks import held_since
from jobseeker.web.deps import current_user, get_conn

router = APIRouter(dependencies=[Depends(current_user)])


def fetch_now_state(conn, user_id: int, now: datetime, cfg) -> dict:
    req = run_requests.pending(conn, user_id)
    if req and req["status"] == "queued":
        return {"state": "queued", "text": "Queued, starts in a few minutes", "poll": True}
    if req and req["status"] == "running":
        since = app_now(datetime.fromisoformat(req["requested_at"])).strftime("%H:%M")
        return {"state": "running", "text": f"Running since {since}", "poll": True}
    last = run_requests.last_fetch_now_started(conn, user_id)
    if last:
        nxt = datetime.fromisoformat(last) + timedelta(hours=cfg.fetch_now.min_hours_between_per_user)
        if nxt > now:
            return {"state": "wait", "text": f"Next possible at {app_now(nxt).strftime('%H:%M')}", "poll": False}
    if run_requests.fetch_now_count_today(conn, now) >= cfg.fetch_now.max_per_day:
        return {"state": "used_up", "text": "Fetch now is used up for today", "poll": False}
    return {"state": "ready", "text": "", "poll": False}


def _back(request: Request, msg: str) -> RedirectResponse:
    target = request.headers.get("referer") or "/today"
    path = "/" + target.split("://", 1)[-1].split("/", 1)[-1] if "://" in target else target
    sep = "&" if "?" in path else "?"
    return RedirectResponse(f"{path.split('#')[0]}{sep}msg={quote(msg)}", status_code=303)


@router.post("/fetch-now")
def fetch_now(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    now = datetime.now(UTC)
    cfg = request.app.state.app_config
    state = fetch_now_state(conn, user.id, now, cfg)
    if state["state"] in ("queued", "running"):
        return _back(request, "Already queued")
    if state["state"] in ("wait", "used_up"):
        return _back(request, state["text"])
    run_requests.queue(conn, user.id, now)
    busy = held_since(conn, "run") is not None
    return _back(request, "Queued: starts after the current run" if busy else "Queued, starts in a few minutes")


@router.get("/fetch-now/status")
def status(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    s = fetch_now_state(conn, user.id, datetime.now(UTC), request.app.state.app_config)
    return request.app.state.templates.TemplateResponse(request, "_fetch_now.html", {"fetch_now": s})
```

The referer→path logic only keeps local paths. It reuses the same rule as spec 2's `next` check, so it can't open-redirect. If `web/application.py:31`'s `_back` helper fits as-is, import and use it instead.

`src/jobseeker/web/templates/_fetch_now.html`:
```html
<div class="fetch-now" id="fetch-now" hx-get="/fetch-now/status" hx-swap="outerHTML"
     {% if fetch_now.poll %}hx-trigger="every 10s"{% endif %}>
  {% if fetch_now.state == "ready" %}
    <form method="post" action="/fetch-now"><button class="btn" type="submit">Fetch now</button></form>
  {% else %}
    <span class="chip">{{ fetch_now.text }}</span>
  {% endif %}
</div>
```

In `create_app`, include `fetch_now.router`. If spec 3 didn't already put `app.state.app_config` there, make sure it's set.

- [ ] **Step 4: Run the tests.** Expected: PASS, green.

- [ ] **Step 5: Commit** — `git add src/jobseeker/web/fetch_now.py src/jobseeker/web/templates/_fetch_now.html src/jobseeker/web/app.py src/jobseeker/web/templates/today.html src/jobseeker/web/templates/settings.html src/jobseeker/web/templates/onboarding/done.html src/jobseeker/web/pipeline.py src/jobseeker/web/settings.py src/jobseeker/web/onboarding.py tests/test_web_fetch_now.py && git commit -m "feat(web): Fetch now queue with per-user and daily limits and live status"`

---

### Task 15: Header notes per user, and IST times

**Files:**
- Modify:
  - `src/jobseeker/db/runs.py` (add `header_run`);
  - `src/jobseeker/web/deps.py:21-29` (`render` uses it);
  - `src/jobseeker/web/filters.py` (`explain_stats`, IST `age`);
  - `src/jobseeker/web/pipeline.py:18-19` (`_local_hour`);
  - `src/jobseeker/db/queries.py` (`today`'s "new since yesterday").
- Test: `tests/test_run_notes_users.py` (new), `tests/test_web_time.py` (new)

**Interfaces:**
- Produces:
  - `header_run(conn, user_id) -> tuple[dict | None, list[str], dict]`: the latest user run, else the latest fetch run, with errors = own + parent fetch's, and stats = `{"user": dict, "fetch": dict}`;
  - `explain_stats(stats: dict) -> list[dict]`;
  - `age(value, now=None)` counts IST days.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_run_notes_users.py
from datetime import UTC, datetime

from jobseeker.db.core import connect
from jobseeker.db.runs import finish_run, header_run, start_run
from jobseeker.web.filters import explain_stats

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=UTC)


def test_user_sees_own_and_fetch_errors_only(settings, seeded_two):
    conn = connect(settings.db_path)
    f = start_run(conn, NOW, None, kind="fetch", trigger="schedule")
    finish_run(conn, f, {"searches_trimmed": 4, "searches_planned": 60}, ["naukri: 3 of 25 searches returned no results"], NOW)
    for uid, err in ((1, "score job 7: LLMError: x"), (2, "score job 9: LLMError: y")):
        r = start_run(conn, NOW, uid, kind="user", trigger="schedule", parent_id=f)
        finish_run(conn, r, {"stopped_by": "share", "score_share_left": 0}, [err], NOW)
    run, errors, stats = header_run(conn, 2)
    assert "score job 9: LLMError: y" in errors and "score job 7: LLMError: x" not in errors
    assert "naukri: 3 of 25 searches returned no results" in errors
    assert stats["user"]["stopped_by"] == "share" and stats["fetch"]["searches_trimmed"] == 4


def test_fetch_only_before_first_user_run(settings):
    conn = connect(settings.db_path)
    f = start_run(conn, NOW, None, kind="fetch", trigger="schedule")
    finish_run(conn, f, {}, ["greenhouse:x: HTTPStatusError: 404"], NOW)
    assert header_run(conn, 1)[1] == ["greenhouse:x: HTTPStatusError: 404"]


def test_explain_stats():
    texts = [n["text"] for n in explain_stats({"user": {"stopped_by": "share", "scored": 25},
                                               "fetch": {"searches_trimmed": 6, "searches_planned": 60,
                                                         "searches_run": 54}})]
    assert "You've used today's 25 scores; more tomorrow" in texts
    assert any(t.startswith("Searched 54 of 60 role and city combinations today") for t in texts)
    for reason in ("global_cap", "quota"):
        assert explain_stats({"user": {"stopped_by": reason}, "fetch": {}})[0]["text"] == \
            "The shared AI limit ran out today; scoring resumes tomorrow"
    assert all(not n["action"] for n in explain_stats({"user": {"stopped_by": "quota"}, "fetch": {"searches_trimmed": 1}}))
```

```python
# tests/test_web_time.py
from datetime import UTC, datetime

from jobseeker.web.filters import age


def test_age_counts_ist_days():
    now = datetime(2026, 10, 11, 4, 0, tzinfo=UTC)  # 09:30 IST
    assert age("2026-10-11T00:30:00+00:00", now) == "today"  # 06:00 IST the same IST day
    assert age("2026-10-10T18:00:00+00:00", now) == "1d"     # 23:30 IST the previous day
    assert age(None, now) == "?"


def test_local_hour_is_ist(monkeypatch):
    from jobseeker.web import pipeline
    monkeypatch.setattr("jobseeker.web.pipeline.app_now", lambda: datetime(2026, 10, 11, 7, 0, tzinfo=UTC).astimezone(
        __import__("jobseeker.clock", fromlist=["APP_TZ"]).APP_TZ))
    assert pipeline._local_hour() == 12
```

- [ ] **Step 2: Run them and check they fail.** Expected: ImportError `header_run` / `explain_stats`; `age()` takes 1 argument.

- [ ] **Step 3: Implement**

`src/jobseeker/db/runs.py`:
```python
def header_run(conn: sqlite3.Connection, user_id: int) -> tuple[dict | None, list[str], dict]:
    """The header's run notes: the user's latest run plus its fetch run's errors; before any, the latest fetch."""
    row = conn.execute("SELECT * FROM runs WHERE kind = 'user' AND user_id = ? ORDER BY id DESC LIMIT 1",
                       (user_id,)).fetchone()
    parent = None
    if row and row["parent_id"]:
        parent = conn.execute("SELECT * FROM runs WHERE id = ?", (row["parent_id"],)).fetchone()
    if row is None:
        row = parent = conn.execute("SELECT * FROM runs WHERE kind = 'fetch' ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None, [], {"user": {}, "fetch": {}}
        return dict(row), json.loads(row["errors"]), {"user": {}, "fetch": json.loads(row["stats"])}
    errors = json.loads(row["errors"]) + (json.loads(parent["errors"]) if parent else [])
    return dict(row), errors, {"user": json.loads(row["stats"]), "fetch": json.loads(parent["stats"]) if parent else {}}
```

`src/jobseeker/web/filters.py`:
```python
def explain_stats(stats: dict) -> list[dict]:
    user, fetch, notes = stats.get("user") or {}, stats.get("fetch") or {}, []
    why = user.get("stopped_by")
    if why == "share":
        notes.append({"text": f"You've used today's {user.get('scored', 0)} scores; more tomorrow", "action": False})
    elif why in ("global_cap", "quota"):
        notes.append({"text": "The shared AI limit ran out today; scoring resumes tomorrow", "action": False})
    if fetch.get("searches_trimmed"):
        notes.append({"text": f"Searched {fetch.get('searches_run', 0)} of {fetch.get('searches_planned', 0)} role and city "
                              "combinations today; the rest rotate in over the next runs", "action": False})
    return notes


def age(value: str | None, now: datetime | None = None) -> str:
    from jobseeker.clock import app_today

    if not value:
        return "?"
    dt = datetime.fromisoformat(value)
    days = (app_today(now) - app_today(dt if dt.tzinfo else dt.replace(tzinfo=UTC))).days
    return "today" if days <= 0 else f"{days}d"
```
The Jinja `age` filter keeps working as `{{ x | age }}`, because `now` defaults to the current time.

`src/jobseeker/web/deps.py`, `render`:
```python
def render(request: Request, conn, name: str, **ctx):
    user = request.state.user
    run, errors, stats = header_run(conn, user.id)
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("err", request.query_params.get("err"))
    ctx["run_errors"] = errors
    ctx["run_notes"] = explain_run(errors) + explain_stats(stats)
    ctx["run_finished"] = run["finished_at"] if run else None
    ctx["nav"] = nav_counts(conn, user.id)
    ctx.setdefault("user", user)
    return request.app.state.templates.TemplateResponse(request, name, ctx)
```
Keep whatever else spec 2/3 added to `render`. Only the run lines change.

`src/jobseeker/web/pipeline.py`: `from jobseeker.clock import app_now`, and `def _local_hour() -> int: return app_now().hour`.

`src/jobseeker/db/queries.py` `today(...)`: replace `since = iso(now - timedelta(days=1))` with `since = iso(day_start_utc(app_today(now) - timedelta(days=1)))`, importing from `jobseeker.clock`.

- [ ] **Step 4: Run the tests:** `tests/test_run_notes_users.py tests/test_web_time.py tests/test_run_notes.py tests/test_web_today.py`, then the full suite **twice**: once normally, once with `TZ=America/New_York FORCE_COLOR= uv run pytest --color=no` (spec §7: times are correct whatever the server zone). Expected: PASS both times; node unchanged.

- [ ] **Step 5: Commit** — `git add src/jobseeker/db/runs.py src/jobseeker/web/deps.py src/jobseeker/web/filters.py src/jobseeker/web/pipeline.py src/jobseeker/db/queries.py tests/test_run_notes_users.py tests/test_web_time.py && git commit -m "feat(web): per-user run notes with share and rotation notes; IST greeting, ages and yesterday"`

---

### Task 16: Delete coverage and the final check

**Files:**
- Test only: spec 3's `tests/test_account.py`

- [ ] **Step 1:** `run_requests.user_id` puts the table in `user_scoped_tables`, so `delete_account` removes it with no code change. **But** `run_requests.run_id` references `runs`, and `delete_account` deletes user tables in schema order. Seed a roommate `run_requests` row with a `run_id` in `tests/test_account.py`'s delete test, and confirm that `PRAGMA foreign_key_check` stays empty. If it isn't, spec 3's caveat applies: order `run_requests` before `runs` in `delete_account`'s second loop (one `sorted(..., key=lambda x: x[0] == "runs")`).
- [ ] **Step 2:** Run `FORCE_COLOR= uv run pytest --color=no tests/test_account.py`. Expected: PASS.
- [ ] **Step 3:** Run the full verification: `FORCE_COLOR= uv run pytest --color=no`, `TZ=UTC FORCE_COLOR= uv run pytest --color=no`, and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`. Then `grep -rn "run_daily\|RunStats\|_local_hour() -> int:\n    return datetime" src` must find nothing old.
- [ ] **Step 4: Commit** — `git add -A src tests && git commit -m "test(account): delete covers run_requests; pipeline sub-project complete"`

---

## Self-review notes (done while writing)

- **Spec coverage:**
  - §4.1 config → Tasks 1 and 3;
  - §4.2 plan → Task 6;
  - §4.3 fetch → Task 7;
  - §4.4 evaluate/describe → Task 8;
  - §4.5 scoring → Tasks 9 and 10;
  - §4.6 drafting → Task 11;
  - §4.7 orchestrator and hooks → Task 12;
  - §4.8 lock/tick/CLI → Tasks 5 and 13;
  - §4.9 `profile_hash` → Tasks 2 and 4;
  - §4.10 Fetch now → Task 14;
  - §4.11 runs/notes/times → Tasks 12 and 15;
  - §5 migration v4 + delete → Tasks 4 and 16;
  - §6 errors → covered in the tests of Tasks 5, 10, 12, 13 and 14;
  - §7 testing → each task; the golden test is in Task 12;
  - §8 acceptance 1 and 6 are checked on the server in the hosting plan's Task 5.
- **Interpretation recorded (spec §4.2 rotation):** round 1 is always planned; the rest rotate as a window. This meets "every user's first pair before anyone's second" and "every trimmed pair within ⌈trimmed/fitted⌉ runs".
- **Type consistency:**
  - `UserStats` fields match spec §4.11;
  - `RunReport.aborted` is the tick's failure signal;
  - `BackupResult.ok` drives the ping;
  - `notify(conn, user_id, run_started_at, now) -> str | None` is the same as in the extras plan.
- **Names checked against plans 2 (`b78149e`) and 3 (`a16ac84`)** on 2026-10-08: `client_as(user_id)`, `anon_client()`, `seeded_two`, `OWNER_ID`, `User`, `user_by_id`, `Budget`/`Limit`, `start_run`/`last_run`, `latest()`, `MigrationContext`, `AppConfig`/`AppSearch`/`AppBudgets`/`Role`, `load_app_config`, `load_user_context(conn, uid, cfg)`, `verdict`, `user_scoped_tables`, `app_config` fixture.
