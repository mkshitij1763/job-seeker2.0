# job-seeker2.0 multi-user: per-user pipeline (design)

**Date:** 2026-10-08
**Status:** The combined multi-user design was approved by the user on 2026-10-08. This is the written spec for sub-project 4, awaiting review.
**Depends on:**
- sub-project 2 (`…-mu-accounts-auth-design.md`): `user_jobs` (with `jd_hash`), `runs.user_id`/`kind`, `usage.user_id`, `Budget(conn, user_id, limits, now)`, migrate;
- sub-project 3 (`…-mu-onboarding-settings-design.md`): `AppConfig`, `effective_prefs`, `get_facts`, the role catalog and custom role, the per-job evaluation function inside `reevaluate`.

**Used by:**
- sub-project 5: `drafts_enabled(user)` is replaced by `users.outreach_enabled`;
- **calls into sub-project 6** (`…-extras` spec, devops-lead): `push.notify_new_matches(conn, user_id, run_started_at, now)` after each user's scoring, and `backup.nightly.nightly_backup(conn, settings, now)` plus the `HEALTHCHECK_PING_URL` ping from `tick`. If this sub-project is built first, both are stubbed with those exact signatures.

**Hosting interface (sub-project 1):** systemd `jobseeker-tick.timer` runs **`jobseeker tick`** every 5 minutes (`Type=oneshot`, `TimeoutStartSec=3h`). Research: `docs/superpowers/research/2026-10-08-per-user-pipeline-proposal.md` (audit §5).

## 1. Goal

Fetch jobs **once** for everyone, then filter, rank, score and draft **for each user**, sharing the free AI quota fairly. The run is triggered by one host-agnostic `jobseeker tick` (daily at 11:15 IST, plus per-user "Fetch now"), never overlaps itself, and shows each user their own run notes.

**Today, for scale:**
- 55 JobSpy searches per run (5 queries; LinkedIn 5; Naukri and Indeed 5 × 5 each), about 5,800-6,400 rows;
- runs take 12-78 minutes, mostly Groq per-minute waits while scoring (`runs` id 9: 78 minutes, 76 scored).

## 2. Non-goals

- Contacts and Gmail (sub-project 5). Drafting is included, but only for eligible users (§4.6).
- Push, backups beyond today's `jobseeker backup`, and `/healthz`: sub-project 6. This spec only calls their entry points (§4.7, §4.8).
- Pooling unused per-user budget (ruled out for v1).
- Per-user time zones: a single `Asia/Kolkata` app time zone.
- Changing the ATS sources, discovery heuristics or the rubric.

## 3. Decisions (brainstorming and coordinator rulings)

| Topic | Decision |
|---|---|
| Stages | `fetch_shared` → `evaluate` (each user) → `describe_shared` → `evaluate` (changed descriptions) → score round-robin → draft round-robin, all under one run lock |
| Search cap | `max_searches_per_run: 60`, **provisional**, to be set from the hosting spike's first week. LinkedIn queries come first; pairs are round-robin across users; trimmed pairs rotate across runs |
| Custom roles | One per user; the union is capped by `max_custom_queries: 3` |
| Fairness | Per-user daily share = `floor(global / eligible users)`, plus the global cap. **No pooling.** Round-robin batches of **5** scores and **2** drafts |
| Units | A score or a draft counts as 1, whichever model in the fallback chain served it |
| Global daily caps | `global_scores_per_day` and `global_drafts_per_day` are config values, **set from the spike's quota measurement** (defaults below are provisional) |
| Facts extraction | Keeps its own `groq:facts` counter (sub-project 3); it isn't counted in the drafting cap |
| Lock | A `locks` row with a heartbeat; taken over after **15 minutes** of silence |
| Scheduling | `jobseeker tick` every 5 minutes; the 11:15 `Asia/Kolkata` schedule lives in `config/app.yaml`, with automatic catch-up |
| Fetch now | Queued by the web, run by the next tick. User-only plan of ≤ **30** searches **plus ATS boards**. **1 per user per 2 h**, **6 per day** globally |
| Staleness | `scores.profile_hash` = SHA-256 of the scoring preference fields **plus the facts JSON**. This replaces the `prefs_hash` named in the sub-project 3 proposal |
| Time zone | `zoneinfo.ZoneInfo("Asia/Kolkata")`; add **`tzdata`** as a direct dependency |

## 4. Design

### 4.1 Configuration (additions to `AppConfig`, sub-project 3)

```yaml
timezone: Asia/Kolkata
schedule: {daily_at: "11:15", max_attempts_per_day: 2}
search:
  max_searches_per_run: 60        # provisional: set from the hosting spike's first week
  max_searches_fetch_now: 30
  max_custom_queries: 3
budgets:
  global_scores_per_day: 150      # provisional: set from the spike's Groq quota measurement
  global_drafts_per_day: 20       # provisional: as above
  score_per_run: 80               # per user, per run (today's value)
  draft_per_run: 10
  score_batch: 5
  draft_batch: 2
fetch_now: {min_hours_between_per_user: 2, max_per_day: 6}
lock: {takeover_after_minutes: 15}
```

**Time** (`src/jobseeker/clock.py`, new): `APP_TZ`, `app_now() -> datetime` (aware, in IST), `app_today() -> date`, and `app_day(dt) -> str` (YYYY-MM-DD in IST). Everything stays stored in UTC as today (`src/jobseeker/db/core.py:44-51`); only "what day / what hour is it" uses IST.

### 4.2 Stage 1: building the search plan (`src/jobseeker/pipeline/plan.py`)

```python
@dataclass(frozen=True)
class Search: site: str; query: str; location: str
def build_plan(users: list[tuple[int, Preferences]], cfg: AppConfig, run_no: int, cap: int) -> Plan
```

- **Each user's pairs:** for each query in `prefs.search.queries` (the catalog roles plus the custom role, from `effective_prefs`), pair it with each of `prefs.cities`, plus `India` if `remote_india_ok`. Custom queries from all users are capped at `max_custom_queries`, oldest `user_prefs.updated_at` first.
- **LinkedIn:** one `(query, "India")` search per distinct query (as `src/jobseeker/sources/jobspy_source.py:82-83`), cost 1 each. They're always planned first. If they alone exceed the cap, catalog queries go first in demand order, then custom ones.
- **Pairs:** a pair costs one search per enabled non-LinkedIn site (today 2: Naukri, Indeed). *Demand* is the number of users wanting the pair.
- **Filling the remaining budget, round by round:** in each round, every user (ordered by `user_id`, rotated by `run_no`) contributes their next not-yet-planned pair, highest demand first, then catalog before custom, then alphabetical. A pair already planned counts as served for every user who wants it. Rounds continue until the next pair doesn't fit.
- **Rotation:** pairs that didn't fit are ordered by `(run_no + index) % len(trimmed)`, so the starting point moves every run and every pair is searched at least once every ⌈trimmed / fitted⌉ runs. `run_no` = the count of `runs` with `kind='fetch'`.
- **`Plan`** = `{linkedin: [queries], pairs: [(query, location)], planned, trimmed}`. `JobSpySource` (`jobspy_source.py:74-115`) takes `plan: list[tuple[str, str]]` instead of computing `searches()` from `SearchConfig`. Its pauses, warnings and stop-on-error behaviour are unchanged.
- **Fetch now:** `build_plan([(u, prefs)], cfg, run_no, cap=max_searches_fetch_now)`.

### 4.3 Stage 2: fetching for everyone (`src/jobseeker/pipeline/fetch.py`)

`fetch_shared(conn, sources, client, now, generic_words) -> FetchStats` is `src/jobseeker/pipeline/run.py:86-126` with the per-user parts removed:
- normalise and upsert every raw job (`src/jobseeker/db/jobs.py:15-67`, unchanged);
- **no** `prefilter` or `_rank` calls;
- `bump_jobs_seen` counts **every new job** at the company (a definition change: before, only jobs that passed the owner's prefilter were counted);
- discovery gets `known` only, not `known | blocked` (`run.py:123`): one user's blocked company must not stop board discovery for the others;
- `generic_words` = `GENERIC_WORDS` ∪ the words of every planned query.

Sources: `companies.yaml` boards + active discovered boards + `JobSpySource`s built from the plan (`src/jobseeker/sources/registry.py:16-31` gains a `plan` argument). `heartbeat()` is called after each source.

### 4.4 Stages 3-5: evaluate and describe

- **`evaluate(conn, user_id, prefs, facts, now) -> int`** (`src/jobseeker/pipeline/evaluate.py`, alongside sub-project 3's `reevaluate`):
  - selects live jobs (`COALESCE(posted_at, first_seen_at) ≥ now − max_age_days`) where the user has **no `user_jobs` row**, or `user_jobs.jd_hash != jobs.jd_hash`;
  - for each, runs the shared per-job function (`prefilter` with `blocked_companies(conn, user_id)`, then `prescore`) and upserts `user_jobs(filter_reason, prescore, jd_hash, evaluated_at)`;
  - a new job below `cfg.min_prescore` gets `filter_reason = "low pre-score: N"`, as `run.py:81-83` does today. A changed description re-runs `prefilter` but doesn't apply the pre-score cutoff, matching `run.py:171`.
  - It also runs the per-user `expire_unscored` (sub-project 2 §4.8). It never touches applications. It's called for every active user (`onboarded_at` set, `disabled_at` null), in `user_id` order. It's the only path by which new jobs reach a user, and it covers late joiners automatically.
- **`describe_shared(conn, picks: list[list[int]], cap: int, describe, now) -> DescribeStats`** (`src/jobseeker/pipeline/describe.py`):
  - `picks[u]` = the user's unfiltered, unscored **LinkedIn** jobs with an empty `jd_text` and `jd_attempts < 2`, ordered by `user_jobs.prescore DESC`, at most `cap` each;
  - the lists are interleaved (u1#1, u2#1, …, u1#2, …), de-duplicated, and stopped at `cap = cfg.search.linkedin_descriptions_per_run` (global) or after 2 consecutive failures;
  - this is today's loop (`run.py:142-173`) minus `prefilter`/`_rank`. Successes update `jobs.jd_text`/`jd_hash`, so the next `evaluate` pass picks them up through the `jd_hash` change.

### 4.5 Stage 6: scoring, round-robin

```python
def score_batch(conn, user_id, llm, prefs, facts, rubric, profile_hash, n, now) -> BatchResult
```

- **Candidates:** `jobs_needing_score(conn, user_id, rubric.version, profile_hash, limit=n, with_jd=True)` = live jobs that are unfiltered for the user, have a description, and have **no score** for the user with the same `rubric_version`, `jd_hash` and `profile_hash`. Ordered by `user_jobs.prescore DESC, first_seen_at DESC`. Never-scored and stale jobs are ranked together.
- **Per job:**
  - `score_job` (`src/jobseeker/scoring/scorer.py`, unchanged signature);
  - `save_score(conn, user_id, job_id, result, model, rubric.version, jd_hash, profile_hash)`;
  - `ensure_application(conn, user_id, job_id)`;
  - `new → shortlisted` when the recommendation is `apply` (`run.py:198-200`);
  - `Budget.spend("score")`.
- **A stale rescore never changes an existing status.** The inbox band follows the latest score.
- **Room per user, per run:** `min(score_per_run, share − used_today)`, where `share = floor(global_scores_per_day / active_users)`. `Budget` limits: `{"score": Limit("day", global_scores_per_day, share)}`, with the day in IST.
- **Loop:** each active user scores up to `score_batch` (5), then the next user, and so on. A user drops out when their room is 0, or they have no candidates. The loop ends when every user has dropped out, or:
  - **the global cap is reached:** `stopped_by = "global_cap"` for everyone still in;
  - **`LLMQuotaExceeded` after the full fallback chain:** `quota`, for everyone;
  - **`LLMUnavailable`:** `unavailable`, for everyone; drafting is skipped too.

  A plain `LLMError` skips that job, records `score job <id>: …` in the user's errors, and moves on, as `run.py:191-193` does today.
- **One `FallbackLLM` for the whole run** (today one per call to `run_daily`, `run.py:225`), so a used-up model isn't retried for each user.
- `profile_hash` is computed once per user per run (§4.9).

### 4.6 Stage 7: drafting, round-robin

- **Eligibility:** `drafts_enabled(user)`. Until sub-project 5 lands, that's `user.is_admin` (the owner). Sub-project 5 replaces it with `users.outreach_enabled`.
- **Share:** `floor(global_drafts_per_day / eligible_users)`. Room per run: `min(draft_per_run, share − used_today)`. Limits: `{"draft": Limit("day", global_drafts_per_day, share)}`.
- **Batches:** `draft_batch` (2) per eligible user, round-robin. Candidates come from `_apps_needing_drafts(conn, user_id, n)` (`run.py:65-70` plus `user_id`), with the best score first. `draft_application` (`run.py:51-62`) is unchanged, apart from receiving the user's prefs and facts.
- **Skipped** when `unavailable`, or when the score quota was hit and the models are equal (today's rule, `run.py:202-205`).

### 4.7 The orchestrator and the calls into sub-project 6 (`src/jobseeker/pipeline/run.py`)

```python
def run_all(conn, *, users: list[User], trigger: str, fetch: bool, plan_cap: int, client, llm, cfg, rubric,
            now, describe=fetch_description, sources_factory=build_sources) -> RunReport
```

1. If `fetch`: `start_run(kind='fetch', user_id=None, trigger)`, then `build_plan`, `fetch_shared`, `finish_run` (`FetchStats`).
2. For each user: `start_run(kind='user', user_id=u, trigger, parent_id=fetch_run_id)`.
3. `evaluate` for each user, then (if `fetch`) `describe_shared`, then `evaluate` again (only `jd_hash` changes match).
4. Score round-robin (§4.5).
5. After the scoring loop, for each user, when `trigger` is `schedule` or `fetch_now` (never `cli`): call **`push.notify_new_matches(conn, user_id, run_started_at, now)`**, where `run_started_at` is that user run's `started_at`. It's called **outside any write transaction** (every pipeline write has already committed), and wrapped in try/except: an exception becomes the line "Couldn't send the match alert" in that user's errors and never fails the run. Sub-project 6 decides what counts as a new match from `run_started_at`.
6. Drafting (§4.6), then `finish_run` for each user run with `UserStats`.

Note the order: alerts go out right after scoring, so a slow drafting stage doesn't delay them.

`run_daily` and its old callers are removed; `rescore` and `run` use `run_all` (§4.8). `wake_snoozed` runs once per tick for everyone, as before.

### 4.8 The lock, `jobseeker tick` and the CLI

**Lock** (`src/jobseeker/db/locks.py`):
```sql
INSERT INTO locks (name, holder, acquired_at, heartbeat_at) VALUES ('run', :holder, :now, :now)
ON CONFLICT (name) DO UPDATE SET holder = excluded.holder, acquired_at = excluded.acquired_at,
  heartbeat_at = excluded.heartbeat_at
WHERE locks.heartbeat_at < :now_minus_takeover
```
- `rowcount == 1` means acquired. `holder = "<hostname>:<pid>"`.
- `heartbeat()` updates `heartbeat_at` if `holder` still matches. If it doesn't match (taken over), it raises `LockLost`, and the run stops at the next checkpoint.
- Heartbeats happen after each source, each scoring and drafting batch, and each `describe` item. Release is `DELETE … WHERE holder = :holder`, in a `finally`.

**`jobseeker tick`** (the only host hook; exit code 0 unless it crashes):
1. `wake_snoozed(conn, now)`.
2. Try the lock. If it isn't free, exit 0 ("run in progress").
3. **Is the scheduled run due?** `app_now() ≥ today at daily_at`, **and** no `runs` row with `kind='fetch' AND trigger='schedule'` and a non-null `finished_at` started on today's IST date, **and** fewer than `max_attempts_per_day` such rows started today. If due:
   - `run_all(all active users, trigger='schedule', fetch=True, plan_cap=max_searches_per_run)`;
   - then, **even if the run failed**, `backup.nightly.nightly_backup(conn, settings, now)` (sub-project 6). It's idempotent per IST day, keyed on its `backups` row, so a retried scheduled run doesn't back up twice;
   - then ping `HEALTHCHECK_PING_URL` (if set) on success, or `<url>/fail` if the run aborted or the backup failed (5 s timeout; a ping failure is only logged);
   - release and exit.

   A crashed attempt (no `finished_at`, lock later taken over) is retried on a later tick, up to `max_attempts_per_day`.
4. **Otherwise, a Fetch-now request?** The oldest `run_requests` row with `status='queued'`: mark it `running`, run `run_all(users=[u], trigger='fetch_now', fetch=True, plan_cap=max_searches_fetch_now)` (ATS boards included), then mark it `done` or `failed` with the `run_id`. Release and exit.
5. Otherwise release and exit.

**CLI:**
- `jobseeker run [--user EMAIL] [--no-fetch]` takes the same lock (exit 1 with "A run is in progress since 10:02" if it's held) and calls `run_all` with `trigger='cli'`. It runs every active user unless `--user` is given.
- `jobseeker rescore --user EMAIL` = `--no-fetch` plus `force=True`: `jobs_needing_score` ignores the hashes for that user.
- `jobseeker serve` is unchanged. launchd is replaced by the systemd units in the hosting spec. On the Mac, `com.kshitij.jobseeker` can run `jobseeker tick` every 5 minutes for local use.

### 4.9 `profile_hash`

`profile_hash(prefs, facts) = sha256(json.dumps({...}, sort_keys=True, separators=(",", ":")))` over:
- `experience_summary`, `target_roles` (sorted), `cities` (sorted), `remote_india_ok`, `current_ctc_lpa`, `target_base_lpa`, `must_haves` (sorted), `deal_breakers` (sorted);
- `facts.model_dump()`.

Those are exactly the inputs of the score prompt (`src/jobseeker/scoring/scorer.py:33-37`) apart from the job itself. Filter-only fields (title allow/deny, the years threshold, max age) are handled by `evaluate`/`reevaluate` and aren't included.

- **Facts or scoring-field edits** (sub-project 3 Settings) change the hash, so the jobs come back in `jobs_needing_score` and refresh best-first within each run's room. The old score keeps showing until it's replaced.
- **Thresholds and the rubric version are global** (a rubric change already invalidates through `rubric_version`).

### 4.10 Fetch now (web)

- **`POST /fetch-now`** (`current_user`, `require_onboarded`, Origin check). Refused with a message, and no row, when:
  - the user has a `queued` or `running` request: "Already queued";
  - their last `fetch_now` run started < 2 h ago: "Next possible at 15:40";
  - ≥ 6 `fetch_now` runs started today (IST): "Fetch now is used up for today".

  Otherwise it inserts `run_requests(user_id, requested_at, status='queued')`. A request made while the lock is held stays queued, and the message says "Starts after the current run".
- **`GET /fetch-now/status`:** a small fragment showing "Queued, starts in a few minutes" / "Running since 14:05" / "Done: 12 new matches" / "Next possible at 15:40". It's polled every 10 s **only while** queued or running.
- The button appears on Today (header area) and on Settings (Account section). The Onboarding Done card (sub-project 3) shows it too, so a new user's first scores don't wait for 11:15.

### 4.11 Runs and the header notes

- **`RunStats`** (`run.py:36-48`) splits into:
  - `FetchStats(fetched, new, duplicates, discovered, searches_planned, searches_run, searches_trimmed, described, errors)`;
  - `UserStats(evaluated, filtered, below_cutoff, candidates, scored, shortlisted, drafted, score_share_left, stopped_by, errors)`.

  `stopped_by` is one of `share`, `global_cap`, `quota`, `unavailable`, `no_candidates` or `run_cap`.
- **`render`** (`src/jobseeker/web/deps.py:21-29`) shows the user's latest `kind='user'` run, plus the errors of its `parent_id` fetch run. With no user runs yet, it shows the latest fetch run only.
  - Fetch errors name sources only, so every user can see them.
  - User-run errors carry job and application ids and are shown only to their owner.
- **`explain_run`** (`src/jobseeker/web/filters.py:48-83`) gains:
  - `share` → "You've used today's {n} scores; more tomorrow";
  - `global_cap` / `quota` → "The shared AI limit ran out today; scoring resumes tomorrow";
  - `searches_trimmed > 0` → "Searched {run} of {planned} role and city combinations today; the rest rotate in over the next runs" (not an action item);
  - a failed `notify_new_matches` → "Couldn't send the match alert".
- **Times:**
  - `_local_hour` (`src/jobseeker/web/pipeline.py:18-19`) becomes `app_now().hour`;
  - `filters.age` (`filters.py:18-25`) counts days between IST dates;
  - `queries.today`'s "new since yesterday" (`src/jobseeker/db/queries.py:126`) uses the IST start of yesterday.

## 5. Data model (migration v4)

```sql
ALTER TABLE runs ADD COLUMN trigger TEXT NOT NULL DEFAULT 'cli';          -- schedule | fetch_now | cli
ALTER TABLE runs ADD COLUMN parent_id INTEGER REFERENCES runs(id);
-- runs.kind (v1) now takes: fetch | user | legacy
ALTER TABLE scores ADD COLUMN profile_hash TEXT;
CREATE TABLE locks (name TEXT PRIMARY KEY, holder TEXT NOT NULL, acquired_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL);
CREATE TABLE run_requests (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  requested_at TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
  run_id INTEGER REFERENCES runs(id), finished_at TEXT);
CREATE INDEX idx_run_requests_status ON run_requests (status, requested_at);
CREATE INDEX idx_runs_kind ON runs (kind, trigger, started_at);
```

**Back-fill:** `UPDATE scores SET profile_hash = :h WHERE user_id = 1`, where `h = profile_hash(effective_prefs(1), get_facts(1))` is computed by the migration (v2 has already run). This stops the owner's 168 existing scores from all becoming stale at once. Legacy runs keep `kind='legacy'`, so the first `tick` after cutover may run that day's schedule even if the Mac already did, which is harmless.

**Delete and export coverage** (sub-project 3 §4.7): `run_requests` is added to the per-user delete. Runs are already covered.

## 6. Errors

| Situation | Behaviour |
|---|---|
| Lock held | `tick` exits 0; `jobseeker run` exits 1 with the holder's start time; Fetch now queues |
| A run dies (OOM, reboot) | Its heartbeat stops; the next tick after 15 minutes takes over; the scheduled run retries up to 2 attempts per IST day; a stuck `run_requests` row in `running` older than the takeover window is marked `failed` |
| `LockLost` mid-run | The run stops at the next checkpoint, records "run superseded", and closes its runs rows |
| One source fails | Recorded in the fetch errors; others continue (today's behaviour, `run.py:94-99`) |
| A user's share is used | That user stops (`stopped_by=share`); others continue |
| Global cap or provider quota | All users stop scoring; drafting follows the `run.py:202-205` rule |
| `notify_new_matches` raises | Caught; "Couldn't send the match alert" in that user's errors; the run continues |
| Backup or ping fails | Recorded by sub-project 6's `backups` row; the ping goes to `<url>/fail`; tick still exits 0 |
| Fetch-now limits | Refused with a reason and the next possible time |
| `tzdata` missing | Impossible once it's a dependency; `clock.py` imports `ZoneInfo("Asia/Kolkata")` at import time, so a broken install fails loudly at startup |

## 7. Testing

No network. JobSpy (`scrape`), `describe`, the ATS clients and the LLM are faked. The clock is injected (`now` and `app_now` take a frozen UTC instant).

- **Plan:**
  - de-duplicated union; LinkedIn queries first at cost 1, pairs at cost = the number of non-LinkedIn sites;
  - cap 60 holds; round-robin gives every user their first pair before anyone's second; shared pairs serve several users;
  - custom queries capped at 3, oldest first;
  - rotation: a pair trimmed in run n is searched by run n + ⌈trimmed/fitted⌉;
  - a Fetch-now plan has only that user's pairs, capped at 30;
  - today's owner preferences give exactly today's 55 searches when alone.
- **Stage isolation:**
  - `fetch_shared` writes no `user_jobs`, scores or applications, and calls no LLM (a fake that fails if called);
  - discovery isn't suppressed by a user's blocked company;
  - `bump_jobs_seen` counts every new job;
  - `evaluate` covers new jobs, a changed `jd_hash`, a late joiner (a user added after the jobs exist gets verdicts on the next run), and leaves other users' rows alone;
  - `describe_shared` interleaves, respects the global cap, and stops after 2 consecutive failures.
- **Fairness** (3 users, a fake LLM that counts calls):
  - batches interleave u1×5, u2×5, u3×5, …;
  - a user at their share stops while the others continue; the global cap stops everyone;
  - unused room isn't given to others;
  - a fallback model's score counts as 1;
  - `LLMQuotaExceeded` after the chain stops everyone; `LLMUnavailable` also skips drafting;
  - drafting runs only for `drafts_enabled` users (the owner here).
- **Staleness:**
  - editing `experience_summary` or the facts changes `profile_hash`, and the job is returned again; editing `title_deny` doesn't change it;
  - the old score renders until replaced; a stale rescore never changes status;
  - the v4 back-fill leaves the owner's existing scores un-stale.
- **Lock and tick:**
  - a second acquire fails while the heartbeat is fresh and succeeds after 15 minutes of silence;
  - `LockLost` stops the run;
  - the scheduled run fires once per IST day: not at 05:44Z (11:14 IST), yes at 05:45Z; catch-up at 17:30Z after downtime; at most 2 attempts;
  - Fetch now: the 2 h per-user limit, the 6-per-day global limit, one queued per user, queued while the lock is held, a stuck `running` request is failed after takeover;
  - `tick` never raises on a held lock.
- **Calls into sub-project 6** (both stubbed and recorded in tests):
  - `notify_new_matches` is called once per user per scheduled or Fetch-now run (never for `cli`), with that user run's `started_at`, after scoring and before drafting, with no open transaction (`conn.in_transaction` is False);
  - a raising stub adds the error line and doesn't fail the run;
  - `nightly_backup` is called after every scheduled-run attempt, including a failed one, and never after Fetch-now or CLI runs;
  - the ping goes to `<url>` on success and to `<url>/fail` when the run aborted or the backup raised.
- **Runs and notes:**
  - user runs link to their fetch run; the roommate never sees the owner's run errors;
  - each `stopped_by` and the trimmed-search note render;
  - `_local_hour`, `age` and "new since yesterday" are correct in IST under `TZ=UTC` and `TZ=America/New_York`.
- **Golden test for the owner:** with only the owner active, `run_all` on a fixed fixture gives the same `user_jobs` verdicts, score candidates (order) and shortlists as today's `run_daily` on the same data.
- **Migration v4:** columns and tables exist; the back-fill hash equals `profile_hash(effective_prefs(1), facts)`; a re-run is a no-op; `run_requests` is in the delete test from sub-project 3.
- **Existing suites** (`tests/test_run.py`, `tests/test_run_discovery.py`, `tests/test_run_notes.py`) move to the new functions with `seeded_two`.

## 8. Acceptance criteria

1. On the server, the 11:15 IST run happens once per day with no host-side schedule except the 5-minute tick, and catches up after a reboot.
2. With 3 users, one run searches at most 60 times. Each user's run notes show their own counts. Scoring interleaves in batches of 5, and nobody exceeds their share.
3. The owner alone gets the same results as today's pipeline (golden test).
4. Fetch now: starts within 5 minutes when idle, refuses within 2 h of the last one with the next possible time, and never runs alongside another run.
5. Changing the summary or the resume makes those jobs re-score over the next runs, best first; changing title exclusions doesn't.
6. A killed run frees the lock within 15 minutes, and the day's scheduled run retries.
7. Greeting and ages use IST on a UTC server.
8. `tzdata` is a direct dependency, `uv.lock` is updated, and all tests pass with no network.
