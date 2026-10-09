# HANDOFF: devops-lead (multi-user build), updated 2026-10-09 by manager

> **START HERE (new or /cleared session).** You are **devops-lead2** (session name), formerly devops-lead, a senior dev on job-seeker2.0's multi-user hosted app. You report to the coordinator session **`manager`** (use `SendMessage` to `manager`), not to the user. Send design questions to `manager`; it makes the calls or passes them to the user. Background on the product: `HANDOFF.md` §1–§3. Treat §8 there as history; this file supersedes it for your work.

## 1. Where you work
- **Worktree:** `/Users/user/Desktop/untitled folder/js-devops2`, branch **`build/devops2`** (from `origin/multi-user` `2f473a9`, the merge of `build/devops` into plan 2). You are the only writer on it. The old `js-build` / `build/devops` is merged and finished.
- **The Bash cwd resets to the MAIN checkout after every call.** That checkout is on `main` and runs the LIVE app. Start every command with `cd "/Users/user/Desktop/untitled folder/js-devops2" && …`. **Never touch the main checkout or `multi-user`.** backend-lead owns `multi-user`, in `../js-mu-backend`.
- **Git:** commit per task, ending messages with the attribution lines your session uses, then `git push origin build/devops2` (that branch only; never force, never `main` or `multi-user`). backend-lead2 merges it into `multi-user` when `manager` says so.
- **zsh doesn't word-split `$VAR` commands;** use a shell function. Don't chain `grep … && git commit`, because grep also matches "failed".

## 2. Status (as of 2026-10-09, build/devops2: security-review fixes A–E in progress; everything up to `74d041e` is merged into multi-user as `e32a467`)
- **Built:** extras T1–T14, pipeline T1–T16, hosting T1–T4. ALL buildable devops tasks are done.
- **Commits:**

  | Commit | What |
  |---|---|
  | `1b66009` | deps: tzdata, py-vapid==1.9.4, http-ece==1.2.1, ALL in one commit |
  | `8db827b` | pipeline T1, IST clock |
  | `186011b` | hosting T1, serve `--proxy-headers` |
  | `422dbe3` | hosting T2, templates + env.example |
  | `2ace984` | hosting T3, bootstrap/ready/js wrapper |
  | `99b7102` | hosting T4, deploy.sh |
| `962fcad` | extras T1, settings fields + gen-key/vapid-keys (Step 1 no-op) |
| `88742e9` | extras T2, backup/crypto.py AES-256-GCM |
| `bec17b5` | extras T3, backup/s3.py SigV4 PUT |
| `9312de4` | extras T4, backup/archive.py + db.backup.snapshot |
| `4f02f27` | extras T5, `jobseeker restore` |
| `d3915b6` | extras T6, push/send.py |
| `d8d5be8` | pipeline T2, profile_hash |
| `554a847` | pipeline T6, build_plan + plan-driven JobSpy sources |
| `16587fd` | docs: env.example BASE_URL origin note + hosting T5 first-POST acceptance check (backend-lead2 via manager) |
| `2f473a9` | `manager` merged `build/devops` into `multi-user` (550 pytest); `build/devops2` starts here |
| `010f6a9` | extras T9, `/healthz` (GET/HEAD, read-only) |
| `89cbaa9` | extras T13, public landing + invite-only page |
| `8fc47f6` | pipeline T7, `fetch_shared` |
| `5c67a71` | fast-forward of `build/devops2` to `multi-user` (plan 3 T1–T3: v2, AppConfig, load_user_context, effective_prefs) |
| `261892e` | extras T7, migration v3 |
| `298ceba` | pipeline T3, AppConfig schedule/fetch-now/lock/fairness settings |
| `a035569` | merge origin/multi-user `3ab1864` (plan 3 T4, require_onboarded) |
| `c8053cf` | pipeline T4, migration v4 (+ `migrated_owner_db` fixture) |
| `1ba85b9` | pipeline T5, heartbeat run lock |
| `a72db4e` | extras T8, `nightly_backup` + `jobseeker backup` (tiny cli.py edit: the `backup` command body only) |
| `e5e920f` | extras T10, `notify_new_matches` |
| `c0180a0` | pipeline T9, `profile_hash`-aware score freshness + per-run `exclude` |
| `20e7314` | pipeline T10, round-robin scoring (`pipeline/score.py`) |
| `de9d3c0` | pipeline T11, round-robin drafting (`pipeline/draft.py`; run.py's copy of `draft_application` stays until T12) |
| `1cca283` | pipeline T15, per-user header notes (`header_run`, `explain_stats`), IST `age`/greeting/yesterday. Small web/deps.py edit: `render`'s run lines + imports only |
| `bd8188c` | merge origin/multi-user `770f00f` (plan 3 T5–T8: reevaluate, onboarding, Settings, export/delete) |
| `839db77` | extras T11, `/sw.js` + `/push/*` (app.py: 1 import + 2 include_router lines; guard test exempts `/push/`) |
| `887a13d` | pipeline T8, `evaluate` + `describe_shared` (evaluate.py: 2 import lines + an appended block; jobs.py: appended `set_verdict`, `linkedin_picks`) |
| `bf1875c` | follow-up (manager): `evaluate` skips early apps of newly hidden jobs via the shared `skip_hidden_apps` (extracted from `reevaluate`) |
| `85487b6` | docs: handoff rows for T8 + follow-up |
| `198cb0e` | pipeline T12, `run_all` replaces `run_daily` (golden-checked); web/application.py: 1 import repointed to `pipeline.draft` |
| `19435a6` | pipeline T13, `jobseeker tick` (schedule, catch-up, Fetch now, backup, ping), `run`/`rescore` on `run_all` + lock; `db/run_requests.py` |
| `fceecd5` | merge origin/multi-user `558b0fd` (plan 3 complete) |
| `6006fcc` | extras T12, Settings "Daily match alerts" card + `push.js` (settings.py: `vapid_public_key` in `_page` + one route; settings.html: one include + one script tag) |
| `f79d063` | merge origin/multi-user `ee7bed9` (build/devops2 merged as 765f56c + outreach plan) |
| `705e949` | extras T14, admin Backups card; pins delete/export coverage of `push_subscriptions` (admin.py: 1 import + 1 context arg; admin.html: 1 include) |
| `513521d` | pipeline T14, Fetch now (`web/fetch_now.py`; app.py: 1 import + 1 include_router; today/settings/onboarding-done templates: 1 include line each) |
| `74d041e` | pipeline T16, delete covers `run_requests` (db/account.py: `runs` deleted last, 1 sort) + final verification; per-user pipeline sub-project complete |
| `cec5895` | docs: hosting T5 Step 3 gains the one-off `js refilter --apply` after migrating |
| `c04fb2b` | review fix A (#1): score/draft share = global // eligible users (`pipeline/eligible.py`), not the run's user count |
| (this commit) | review fix B (#2): Fetch now check+queue in one `BEGIN IMMEDIATE`; queued requests count toward the daily cap; one pending request per user (unique index, v4 amended); tick refuses a queued request past the cap |

- **Tests at `2f473a9` (multi-user, plan 2 complete):** 550 pytest per `manager`.
- **NEXT:** security-review fixes (manager ruled: fix all 10, commits A–E, test-first, push after each). A, B done; C deploy safety (#3 #4 #5 #10), D push hardening (#6 #7), E restore + sshd (#8 #9). Then send `manager` one line per commit with counts and stand by for hosting T5 (manual, with the user, once their Oracle VM is ready).
- **Ledgers (git-ignored, on disk):** `.superpowers/sdd/2026-10-08-mu-{hosting,extras,per-user-pipeline}/progress.md`. The first line is the plan path; "Task N: complete" lines mark what's done.
- **Skill scripts:** `…/plugins/cache/claude-plugins-official/superpowers/6.4.1/skills/executing-plans/scripts/{task-start,task-done}`. Run task-done with `env PYTHONWARNINGS=ignore FORCE_COLOR= uv run pytest --color=no -p no:warnings`.
- **Reporting:** after each task, send `manager` one line: task, commit, pytest/node counts. Stop and message `manager` if a task needs a spec change.

## 3. Rulings and deviations
- **Extras T1, Step 1 (`uv add`) is a NO-OP:** the deps are already in `1b66009`. Skip it.
- **Extras T4 needs `snapshot(db_path, out) -> Path` in `db/backup.py`**, which plan 2 adds on `multi-user`. Add EXACTLY that signature here. At merge, `manager` takes plan 2's version.
- Hosting T1's commit was amended before any push to hold both the test and the implementation (noted in the ledger).
- Accepted, and in the plans:
  - bootstrap writes an empty `/etc/duckdns.env` for the user to fill;
  - `notify_new_matches` returns a run note (`str|None`) and never raises;
  - `/push/*` skips `require_onboarded`;
  - the rotation window is `(run_no·slots) mod len`;
  - py-vapid + http-ece + httpx instead of pywebpush;
  - B2 is write-only;
  - `BACKUP_S3_REGION`;
  - the `gen-key`/`vapid-keys` CLIs;
  - the deploy key is generated on the server;
  - migration v2 imports from `$JOBSEEKER_HOME/profile` (no `--import` flag);
  - `nightly_backup(conn, settings, now, force=False) -> BackupResult(path, ok, uploaded, error, skipped)` is idempotent per IST day and never raises on a failed upload.
- The search cap is 60 (provisional). `global_scores_per_day` and `global_drafts_per_day` are "set from the spike".
- Migration numbers: v1 auth, v2 onboarding, **v3 extras**, v4 pipeline, v5 outreach.
- Extras T1 commit has no pyproject/uv.lock change (deps already in `1b66009`).
- Extras T4: the brief's Interfaces block says `archive.MEMBERS_ALLOWED`; the test and code use `member_allowed(name)`, which is what was built. `db.backup.snapshot(db_path, out) -> Path` added and `backup()` now calls it; take plan 2's version at merge.
- Extras T9: `test_schema_mismatch_is_503` builds the client BEFORE setting `user_version = 0`, because plan 2's `create_app` refuses an out-of-date DB at startup; the test now models the schema changing under a running app.
- Extras T13: `landing.html` extends `bare.html` (plan allows it), not `base.html`, so `base.html` is untouched for plan 3; `bare.html` gains one empty `{% block head %}`. The page wrapper is `<div class="landing">`, because `bare.html` already provides `<main>`. CSS uses ui.css's real tokens (`--line-strong`, px spacing): `--space-*`/`--border-strong` don't exist. The test_auth invite line uses the fallback ("Ask the person who shared this link"), because its fixture owner has no name. `test_web_guards` root assertion changed from 303→/login to 200 landing (plan 2's interim behaviour, replaced by this task). Google "G" path data is the standard 18px mark; verify against developers.google.com/identity/branding-guidelines before launch.
- Extras T7: the v3 function is `migrate_v3` (matching `migrate_v1`/`migrate_v2`), not the plan's `_v3_extras`. `test_endpoint_unique_and_user_required` drops its `INSERT INTO users (id=1…)`, because a fresh DB already seeds the placeholder owner as user 1.
- Pipeline T4: function is `migrate_v4` (file convention). `migrated_owner_db` (conftest) imports `live_like_v0`/`_ctx` from `tests/test_migrations.py` rather than refactoring that file (owned by backend-lead2), then migrates with the fixture profile/.
- Extras T10: `notify_new_matches`'s `keys` default is a `...` sentinel (reads VAPID from Settings), as in the plan's code; `keys=None` explicitly means "no VAPID keys", so no send. The Interfaces line's `keys=None` default is superseded by the code.
- Pipeline T10: the test's `SCORE` uses `role_family="product_analyst"`, not the plan's `"pa"`, which `LLMScore`'s Literal rejects.
- Pipeline T15 (built before T12): `header_run`'s fallback, when the user has no `kind='user'` run, also takes a `kind='legacy'` run of theirs or a shared one (not only `kind='fetch'`), so run notes don't vanish while `run_daily` still writes legacy runs or across the upgrade. `deps.py` drops its now-unused `import json`.
- Extras T11: there is no `users` fixture, so the two tests that sign in as user 2 request `seeded_two`. The test file gets the plan's autouse fixture that resets `_last_test`. `tests/test_web_guards.py` adds `"/push/"` to the require_onboarded exemption tuple (`/sw.js` is already in `PUBLIC`).
- Pipeline T8: plan 3 already owns `tests/test_evaluate.py`, so T8's tests live in `tests/test_evaluate_pipeline.py`. **Follow-up `bf1875c` (manager's ruling):** `evaluate` now applies plan 3's rule too. A job going from visible or never-judged to hidden skips its new/shortlisted/drafted app (undoable; reason "pipeline: the job description changed"), and apps at approved or later are never touched. The skip loop is extracted from `reevaluate` into `evaluate.skip_hidden_apps(conn, app_ids, reason, now)`, which both functions call.
- Pipeline T12: GOLDEN was frozen from `run_daily` on `GOLDEN_JOBS` = `([('0',1),('1',1),('2',0),('3',1),('4',0)], ['0','1','3'], ['1','0','3'])`, and `run_all` matches it. Ported tests: `test_run.py`'s budget test sets `cfg.budgets` (budgets now live in AppConfig). The finish-time test passes `clock=` returning +5 min, because `run_all` reads the clock once, at the end. `test_run_discovery.py`'s helper mirrors `prefs.budgets.score_per_run`/`prefs.search.linkedin_descriptions_per_run` into cfg. Its `stats.candidates == 2` assertion is dropped, because nothing in the plan's code fills `UserStats.candidates`. The `jobs_seen` counts needed no change. `cli.py`'s `_run` still imports `run_daily`, so `jobseeker run`/`rescore` are broken at this commit only; T13 rewrites them.
- Pipeline T13: `_pipeline` (rubric, companies, LLM) is built lazily inside the `run` closure, not up front. A busy `tick` or a lock-refused `run` therefore never builds the LLM, which needs `GROQ_API_KEY` (the plan's own fallback note). Per the plan, `rescore` now REQUIRES `--user`, and `run` no longer calls `backup`: the nightly backup belongs to `tick`. **At cutover:** the Mac's launchd job (on `main`) runs `jobseeker run`. Once this code reaches the Mac, that job stops backing up, so the server's `jobseeker-tick` timer is the replacement. cli.py drops its now-unused top-level `load_companies`/`load_rubric`/`build_llm` imports.
- Extras T12: `POST /settings/prefs/alerts` is declared BEFORE plan 3's `/settings/prefs/{section}`, which would otherwise answer "Unknown section". It saves through plan 3's `save_user_prefs` (as `/settings/profile` does) instead of raw `json_set`. The card reads `up.notify_new_matches` (the page's existing UserPrefs) instead of a new `prefs_data`. It's its own card (`id="alerts"`) placed just above Account, not nested inside it. `push.js` loads from a `<script defer>` at the end of settings.html's content block, because base.html has no head/scripts block.
- Extras T14: the Backups card uses admin.html's own conventions (`card block`, `section-title`, plain `<table>`), not the plan's `card`/`card-title`/`table`.
- Pipeline T14: no route handler passes `fetch_now=…` (pipeline.py, settings.py and onboarding.py are untouched, because backend-lead2 is editing onboarding.py). Each page instead includes `_fetch_now_slot.html`, a placeholder that `hx-get`s `/fetch-now/status` on load and swaps in `_fetch_now.html`. Test `test_pages_load_the_fetch_now_slot` pins it on /today and /settings. The `/fetch-now` router carries `require_onboarded`, as the guard test requires.
- Pipeline T16: the delete test lives in `tests/test_account_pipeline.py`, not plan 3's `tests/test_account.py`. It failed (`FOREIGN KEY constraint failed`: `run_requests.run_id` → the user's own `runs` row), so `delete_account`'s second loop now sorts `runs` last, the fix the plan anticipated.
- **Live-copy drift check (T16, read-only):** I took an SQLite backup-API copy of the live DB (opened `mode=ro`) into the scratchpad, migrated it v0→v4 (owner = the user's email), then deleted the copy. `reevaluate` dry-run: 5 hidden, 5 restored, 1 app would be skipped. `evaluate` changed **0** verdicts, and the same 5/5 remain afterwards. Why: v1 stamps `user_jobs.jd_hash` = current `jobs.jd_hash`, so `evaluate` (new or jd_hash-changed jobs only) has nothing to re-judge. The drift comes from rule changes (experience parsing, `location: KA, IN`), not changed descriptions. **Recommendation for cutover:** run `jobseeker refilter --apply` once for the owner after migrating (the user's call; it skips 1 app, undoably).
- **Review fix A (#1, manager):** the share divisor is `share_divisor(conn, stage, in_run)` = max(1, in_run, `eligible_count(conn, stage)`) in the new `pipeline/eligible.py`. "score" = `active_users` (onboarded, not disabled); "draft" = those with `drafts_enabled` (owner-only until plan 5 swaps in `outreach_enabled`). `active_users` and `drafts_enabled` moved there from tick.py/draft.py; cli.py, run.py and the draft test import them from `eligible`. Plan 5 T5/T6 (`outreach_limits`) should reuse `eligible_count`. `in_run` is in the max so a `run --email` of a not-yet-counted user, or a test DB with no user_prefs, never gets more than the run's even split.
- **Review fix B (#2, manager):** `web/fetch_now.queue_if_allowed` runs `fetch_now_state` and the insert inside one `BEGIN IMMEDIATE`; an `IntegrityError` from the new partial unique index `idx_run_requests_one_pending (user_id) WHERE status IN (queued, running)` reads as "Already queued". `fetch_now_count_today` now adds queued requests (per-user spacing already counted them through `pending`). `tick` re-checks the cap with `include_queued=False` and marks an over-cap request `failed` without running it (returns `"fetch_now_refused"`). **Migration v4 was amended in place** (manager: v4 had not shipped) and `schema.sql` gained the same index. Any scratch DB already at v4, such as the :8771 preview, lacks the index; `BEGIN IMMEDIATE` still covers it.
- **Standing rule (user, via `manager`):** every task commit also updates §2 here (commit row + NEXT) and §3 rulings, then `git push origin build/devops2` (that branch only, never force).

## 4. Gotchas
- **pytest:** `FORCE_COLOR= uv run pytest --color=no -p no:warnings`. Don't pass `-q`.
- **node:** `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`. It still emits ANSI codes, so grep with `-a`.
- The plan code is transcribed verbatim. The old throwaway extractor scripts may be gone; copy the plan's code blocks by hand.
- **SigV4 vector (extras T3):** taken from botocore, with the date pinned to `2026-10-11T05:50:00Z` and region `us-west-004`. The plan's code reproduces it.
- **Deploy tests** run `deploy.sh --dry-run` with an ssh stub on PATH and the real `git rev-parse HEAD` (`--sha` given, so no network).
- Before plan 2, extras T1's `vapid-keys` reads `Settings().model_dump().get("owner_email")` and falls back to `you@example.com`. That's fine.
- Flags already passed to backend-lead:
  - plan 3's `verdict(..., scored)` meaning;
  - a reusable v2 test-DB helper, for pipeline T4's `migrated_owner_db`;
  - a possible delete-order sort key for `run_requests.run_id → runs` (pipeline T16).

## 5. Other worktrees
- `../js-plans` (`plans/devops`) has been superseded by `build/devops`, and `manager` will remove it.
- `../js-spike` (`spike/hosting`, pushed) is throwaway. Remove it only when `manager` says the user OK'd it.

## 6. Decisions you must not re-ask (the user decided)
- Oracle Always Free (Mumbai/Hyderabad) on PAYG with a ₹100 budget alert; DuckDNS subdomain chosen at signup (`BASE_URL`); Caddy; Backblaze B2.
- Port 25 is assumed blocked, and `smtp_verify` is off on the server.
- Roommates get matching only at launch.
- Free only. Inline execution. **Never merge to `main` without the user.**
- The user does the Oracle, DuckDNS and B2 signups by hand. Never sign up, provision or spend money yourself.
