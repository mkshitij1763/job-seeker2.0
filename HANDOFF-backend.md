# HANDOFF: backend-lead (multi-user build), 2026-10-08

> **START HERE (new session).** You are **backend-lead**, a senior dev on job-seeker2.0's multi-user hosted app. You report to the coordinator session **`manager`** (use `SendMessage` to `manager`), not to the user. Send design questions to `manager`; it makes the calls or passes them to the user. Background on the product: `HANDOFF.md` §1–§3 (in the same repo). Treat §8 there as history; this file supersedes it for your work.

## 1. Where you work
- **Worktree:** `/Users/user/Desktop/untitled folder/js-mu-backend`, branch **`multi-user`**. You are the only writer on `multi-user`.
- **The Bash cwd resets to the MAIN checkout after every call.** That checkout is on `main` and runs the LIVE app (launchd `com.kshitij.jobseeker` + `.web`). Start every command with `cd "/Users/user/Desktop/untitled folder/js-mu-backend" && …`. **Never edit, switch or build in the main checkout, and never touch its `data/`.**
- **Git:** commit per task, ending messages with the attribution lines your session uses. Don't push (`manager` pushes). Never merge to `main`.
- **devops-lead** builds independent tasks on `build/devops` (worktree `../js-build`). `manager` merges that branch into `multi-user` after plan 2 lands, and resolves the expected `uv.lock`/`pyproject` conflict and the duplicate `db/backup.snapshot()` (take yours).

## 2. Status (at pause)
- **Plan 2** `docs/superpowers/plans/2026-10-08-mu-accounts-auth.md` (spec `docs/superpowers/specs/2026-10-08-mu-accounts-auth-design.md`):

  | Task | Commit |
  |---|---|
  | T1 migrate framework | `af3b814` |
  | T2 migrate_v1 fn | `a66f735` |
  | T3 schema switch | `222d7d5` |
  | T4 user_jobs | `91000b2` |
  | T5 read scoping | `15f6635` |
  | T6 OAuth primitives/users/invites | `806f273` |

- **Tests at `806f273`:** 442 pytest, 19 node, verified by `manager`. `git status` is clean.
- **`manager` independently verified T3:** a real migrate on a `.backup` copy of the live DB gives user_version 1, an empty foreign_key_check, integrity ok, apps 167 / scores 168 / jobs 4497 / user_jobs 4497, all on user 1.
- **NEXT:** plan 2 **Task 7** (sessions, `/login`, `/auth/callback`, `/logout`, startup env check), then T8–T11. Then **plan 3** `docs/superpowers/plans/2026-10-08-mu-onboarding-settings.md` (accepted at `a16ac84`), T1–T9.
- **Ledger:** `.superpowers/sdd/2026-10-08-mu-accounts-auth/progress.md` (git-ignored, on disk). Resume from the first task without a "complete" line. Skill scripts: `…/plugins/cache/claude-plugins-official/superpowers/6.4.1/skills/executing-plans/scripts/{task-start,task-done} <plan> <N> [BASE] -- <test cmd>`. The BASE for T7 is `806f273`.
- **Execution:** inline (superpowers:executing-plans), with TDD per task. After each task, send `manager` one line: task, commit, pytest/node counts. Stop and message `manager` if a task needs a design change beyond the spec, or if tests can't be made green.

## 3. Rulings and deviations already made (not in the plan file)
- T3: two raw `INSERT INTO blocklist` statements in `tests/test_contacts_finder.py` (about lines 126 and 140) pass `user_id=1`.
- T3: four legacy v0 catch-up tests (`test_db_migration.py` x3, `test_contacts_setup.py::test_migrates_older_db`) build their DB from `SCHEMA_V0` and reopen it with `connect(path, check_version=False)`.
- **T4 (code):** `expire_unscored` also INSERTs `'stale: never scored'` user_jobs rows for old, unscored jobs that have no verdict row. The plan only UPDATEd existing rows, which left them unexpired.
- T4: test verdict reads use `(get_user_job(conn, 1, id) or {}).get("filter_reason")`.
- T6: `Settings.owner_email` is defined once (T1); T6 adds `google_client_id/secret`, `base_url`, `secret_key`, `cookie_secure`. Extra test: `test_another_account_cannot_claim_owner_by_email_after_sub_is_set`. `set_disabled` tolerates a missing row.
- Earlier, accepted by `manager`:
  - a fresh DB seeds `users(1, email='')`, and `ensure_owner()` fills it from `OWNER_EMAIL`;
  - `schema_v0.sql` lives in `src/jobseeker/db/`;
  - `owner_first_name(conn)` is in `db/users.py`;
  - Sign out sits in the sidebar foot and phone top bar until plan 3's Settings tab.
- Plan 3 rulings (accepted):
  - `UserPrefs.target_roles_text` keeps the owner's prose roles, so the scorer prompt stays byte-identical;
  - an explicit `title_allow_extra` replaces the catalog allow-words;
  - the importer sets `users.name`;
  - delete uses the schema-derived `user_scoped_tables(conn)`.

## 4. Contracts other plans rely on (keep exactly)
- `verdict(job, prefs, facts, now, blocked, scored)` applies `prefs.min_prescore` **unless `scored=True`**; the pipeline's evaluate depends on it.
- The plan 3 v2 test-DB setup must be a **reusable helper**. Pipeline Task 4 builds a `migrated_owner_db` fixture from it.
- Names used by devops-lead's plans:
  - fixtures: `client_as(id)`, `anon_client()`, `seeded_two`, `app_config`;
  - users: `OWNER_ID`, `User`, `user_by_id`, `owner_first_name`;
  - migrations: `migrations.latest()`, `MigrationContext`;
  - `snapshot(db_path, out) -> Path` in `db/backup.py`;
  - `PUBLIC` in `web/app.py`;
  - config and prefs: `AppConfig`/`AppSearch`/`AppBudgets`/`Role`, `load_app_config(settings.app_config_path)`, `load_user_context(conn, uid, cfg)`, `current_prefs`, `effective_prefs`, `user_scoped_tables`.
- Public routes: `/` (mixed, `optional_user`), `/login`, `/auth/callback`, `/logout*`, `/healthz` (GET + HEAD), `/sw.js`, `/static`, the manifest. The not-invited 403 reuses `landing.html`.
- Migration numbers: v1 auth, v2 onboarding, v3 extras, v4 pipeline, v5 outreach.

## 5. Gotchas
- **pytest:** `FORCE_COLOR= uv run pytest --color=no -p no:warnings` (about 9 s). Without `-p no:warnings`, task-done records a swig DeprecationWarning line as the result. Don't pass `-q`.
- **node:** `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`. It still emits ANSI codes, so grep with `grep -aE "(pass|fail) [0-9]+"`.
- uv's "VIRTUAL_ENV … does not match" warning is harmless.
- The worktree has no `data/`, `.env` or `profile/`. Live-DB checks use a copy only:
  1. `sqlite3 "/Users/user/Desktop/untitled folder/job-seeker2.0/data/jobseeker.db" ".backup /tmp/jsmig/data/jobseeker.db"`
  2. `JOBSEEKER_HOME=/tmp/jsmig OWNER_EMAIL=mkshitij1763@gmail.com uv run jobseeker migrate [--dry-run]`
- Rebuilt tables have `user_id NOT NULL` with no default, so raw test INSERTs into applications/scores/blocklist/usage must pass `user_id`.
- Web routes pass `OWNER_ID` as an interim measure until T8 switches them to the signed-in user.
- **T7, first step:** update the conftest `settings` fixture with `AUTH_TEST`, because `create_app` refuses to start without the auth vars. Otherwise every web test breaks.
- **Unverified T7 risk:** `respx.mock` around Google's token endpoint while using TestClient. If respx intercepts TestClient's transport, monkeypatch `auth.exchange_code` instead.
- `pytest-socket` blocks the network, so mock all Google calls.

## 6. Decisions you must not re-ask (the user decided)
- Oracle Always Free on PAYG with a ₹100 alert; DuckDNS + Caddy; Backblaze B2.
- Roommates get matching only at launch; outreach is switchable per user (`users.outreach_enabled`) and the owner keeps it.
- Free only. Invite-only Google sign-in. No invite emails.
- Inline execution. **Never merge to `main` without the user.**
