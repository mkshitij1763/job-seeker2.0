# Multi-user impact audit (pre-spec research)

**Date:** 2026-10-08 · **Branch:** `multi-user` @ `933d1f4` · **Scope:** read-only. No product code was changed.
**Target:** a hosted app with 3 users. Google sign-in; per-user preferences, resume/facts, scores, applications, contacts, Gmail tokens and budgets. Jobs are fetched once into a shared table.

All references are `path:line` from the repo root, as of `933d1f4`.

---

## 0. Headline findings

1. **`jobs` mixes shared data with per-user verdicts.** `jobs.filter_reason` and `jobs.prescore` (`src/jobseeker/db/schema.sql:17-18`) are computed from *one user's* preferences and facts, but they live on the shared table. 4,266 of the 4,497 stored jobs carry a `filter_reason` (3,488 of them for "title"). If left as-is, the roommates would never see jobs that the owner's title rules dropped. These two columns must move to a per-user table (proposed `user_jobs`, §1).
2. **Prefilter only runs on insert** (`src/jobseeker/pipeline/run.py:108-114`, `if is_new`). A user who joins later would never get existing jobs prefiltered or pre-scored for them. The per-user step has to be "evaluate every live job this user has no verdict for yet", not "evaluate new inserts".
3. **Every `/applications/{app_id}` route is an IDOR once there are two users.** All lookups are by id only (`src/jobseeker/db/applications.py:41-47`, `src/jobseeker/db/queries.py:53`), and no route checks ownership. That is about 15 routes across `src/jobseeker/web/application.py` and `src/jobseeker/web/contacts.py`. One ownership dependency should guard them all (§3).
4. **SQLite can't add these constraints in place.** `applications.job_id` is inline `UNIQUE` (`schema.sql:56`), and `usage` has `PRIMARY KEY (period, service)` (`schema.sql:166`). Changing either needs a table rebuild. SQLite also refuses `ADD COLUMN ... REFERENCES` with a non-NULL default while `foreign_keys=ON` (`src/jobseeker/db/core.py:25`). The current on-connect migrator (`core.py:9-41`, `NEW_COLUMNS`) can't express this, so it needs a versioned, explicit migration (§6).
5. **No import-time singletons.** Config is loaded in `create_app` and the CLI, not at import time. The process-wide state is `app.state.prefs` / `app.state.rubric` (`src/jobseeker/web/app.py:54-55`) and the factories on `app.state` (`app.py:57-60`). Each of those factories takes no arguments, so none can be per-user without a signature change.

---

## 1. Tables: shared or per-user

Row counts come from a copy of `data/jobseeker.db` taken 2026-10-08. No `-wal` file was present, so the copy is complete.

| Table (schema.sql) | Rows | Verdict | Changes needed |
|---|---|---|---|
| `jobs` (1-23) | 4,497 | **Shared** | Move `filter_reason` (17) and `prescore` (18) out to `user_jobs`. Keep `jd_attempts` (19) shared, since it tracks LinkedIn fetch attempts. `UNIQUE (source, source_job_id)` (21) and the fingerprint index (23) stay. |
| **new `user_jobs`** | — | Per-user | `(user_id, job_id) PRIMARY KEY, filter_reason, prescore, evaluated_at`. Backfill user 1 from the current `jobs` columns. Index `(user_id, filter_reason)`. |
| `scores` (25-39) | 168 | **Per-user** | Add `user_id`. The score prompt embeds the user's preferences (`src/jobseeker/scoring/scorer.py:33-37`) and thresholds (`scorer.py:64-66`). Replace `idx_scores_job` (39) with `(user_id, job_id, id)`. |
| `applications` (54-73) | 167 | **Per-user** | Add `user_id`. `UNIQUE(job_id)` (56) becomes `UNIQUE(user_id, job_id)`, which needs a rebuild. |
| `drafts` (75-85) | 135 | Per-user via `application_id` | No column needed if every access goes through an owned application. `UNIQUE(application_id, kind)` (84) is fine. |
| `events` (87-94) | 204 | Per-user via `application_id` | `queries.stats` reads `events` without joining `applications` (`queries.py:97-103`), so either add a join or a `user_id`. A join is enough. |
| `contacts` (41-52) | 16 | **Per-user (recommended)** | Add `user_id`. Dedup by email or LinkedIn URL is global today (`applications.py:136-138`, `contacts_repo.py:180-184`), and the edit route rewrites the row in place (`src/jobseeker/web/contacts.py:114`). With a shared table, user A's edits and "not interested" would leak into user B's view. See open question Q1. |
| `application_contacts` (123-137) | 12 | Per-user via `application_id` | Fine if routes are ownership-checked. |
| `contact_candidates` (139-150) | 19 | Per-user via `application_id` | Same. |
| `blocklist` (96-102) | 0 | **Per-user** | Add `user_id`. "Not interested" and "block company" are personal choices (`applications.py:159-175`). Empty today, so the migration is trivial. |
| `runs` (104-110) | 9 | **Split** | Add a nullable `user_id` (NULL = the shared fetch run) and a `kind` column (`fetch` or `user`). The banner (`src/jobseeker/web/deps.py:22-27`) should show the user's latest run plus the latest fetch errors. |
| `discovered_companies` (112-121) | 120 | **Shared** | No change. Its `jobs_seen` semantics change, though (§5). |
| `company_domains` (152-160) | 4 | **Shared** cache | No change. It records facts about the company (domain, MX, pattern, catch-all) and saves paid lookups. Note that any user can overwrite it through the "set domain" route (`web/contacts.py:64-74`). That's acceptable for 3 trusted users, but say so in the spec. |
| `usage` (162-167) | 4 | **Per-user plus a global cap** | Add `user_id`. The PK `(period, service)` becomes `(user_id, period, service)`, which needs a rebuild. The API keys are shared, so the provider's real limit is global (§4). |
| **new `users`** | — | — | `id, email UNIQUE, google_sub UNIQUE, name, is_admin, created_at, timezone`. Also an `invites`/allow-list table and `sessions`, or signed cookies. |
| **new `user_profile`** | — | Per-user | Preferences as JSON, validated by the existing `Preferences` model; facts JSON plus `resume_sha256`; the resume blob or path; Gmail token (encrypted). One table or several; spec decision. |

`core.py:9-17` (`REQUIRED_TABLES`, `NEW_COLUMNS`) has to learn the new tables, but the column/constraint changes above go into an explicit migration (§6).

---

## 2. Readers of profile files, secrets and per-user `.env` values

### Paths (all derive from `Settings.jobseeker_home`, `src/jobseeker/config.py:14-70`)

| File | Path property | Readers | Per-user change |
|---|---|---|---|
| `profile/preferences.yaml` | `config.py:57-58` | `web/app.py:54` (loaded **once** into `app.state.prefs`); `cli.py:14-16` (`_load`, every command) | Load from the DB per request or per run, for the current user. `app.state.prefs` must go: it is single-user, and edits made in Settings would never show until a restart. |
| `profile/facts.json` | `config.py:52-53` | `web/application.py:45` (detail page skill highlighting); `web/application.py:115` (Regenerate drafts); `cli.py:31-32` (`init`, via `load_or_build_facts`); `cli.py:46` (daily run); `db/backup.py:29-30` (copied into the backup) | Store facts JSON plus `resume_sha256` per user in the DB. `load_or_build_facts` (`src/jobseeker/profile/facts.py:50-63`) is pure apart from its two `Path`s, so split it into "build from bytes" and "save". |
| `profile/resume.pdf` | `config.py:48-49` | `cli.py:28-32` (init); `web/application.py:195` (Gmail attachment) | Per-user blob or file (`data/users/<id>/resume.pdf`). The attachment name uses `prefs.name` (`web/application.py:196`). |
| `secrets/token.json` | `config.py:68-70` | `web/app.py:59` (`gmail_factory`); `cli.py:140` (`auth-gmail`); `src/jobseeker/gmail/client.py:28-46` (`load_service` reads it and **writes the refreshed token back**, `:43`) | Per-user token storage with a write-back on refresh. `authorize` (`gmail/client.py:19-25`) uses `InstalledAppFlow.run_local_server`, a desktop loopback flow that can't run on a server. It needs a web OAuth redirect flow and a **Web**-type OAuth client. `credentials.json` today is a Desktop client. |
| `secrets/credentials.json` | `cli.py:140` | `auth-gmail` | Stays global (one Google app), but it becomes a Web client with a redirect URI. Google sign-in can use the same client. |
| `companies.yaml`, `rubric.yaml` | `config.py:60-66` | `cli.py:47`, `cli.py:16`, `web/app.py:55` | **Shared.** No change. |

### Preferences fields: per-user or operator-level

The `Preferences` model (`config.py:115-137`) mixes the two:

- **Per-user:** `name, email, linkedin, github, experience_summary, target_roles, cities, remote_india_ok, current_ctc_lpa, target_base_lpa, must_haves, deal_breakers, title_deny, title_allow, drop_if_min_years_at_least, max_age_days, thresholds, min_prescore`, and `contacts.sender_email`.
- **Operator/global:** `models` (`config.py:83-92`, the fallback chains), `search` (`config.py:95-103`; becomes the *union* of users' roles × cities, §5), and the `contacts.*` limits (`config.py:106-111`). `budgets` (`config.py:78-80`) becomes a per-user cap set by the admin, not by the user.

Readers of per-user fields outside the files above:

- `src/jobseeker/pipeline/prefilter.py:33-55`: title deny/allow, cities, remote, years, age.
- `src/jobseeker/pipeline/prescore.py:20-58`: `title_allow`, `cities`, `facts.skills`.
- `src/jobseeker/scoring/scorer.py:33-37, 64-66`: summary, roles, cities, CTC, must-haves and deal-breakers in the prompt; thresholds.
- `src/jobseeker/outreach/drafter.py:37` (signature), `:53-55` (prompt), `:87` (guard sources).
- `src/jobseeker/web/templates/today.html:6`: `request.app.state.prefs.name` for the greeting. This must come from the user.
- `src/jobseeker/web/contacts.py:33`: `Budget(conn, state.prefs.contacts, ...)` (limits).
- `src/jobseeker/web/contacts.py:50`: `run_find(..., state.prefs, ...)`.
- `src/jobseeker/contacts/finder.py:60, 90, 102, 123, 126`: budget, models, `sender_email or prefs.email` (SMTP `MAIL FROM`), pause.

### `.env`

All API keys (`config.py:15-21`) stay **global**, since the users share them. Nothing in `.env` is per-user today. `sender_email` and the budgets live in `preferences.yaml`, not in `.env`. `Settings` reads `.env` relative to the **current working directory** (`config.py:12`), and `jobseeker_home` defaults to `.` (`config.py:14`). On the server, set `JOBSEEKER_HOME` to an absolute path and set `env_file` absolutely, or run from that directory. `backup_path` (`config.py:24-30`) defaults to iCloud or `~/JobSeeker-backups`, which is meaningless on a VM.

---

## 3. Queries that must gain a user filter

Legend: **LEAK** = shows or changes another user's data if missed. **WRONG** = no leak, but wrong results for some user.

### `src/jobseeker/db/queries.py`
| Line | Function | Issue | Severity |
|---|---|---|---|
| 11 | `_LATEST_SCORE` subquery | `WHERE job_id = j.id` must also match `user_id`, or a user sees another user's score | **LEAK** |
| 17-40 | `inbox` | no `a.user_id = ?` filter | **LEAK** |
| 43-50 | `inbox_facets` | `role_family` from all users' scores; cities and sources from all jobs (fine, shared) | LEAK (minor) |
| 53-65 | `application_detail` | by `app_id` only; `latest_score(job_id)` has no user | **LEAK** |
| 68-91 | `pipeline` | no user filter | **LEAK** |
| 94-111 | `stats` | `events` counted across all users (97-103); `jobs_per_source` shared, which is fine | **LEAK** (counts) |
| 114-134 | `today` | no user filter | **LEAK** |

### `src/jobseeker/db/jobs.py`
| Line | Function | Issue |
|---|---|---|
| 70-72 | `set_filter_reason` | becomes a `user_jobs` upsert (WRONG if left on `jobs`) |
| 80-82 | `set_prescore` | same |
| 98-105 | `expire_unscored` | writes the shared `filter_reason` based on "no score exists". Must be per-user (`user_jobs`, the user's scores) |
| 108-112 | `jobs_missing_prescore` | per-user: jobs with no `user_jobs` row for this user |
| 126-138 | `jobs_needing_score` | `filter_reason IS NULL` and `NOT EXISTS scores` must both be per-user; the `prescore` ordering must come from `user_jobs` |
| 141-150 | `save_score` | needs `user_id` |
| 153-157 | `latest_score` | needs `user_id`. **LEAK** through the detail page and finder |

### `src/jobseeker/db/applications.py`
| Line | Function | Issue |
|---|---|---|
| 31-38 | `ensure_application` | `INSERT OR IGNORE ... (job_id)` and `SELECT id ... WHERE job_id = ?` would return **another user's application** for the same job. **LEAK, and it corrupts data.** |
| 41-47, 50-104 | `get_application`, `get_status`, `transition`, `snooze`, `record_followup`, `set_notes` | by `app_id`. Safe only if the route already checked ownership |
| 79-91 | `wake_snoozed` | global sweep; harmless (row-local), can stay global |
| 121-122 | `blocked_companies` | global → per-user. Today it also feeds discovery (`run.py:123`) |
| 131-156 | `save_contact` | dedup by email or URL across all contacts; blocklist check is global (141) → **LEAK** |
| 159-175 | `mark_not_interested` | inserts into `blocklist` without a user |
| 204-209 | `last_status_event` | by `app_id`; OK once ownership-checked |

### `src/jobseeker/db/contacts_repo.py`
| Line | Function | Issue |
|---|---|---|
| 124-127 | `bounced_emails` | all contacts at the company (fine if contacts become per-user, or bounces become a shared fact; see Q1) |
| 156-160, 163-175 | `blocked_profile_urls`, `blocked_names` | global blocklist → per-user. **LEAK**: B's "not interested" hides people from A |
| 178-201 | `upsert_contact` | global dedup by URL or email; adopts another user's row → **LEAK** |
| 13-121, 130-153 | the rest | by `app_id`; fine behind an ownership check |

### `src/jobseeker/db/runs.py`, `src/jobseeker/db/usage.py`, `src/jobseeker/db/companies.py`
- `runs.py:22-24` `last_run`: global. It feeds every page's banner (`web/deps.py:22`). Show per-user plus fetch runs. **LEAK** (other users' error strings carry job and application ids).
- `usage.py:23-36`: `used` and `spend` must filter by user, and `can` must also check the global total (§4).
- `companies.py`: shared; no change.

### `src/jobseeker/pipeline/`
- `run.py:65-70` `_apps_needing_drafts`: no user filter. It would **draft for another user using the wrong person's facts and preferences**.
- `run.py:87, 145`: `blocked_companies(conn)` becomes per-user.
- `src/jobseeker/pipeline/refilter.py:20-22`: `LEFT JOIN applications a ON a.job_id = j.id` returns a row per user once several users have an application for the same job, and it reads the shared `filter_reason`. Make it per-user.

### `src/jobseeker/contacts/finder.py`
- `:57-58`: app and job by id; called from a background task, so pass and check `user_id`.
- `:62-63`: `role_family` from `scores` by `job_id` only; needs `user_id` (WRONG: another user's role family).

### `src/jobseeker/web/` (raw SQL in routes)
- `web/view.py:88-90` `nav_counts`: counts all applications. **LEAK** (numbers).
- `web/contacts.py:22-23, 56, 59, 80-91, 110-118, 134, 141, 163-165, 174`: all by `app_id`; ownership must come first. `:114` updates `contacts` by `contact_id`, which crosses users if contacts stay shared.
- `web/application.py:174-175`: same.

### Ownership guard (the one thing that fixes most of the above)
Every route under `/applications/{app_id}` (`web/application.py:39, 60, 69, 78, 84, 97, 108, 128, 220, 229, 242`; `web/contacts.py:37, 54, 64, 77, 105, 122, 153`) should take one dependency, for example `owned_app(app_id, user=Depends(current_user))`. It returns 404 when `applications.user_id != user.id`. Today none of them check anything. Background `run_find` (`web/contacts.py:50`) must receive the `user_id` too.

---

## 4. Global singletons, caches and process-wide state

| What | Where | Multi-user problem | Change |
|---|---|---|---|
| `app.state.prefs` | `web/app.py:54` | one user's preferences for every request; frozen until restart | per-request `current_user` → load preferences from the DB (cheap; could cache per user with invalidation on save) |
| `app.state.rubric` | `web/app.py:55` | shared rubric | fine as-is |
| `llm_factory` | `web/app.py:57-58` | zero-arg; builds a new `RouterLLM` plus `groq.Groq` client **per call** | fine for keys (shared). Could be a process singleton for the inner `RouterLLM`, with a fresh `FallbackLLM` per user-run (its `_used_up` set, `src/jobseeker/llm.py:238`, is per-object) |
| `gmail_factory` | `web/app.py:59` | zero-arg; reads the single `token.json` | `gmail_factory(user)` → that user's token; refresh writes back per user. Call sites: `web/application.py:169, 208`; `web/contacts.py:136, 170` |
| `contacts_deps_factory` | `web/app.py:60, 70-78` | zero-arg; `find` calls it only to probe for a Tavily key (`web/contacts.py:43`), which builds a Groq client per click | keys are shared, so it can stay zero-arg; pass `user_id` into `run_find` instead |
| eager Groq client | `llm.py:73` (`groq.Groq(...)` in `GroqLLM.__init__`); `llm.py:229` (`build_llm` always builds it) | `groq.Groq` raises at construction without a key, so any path that calls `build_llm` with an empty `GROQ_API_KEY` crashes before doing any work. Tests dodge this with `groq_api_key="test"` (`tests/conftest.py:27`). Not per-user, but it matters for "Fetch now" on a server where a missing key should degrade gracefully | make the client lazy, or accept it as-is; not a multi-user blocker |
| `Budget` | `src/jobseeker/db/usage.py:11-42` | one bucket per `(period, service)`; limits from one user's preferences | two-level check: `can(user, svc)` = user's share **and** global ≤ provider limit (the free Tavily/Apify/Hunter quotas belong to one key). The `summary()` card (`web/contacts.py:33`) should show "yours / total". SMTP's daily limit is per IP, so it stays global (and port 25 is likely blocked on the VM anyway, HANDOFF §8) |
| Groq daily quota | not tracked in `usage`; only `FallbackLLM` skips used-up models per object | 3 users × `score_per_run` 80 share one free daily quota per model. User 1 can starve users 2-3 | spec decision: round-robin users within a run, or per-user caps that sum below the quota. One `FallbackLLM` across all users in one run avoids re-hitting a dead model 3 times |
| `_fingerprint` lru_cache | `web/app.py:21-23` | static-asset hashing | fine |
| `SCHEMA` read at import | `db/core.py:7` | constant | fine |
| `Settings()` | `cli.py:15, 71, 139`; `cli.py:131` (`serve`) | reads `.env` from the CWD; `JOBSEEKER_HOME` defaults to `.` (`config.py:12-14`) | set an absolute `JOBSEEKER_HOME` in the systemd unit |
| Server-local time | `web/pipeline.py:18-19` `_local_hour()` uses the **server's** timezone for the Today greeting; the launchd 11:15 schedule is local time (`scripts/com.kshitij.jobseeker.plist`) | on a UTC VM the greeting is 5.5 h off; the run lands at 16:45 IST | per-user timezone (default `Asia/Kolkata`); schedule the systemd timer in IST |
| Copy that assumes a Mac | `contacts_repo.py:37` ("the Mac may have slept"); `finder.py:143` ("try again from office Wi-Fi") | cosmetic | reword |
| `connect()` per request | `web/deps.py:13-18` calls `connect`, which may run `executescript(SCHEMA)` and `ALTER` (`core.py:29-40`) | after the migration, a request must never be the thing that migrates | gate on `PRAGMA user_version`; refuse to serve on a version mismatch |

---

## 5. Splitting `pipeline/run.py`

Current flow (`run_daily`, `run.py:218-238` → `_run`, `run.py:176-215`): `wake_snoozed` → `_fetch` (fetch + upsert + **prefilter on insert** + **prescore** + discovery) → `_select` (expire, backfill prescore, LinkedIn descriptions, pick jobs to score) → score → shortlist → draft. One `RunStats`, one `runs` row.

### Proposed split

**A. `fetch_shared(conn, sources, client, search_union, now)`**, once per schedule, no LLM:
- Build sources from `companies.yaml`, discovered boards, and a `SearchConfig` built from the **union** of all users' target roles × cities (today `cli.py:47` uses `prefs.search`).
- Fetch every source, `normalize`, `upsert_job` (`run.py:91-107`; `jobs.py:15-67` is already user-free).
- Discovery (`run.py:121-126`).
- Close a `runs` row with `user_id NULL`.

**B. `describe_shared(...)`**: LinkedIn descriptions (`run.py:142-173`). It's one shared rate budget (`search.linkedin_descriptions_per_run`, `config.py:103`) on shared rows (`jobs.jd_text`, `jobs.jd_attempts`), but *which* jobs deserve a description is decided by per-user pre-scores. Feed it the union of each user's top-N unscored candidates, interleaved, under the single global cap.

**C. `run_user(conn, user, llm, facts, prefs, rubric, now)`**, per user:
- `evaluate`: for every live job with no `user_jobs` row for this user → `prefilter` (`prefilter.py:33`) + `prescore` (`prescore.py:56`) → write `user_jobs`. This replaces the `is_new` branch (`run.py:108-114`) and `jobs_missing_prescore` (`run.py:132-133`), and it covers **onboarding backfill** for free.
- Re-prefilter jobs whose description arrived since the last evaluation (`run.py:164-171` today).
- `expire_unscored` per user (`run.py:131`).
- Score (`run.py:183-200`), shortlist, draft (`run.py:204-215`), all scoped by `user_id`.
- Close a `runs` row with that `user_id`.

### Coupling points to untangle
1. **Prefilter/prescore inside the fetch loop** (`run.py:108-120`): the biggest knot. It needs per-user `prefs`, per-user `blocked`, and per-user `facts` in the middle of a shared loop.
2. **`blocked` feeds discovery** (`run.py:87, 123`: `known | blocked`). In the shared step, pass `known` only. One user's blocked company shouldn't stop board discovery for the others.
3. **`bump_jobs_seen` counts only jobs that passed the user's prefilter** (`run.py:115-117`, after the `continue` at 114). In a shared fetch, count every new job, or every job that passed *any* user's filter. That's a definition change for `discovered_companies.jobs_seen`.
4. **Discovery's generic words come from `prefs.search.queries`** (`run.py:122`) → union of all users' queries.
5. **Description fill is chosen by prescore** (`run.py:137, 148-151`): see B above.
6. **`run_daily` signature** (`run.py:218-222`) takes one `prefs`/`facts` and creates its own `FallbackLLM` (`run.py:225`). The CLI (`cli.py:37-51`) becomes: fetch_shared → describe_shared → for each active user: `run_user`.
7. **`draft_application`** (`run.py:51-62`) is also called from the web (`web/application.py:116`). It needs the user's facts and preferences, so the signature already allows it, but the caller must pass the right ones.
8. **Concurrency**: "Fetch now" plus the timer plus 3 users means more than one writer. SQLite allows one writer at a time, and `busy_timeout` is 5 s (`core.py:27`). A long fetch holds short write transactions (each upsert commits, `jobs.py:37, 55, 66`), so readers are fine. Two fetches at once would double the network load, so add a run lock (a `runs` row with `finished_at IS NULL` and a staleness timeout, like `claim_find`, `contacts_repo.py:23-29`).
9. **Quota fairness** (§4): per-user scoring loops in sequence let user 1 drain Groq. Interleave them, or cap each user.

`rescore` (`cli.py:76-79`) and `refilter` (`cli.py:82-99`, `refilter.py:14-37`) become per-user commands (`--user`) and later Settings actions ("I changed my preferences → re-filter").

---

## 6. Migration risk note: existing data → `user_id = 1`

**Current data** (copy of `data/jobseeker.db`, 2026-10-08): jobs 4,497 (231 unfiltered), scores 168, applications 167, drafts 135, events 204, contacts 16, application_contacts 12, contact_candidates 19, blocklist 0, usage 4, runs 9, discovered_companies 120, company_domains 4. *(The brief said 3,948 jobs; the DB has grown since, so re-count right before migrating.)*

### Plan
1. **Freeze writers.** Unload both launchd agents (`com.kshitij.jobseeker`, `com.kshitij.jobseeker.web`) before taking the copy that moves to the server. Otherwise the Mac keeps running daily at 11:15 into a DB nobody reads (split brain). Run `jobseeker backup` (`cli.py:64-73`), then also keep a plain `.db` copy.
2. **Make it explicit and versioned.** Set `PRAGMA user_version` (currently 0, unused) and add `jobseeker migrate`. Don't extend `connect()`'s on-the-fly path. `connect` runs on every web request (`web/deps.py:14`), and `CREATE TABLE IF NOT EXISTS` (`core.py:31`) **silently keeps the old table shape**. Editing `schema.sql` alone would leave an old DB without `user_id` and no error.
3. **Rebuild, don't ALTER**, for `applications` (inline `UNIQUE(job_id)`) and `usage` (PK). Use SQLite's 12-step procedure: `PRAGMA foreign_keys=OFF`, `BEGIN`, create `applications_new` with `user_id NOT NULL REFERENCES users(id)` and `UNIQUE(user_id, job_id)`, `INSERT ... SELECT` **keeping the same `id`s** (drafts, events, application_contacts, contact_candidates all point at `applications.id`), drop, rename, recreate indexes, then `PRAGMA foreign_key_check` (must return nothing) and `PRAGMA integrity_check`, `COMMIT`, `foreign_keys=ON`. The same `ADD COLUMN ... REFERENCES` limit (§0.4) applies to `scores`, `contacts` and `blocklist`. Either rebuild them too, or add `user_id INTEGER` without `REFERENCES` and enforce it in code. Rebuilding everything in one transaction is the cleaner choice.
4. **Order:** create `users` and insert id 1 (email from `profile/preferences.yaml`, `is_admin=1`) → create `user_jobs` and copy `(1, id, filter_reason, prescore)` from all 4,497 jobs → rebuild `scores`, `applications`, `contacts`, `blocklist`, `usage` with `user_id=1` → `runs.user_id = 1` for the 9 historical runs (they mixed fetch and user work) → import `preferences.yaml`, `facts.json` (keep `resume_sha256` so facts aren't rebuilt), and `resume.pdf` into user 1's profile.
5. **Keep `jobs.filter_reason` and `jobs.prescore` in place** until no code reads them, then drop them in a later migration. Dropping first makes rollback harder.
6. **Gmail token: plan to re-consent; don't migrate it.** A refresh token is bound to the OAuth client that issued it. Moving from the Desktop client to a Web client invalidates the current `secrets/token.json`, so user 1 reconnects Gmail once. (Testing-mode tokens expire about weekly anyway.)
7. **Verify before switching:** row counts per table unchanged; `SELECT COUNT(*) FROM applications WHERE user_id != 1` = 0; render `queries.inbox`, `pipeline` and `today` for user 1 before and after on the copy and diff the output; `PRAGMA foreign_key_check` is empty.
8. **Rollback:** the migration is one-way. Rollback = restore the pre-migration `.db` and reload the launchd agents. Keep the Mac setup intact until the server has run cleanly for a few days.

**Risks:** dropping the inline `UNIQUE` by mistake (a duplicate application per job for one user); renumbered `applications.id` (orphaned drafts and events; the FK check catches it only if run); the Mac launchd still writing after cutover; WAL not checkpointed when copying (copy with `sqlite3 .backup` or `db/backup.py`, never a raw `cp` while the web app runs).

---

## 7. Test impact

346 tests across 45 test files. The fixtures assume one user and file-based config.

**Fixtures (`tests/conftest.py`)**
- `home` (`:16-22`) copies the **real** `profile/preferences.yaml` from the repo. Tests depend on the owner's live preferences file. Replace it with a fixture `Preferences` and a DB-backed user.
- `settings` (`:25-27`), `prefs` (`:30-32`): single-user objects; `prefs` becomes "user 1's preferences".
- `seeded` (`:59-82`): creates jobs, scores and applications with no user. It needs `user_id`, ideally with a second user's rows too, so the leak tests have something to leak.
- `tests/factories.py` `make_job`: shared jobs, fine.

**Web tests: every one builds `create_app(settings)` with no auth.** Once routes require a session, all of these need a logged-in client fixture (e.g. `client_as(user)`): `test_web_inbox.py:17,26,32`, `test_web_application.py:46,92`, `test_web_pipeline.py:24`, `test_web_today.py:47,56`, `test_web_mobile.py:14-15`, `test_web_view.py:64`, `test_web_contacts.py:19,52`, `test_web_contacts_outreach.py:56-58,195,212`, `test_web_undo.py:70`, `test_web_redesign.py`, `test_run_notes.py:36`. `gmail_factory=lambda: gmail` and `llm_factory=lambda: llm` overrides change signature if the factories take a user.

**Raw SQL against now-scoped tables:** `test_run.py`, `test_contacts_finder.py`, `test_web_contacts.py`, `test_web_redesign.py` (insert into or query `applications`, `contacts`, `usage` or `blocklist` directly); `test_db_jobs.py` (`filter_reason`/`prescore` on `jobs`); `test_db_applications.py` (`ensure_application`, blocklist); `test_refilter.py`; `test_run_discovery.py` (discovery with `blocked`, `jobs_seen` semantics).

**Config and file-path tests:** `test_config.py:31` (`test_settings_paths`), `test_profile.py`, `test_gmail.py:16` (resume path), `test_backup.py` (single `facts.json`), `test_contacts_setup.py`.

**Migration tests:** `test_db_migration.py` exercises the `NEW_COLUMNS` on-connect model. Keep it, and add a test that builds a DB with **today's** schema plus data, runs the new migration, and asserts ids are preserved, `user_id=1`, the new unique keys, and an empty `foreign_key_check`.

**New tests the spec should require:**
- Two-user isolation: B gets 404 on every `/applications/{A's id}` route.
- `inbox`, `pipeline`, `today`, `nav_counts` and `stats` show only own rows.
- Facets don't show the other user's role families.
- `ensure_application` for the same job gives two users two rows.
- B's block or "not interested" doesn't affect A.
- Budget: per-user cap and global cap.
- Per-user step backfills a user who joins after the jobs were fetched.
- Shared fetch runs once for N users.

---

## Open questions for the coordinator

- **Q1. Contacts: per-user or shared?** I recommend per-user `contacts` (privacy; no edit or blocklist bleed) with `company_domains` shared as the cache of expensive lookups. Shared contacts would save Tavily/Apify spend when two roommates target the same company, but they need a per-user overlay for edits, status and blocklist. Needs a product call.
- **Q2. Do roommates get contact finding and Gmail drafts, or only matching?** HANDOFF §8 step 3 asks the user this too. If only matching, §2's Gmail rows and most of §3's contacts rows can wait for a later phase.
- **Q3. Groq quota fairness** (§4/§5.9): round-robin or fixed per-user caps? This affects the `run_user` loop shape.
