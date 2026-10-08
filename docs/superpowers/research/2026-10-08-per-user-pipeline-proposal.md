# Proposal: sub-project 4, per-user pipeline (draft, pre-spec)

**Date:** 2026-10-08 · **Branch:** `multi-user` · **Builds on:** audit §5 (the pipeline split), auth proposal (users, `runs.user_id`, migration v1), onboarding proposal (`UserPrefs`, `AppConfig`, `effective_prefs`, `reevaluate`, `prefs_hash`).
**Rulings applied:**
- Role catalog in `config/app.yaml`, plus one custom role per user.
- Each user's Groq usage is capped at an equal share of the global cap, with no pooling; users are processed round-robin.
- Matching first; drafting is gated per user.

**Out of scope:** contacts and Gmail (sub-project 5).

**Today, for scale** (live `runs` rows):
- One run fetches about 5,800-6,400 rows.
- JobSpy plans 5 queries × (4 cities + India) = 25 searches each on Naukri and Indeed, plus 5 India-wide on LinkedIn: **55 searches**, with 1-3 s pauses between them (`src/jobseeker/sources/jobspy_source.py:16, 81-86`).
- Runs take 12-78 minutes. The latest took 78 minutes, mostly waiting out Groq per-minute 429s while scoring 76 jobs.

---

## (a) Stages, signatures, and where today's code moves

```
jobseeker run (one process, holds the run lock)
  1 fetch_shared      ── no LLM, no user ────────────── jobs, discovered_companies
  2 evaluate(u)  ∀u   ── prefilter + prescore, no LLM ── user_jobs
  3 describe_shared   ── one LinkedIn cap, union of users' top picks ── jobs.jd_text
  4 evaluate(u)  ∀u   ── only jobs whose jd_hash changed ── user_jobs
  5 score round-robin ── per-user share + global cap ─── scores, applications
  6 draft round-robin ── only users with outreach_enabled ── drafts
```
- **`pipeline/plan.py`**: `build_search_plan(user_prefs: list[UserPrefs], cfg: AppConfig, run_no: int) -> list[Search]`, where `Search = (site, query, location)`. See (b).
- **`pipeline/fetch.py`**: `fetch_shared(conn, sources, client, now, generic_words) -> FetchStats`. It takes `src/jobseeker/pipeline/run.py:86-126` minus the per-user parts:
  - no `prefilter`/`_rank` (`run.py:108-114, 120`);
  - discovery gets `known` only, not `known | blocked` (`run.py:123`);
  - `bump_jobs_seen` counts **every** new job, which changes the definition of `discovered_companies.jobs_seen` (audit §5.3).

  `JobSpySource` (`jobspy_source.py:74-115`) takes a `plan: list[tuple[query, location]]` instead of computing a Cartesian product from `SearchConfig`. The ATS sources are unchanged.
- **`pipeline/evaluate.py`**: `evaluate(conn, user_id, prefs, facts, now, only_changed=False) -> int`. It walks live jobs with **no `user_jobs` row, or a row whose `jd_hash` differs from `jobs.jd_hash`**, and runs `prefilter` (`src/jobseeker/pipeline/prefilter.py:33`) and `prescore` (`src/jobseeker/pipeline/prescore.py:56`). This needs a new `user_jobs.jd_hash` column, added in v1. One function then covers:
  - new jobs (old `run.py:108-120`);
  - pre-score backfill (`run.py:132-133`);
  - re-prefilter after a description arrives (`run.py:164-171`);
  - onboarding backfill for a new user.

  `expire_unscored` (`src/jobseeker/db/jobs.py:98-105`) becomes per-user and writes `user_jobs.filter_reason`. Sub-project 3's `reevaluate` is `evaluate` over all rows, with `apply` and a preview.
- **`pipeline/describe.py`**: `describe_shared(conn, picks: list[list[int]], cap: int, describe, now) -> DescribeStats`. `picks[u]` is user u's unscored LinkedIn jobs with no description, best pre-score first. The picks are interleaved (u1#1, u2#1, u3#1, u1#2, …), de-duplicated, and stopped at `cap` (`AppConfig.search.linkedin_descriptions_per_run`, global) or at 2 failures in a row. This keeps today's loop (`run.py:142-173`), minus prefilter, which moves to stage 4.
- **`pipeline/user_run.py`**:
  - `score_batch(conn, user_id, llm, prefs, facts, rubric, n, now) -> BatchResult` (the body of `run.py:183-200`, scoped to the user);
  - `draft_batch(...)` (`run.py:204-215`, using `_apps_needing_drafts` with `user_id`).
- **`pipeline/run.py`**: `run_all(conn, *, users, sources, client, llm, cfg, now, trigger) -> RunReport`, the orchestrator. It creates **one `FallbackLLM` for the whole run** (today one per run, `run.py:225`), so a model whose quota ran out isn't retried once per user. `draft_application` (`run.py:51-62`) stays as it is; its web caller passes `current_prefs` and the user's facts.

## (b) The search union, the cap, and trimming

- **Each user's pairs:** for every role in their prefs (catalog `query`, plus their one custom role), pair it with each of their cities, plus `India` if `remote_india_ok`. A role contributes its query once even if several users share it.
- **Demand:** the number of users wanting a `(query, location)` pair.
- **Plan per site:**
  - LinkedIn: one India-wide search per *query*, exactly as today (`jobspy_source.py:82-83`). That's cheap and covers every city.
  - Naukri and Indeed: one search per *pair*.
- **Hard cap:** `AppConfig.search.max_searches_per_run` (proposed **90**, against 55 today), counted across all sites, plus `max_custom_queries` (3, one per user). Each LinkedIn query counts as 1 and each pair as 2 (Naukri + Indeed).
- **Order when over the cap:**
  1. All LinkedIn queries come first (one search each covers all of India).
  2. Then pairs, **round-robin across users**: each user's highest-demand pair, then each user's next pair, and so on. Shared pairs count as served for every user who wants them. Within a round, higher demand comes first, then catalog roles before custom roles.
  3. Pairs that don't fit are **rotated, not dropped**: `run_no` (the count of scheduled runs) offsets where the round-robin starts among trimmed pairs, so each pair is searched at least every ⌈trimmed/fit⌉ runs.

  `FetchStats` records `searches_planned`, `searches_run` and `searches_trimmed`; the admin page shows them.
- **Shared results:** every fetched job lands in the shared `jobs` table, and each user's `evaluate` decides relevance. A pair added for user A can surface jobs for B.

## (c) Fairness: shares, caps and round-robin

- **Units:** count *scores* and *drafts*, not model calls. A fallback model (`config.py:88-92`) scoring a job still spends one score from the share.
- **Config:** `AppConfig.budgets`: `global_scores_per_day`, `global_drafts_per_day` (set by the admin from the observed Groq quota), `score_per_run`, `draft_per_run`.
- **Shares:** `share = floor(global / active_users)`. Active means onboarded and not disabled. A user's room this run is `min(share − used_today(u), per_run)`. Spend is recorded in `usage` as `(user_id, day, 'score' | 'draft')`. The day is the IST date (d).
- **Round-robin in batches of 5:** u1 scores 5, u2 scores 5, u3 scores 5, and so on until every user is out of room, out of candidates, or the global cap or provider quota is hit.

  The batch size of 5 is about Groq's per-minute token limits. The 429 waits (`src/jobseeker/llm.py:92-99`) then spread across users instead of one user collecting all of them.

  A `LLMQuotaExceeded` after every fallback ends scoring for everyone. A `LLMUnavailable` ends both scoring and drafting, as today (`run.py:202-205`).
- **No pooling in v1:** room a user doesn't use (no candidates, or they ran out) is **not** given to others. They keep it for a later "Fetch now" the same day. It resets at IST midnight. The admin page shows "used / share" per user, so it's visible when pooling would help.
- **Drafting** runs only for `users.outreach_enabled` (the owner: yes), round-robin in batches of 2, from the user's share of `global_drafts_per_day`. Facts extraction (onboarding proposal §c) has its own `groq:facts` counter. It runs on the drafting model, so the spec should count it against `global_drafts_per_day` too.

## (d) Run lock, scheduling, "Fetch now", time zone

- **Lock:** `locks(name PRIMARY KEY, holder TEXT, acquired_at, heartbeat_at)`. To acquire:
  ```sql
  INSERT ... VALUES ('run', :pid_host, :now, :now)
  ON CONFLICT (name) DO UPDATE SET ... WHERE heartbeat_at < :now - 15 min
  ```
  `rowcount == 1` means we hold it. `heartbeat_at` is refreshed after every source and every scoring batch. A crashed run frees the lock after 15 minutes of silence, not after a fixed run length (runs take up to 78 minutes today). The lock is released in a `finally`.
- **One entrypoint the host just calls:** `jobseeker tick`, every 5 minutes, from a systemd timer (`OnCalendar=*:0/5`) or cron. The schedule lives in the app, not the host:
  1. If no lock can be taken, exit 0 (a run is in progress).
  2. If a **scheduled run** is due (`AppConfig.schedule.daily_at: "11:15"` in `Asia/Kolkata`, and no `kind='fetch', trigger='schedule'` run has finished today in IST), run `run_all(all users, trigger='schedule')`, then back up (`src/jobseeker/cli.py:58-61`). Missed runs catch up automatically after downtime, as launchd does today on wake.
  3. Otherwise, if a **Fetch now request** is pending, run it (below).

  `jobseeker run [--user EMAIL] [--no-fetch]` stays for manual use and takes the same lock. `jobseeker rescore --user` is `--no-fetch` with force.
- **"Fetch now"** (a button on Today and in Settings):
  - `POST /fetch-now` inserts `run_requests(user_id, requested_at, status='queued')`. The web process never runs the pipeline; a restart would kill a 78-minute task.
  - The next `tick` (within 5 minutes) runs `run_all(users=[u], trigger='fetch_now')` with a **user-only plan**: only that user's pairs, capped at `max_searches_fetch_now` (proposed 30), plus the ATS boards. Then evaluate and score only u, within u's remaining share.
  - **Limits:** one per user per 2 h (since their last `fetch_now` run *started*), and at most `max_fetch_now_per_day` (proposed 6) across everyone. It's refused or queued while any run holds the lock.
  - The button shows its state: "Queued, starts in a few minutes" / "Running" / "Next possible at 15:40". It's rendered from `run_requests` and `runs`, and polled every 10 s only while queued or running.
- **Time zone:** `AppConfig.timezone = "Asia/Kolkata"`, used through `zoneinfo.ZoneInfo`. Add **`tzdata`** as a dependency, because slim Linux images have no system time-zone database. It fixes:
  - `_local_hour` (`src/jobseeker/web/pipeline.py:18-19`, today the server's local time, UTC on a VM);
  - the "today" day boundaries for usage and the schedule;
  - `filters.age` (`src/jobseeker/web/filters.py:18-25`), which counts UTC days, so it says "1d" for an IST job posted this morning before 05:30.

  Per-user time zones aren't needed for 3 users in India; the setting keeps the door open.

## (e) The `runs` table and per-user run notes

- **Columns** (extending v1): `kind` ('fetch', 'user' or 'legacy'), `user_id` (NULL for fetch), `trigger` ('schedule', 'fetch_now' or 'cli'), `parent_id` (a user run points at the fetch run it followed), `stats`, `errors`, `started_at`, `finished_at`.
- **Stats:** `RunStats` (`run.py:36-48`) splits into:
  - `FetchStats(fetched, new, duplicates, discovered, searches_planned, searches_run, searches_trimmed, described)`;
  - `UserStats(evaluated, filtered, below_cutoff, candidates, scored, shortlisted, drafted, share_left, stopped_by)`, where `stopped_by` is one of 'share', 'global_cap', 'quota', 'unavailable', 'no_candidates' or 'run_cap'.
- **Header notes:** `render` (`src/jobseeker/web/deps.py:21-29`) shows the user's latest `kind='user'` run, plus its parent fetch run's errors. Both go through `explain_run` (`filters.py:48`).
  - Fetch errors only name sources ("naukri: 12 of 30 searches returned no results"), so they are safe to show everyone.
  - User-run errors carry job and application ids and are shown only to their owner.
  - New plain-English lines: "You've used today's 80 scores; more tomorrow" (`share`), and "The shared AI limit ran out today; scoring resumes tomorrow" (`global_cap`/`quota`).
  - The admin page lists all runs.

## (f) Scoring staleness

- `scores` gains **`profile_hash`**: the SHA-256 of the scoring-relevant `UserPrefs` fields (`experience_summary`, `target_roles`, `cities`, `remote_india_ok`, CTC, `must_haves`, `deal_breakers`) **plus the facts JSON**. The score prompt includes the facts too (`src/jobseeker/scoring/scorer.py`). This amends sub-project 3's `prefs_hash`.
- `jobs_needing_score(conn, user_id, rubric_version, profile_hash, limit)` (today `src/jobseeker/db/jobs.py:126-138`): a job needs scoring when it has no score for this user with the same `rubric_version`, `jd_hash` and `profile_hash`. Never-scored and stale jobs are ranked together by `user_jobs.prescore`, so the budget goes to the best jobs either way.
- **A stale score keeps showing** until replaced; the inbox reads the latest score. A rescore that newly says `apply` moves `new → shortlisted`, as today (`run.py:198-199`). A rescore that drops a `shortlisted`/`drafted` job to `review` doesn't change its status; the band follows the new score.
- `force_rescore` (`jobseeker rescore`) keeps meaning "ignore the hashes" for one user.

## (g) Tests

- **Plan:**
  - the union is de-duplicated and demand-ordered;
  - the cap holds (LinkedIn first);
  - round-robin gives each user their first pair before anyone gets a second;
  - trimmed pairs rotate (a pair trimmed in run n is searched by run n + ⌈trimmed/fit⌉);
  - custom roles count against `max_custom_queries`;
  - a user-only Fetch-now plan holds only that user's pairs.
- **Stages:**
  - `fetch_shared` writes no `user_jobs` and no scores, and calls no LLM (with a fake LLM that fails if called);
  - discovery ignores a user's blocked company;
  - `evaluate` covers new jobs, changed `jd_hash` and a user who joined after the jobs arrived, and leaves the other user's rows alone;
  - `describe_shared` interleaves picks, respects the global cap and stops after 2 failures in a row.
- **Fairness:** with 3 users and a fake LLM:
  - the batches interleave (u1×5, u2×5, u3×5, …);
  - a user at their share stops while others continue;
  - the global cap stops everyone;
  - unused room isn't given to others;
  - a fallback model's score counts against the share;
  - `LLMQuotaExceeded` after the chain ends scoring for all;
  - drafting runs only for `outreach_enabled`.
- **Lock and tick:**
  - a second `tick` while the lock is held exits;
  - a stale heartbeat (> 15 min) is taken over;
  - the daily run fires once per IST day, including catch-up at 23:00 after downtime;
  - 11:14 IST doesn't fire and 11:15 does (frozen clock in UTC, 05:45Z);
  - Fetch now: the 2 h per-user limit, the daily global limit, and queued while running.
- **Runs and notes:** user runs link to their fetch run; user B never sees A's run errors; the `stopped_by` messages render.
- **Staleness:** a scoring-field or facts edit changes `profile_hash`, and `jobs_needing_score` returns the job again; the old score still renders until it's replaced; a filter-only edit doesn't change `profile_hash`.
- **Time zone:** `_local_hour` and `age` use IST regardless of the server's `TZ` (run with `TZ=UTC` and `TZ=America/New_York`).
- **Golden test for the owner:** with one user, the migrated owner's run gives the same shortlists as today's `run_daily` on a fixture (same prefilter reasons, prescores and score candidates).
- **Existing suites** `tests/test_run.py`, `tests/test_run_discovery.py` and `tests/test_run_notes.py` move to the new functions. Their fixtures switch to `seeded_two` (auth proposal §f).

## Open points for the coordinator
1. Proposed numbers to confirm: `max_searches_per_run` 90; Fetch now 30 searches, 1 per user per 2 h, 6 per day globally; tick every 5 minutes; heartbeat timeout 15 minutes; batch sizes 5 (score) and 2 (draft).
2. `global_scores_per_day`: set it from the observed Groq quota for the 20b model. The latest run hit per-minute limits at 76 scores. A one-day measurement on the server, as part of the hosting spike, would set this properly.
3. Should Fetch now include the ATS boards (cheap APIs) or only JobSpy pairs? Proposed: include them.
