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
  | T7 sessions, /login, /auth/callback, /logout | `e920d9b` |
  | T8 route guards, owned_app, signed-in user | `04259b6` |
  | T9 CSRF Origin check | `8477b1c` |
  | T10 admin page, sign-out controls | `ea42f25` |
  | T11 web isolation, acceptance, HANDOFF.md | `22fd45f` |

- **Plan 3** `docs/superpowers/plans/2026-10-08-mu-onboarding-settings.md` (spec `docs/superpowers/specs/2026-10-08-mu-onboarding-settings-design.md`), base `2f473a9`:

  | Task | Commit |
  |---|---|
  | P3-T1 UserPrefs, AppConfig, effective_prefs, fixtures | `0f773be` |
  | P3-T2 migration v2, profile importer (+ where_confirmed) | `4f68793` |
  | P3-T3 request-scoped prefs, DB facts, CLI --user | `08ec981` |
  | P3-T4 require_onboarded, onboarding steps 1-3 | `b86497d` |
  | P3-T5 two-way reevaluate replaces refilter | `this commit` |

- **Tests at `P3-T5`:** 599 pytest, 19 node. `git status` is clean.
- **`manager` independently verified T3:** a real migrate on a `.backup` copy of the live DB gives user_version 1, an empty foreign_key_check, integrity ok, apps 167 / scores 168 / jobs 4497 / user_jobs 4497, all on user 1.
- **NEXT:** plan 3 **Task 6** (resume upload, fact extraction, review, Finish), then T7–T9. Ledger `.superpowers/sdd/2026-10-08-mu-onboarding-settings/progress.md`. Rule from `manager`: every task commit also updates this §2 table, this NEXT line and §3, then `git push origin multi-user` (never main, never force). A task's own row says "this commit"; the next task commit fills in its hash.
- **Ledger:** `.superpowers/sdd/2026-10-08-mu-accounts-auth/progress.md` (git-ignored, on disk). Resume from the first task without a "complete" line. Skill scripts: `…/plugins/cache/claude-plugins-official/superpowers/6.4.1/skills/executing-plans/scripts/{task-start,task-done} <plan> <N> [BASE] -- <test cmd>`. The BASE for the next task is the last task commit in the table above. Cloud sessions have no ledger: this file is the record.
- **Execution:** inline (superpowers:executing-plans), with TDD per task. After each task, send `manager` one line: task, commit, pytest/node counts. Stop and message `manager` if a task needs a design change beyond the spec, or if tests can't be made green.

## 3. Rulings and deviations already made (not in the plan file)
- T3: two raw `INSERT INTO blocklist` statements in `tests/test_contacts_finder.py` (about lines 126 and 140) pass `user_id=1`.
- T3: four legacy v0 catch-up tests (`test_db_migration.py` x3, `test_contacts_setup.py::test_migrates_older_db`) build their DB from `SCHEMA_V0` and reopen it with `connect(path, check_version=False)`.
- **T4 (code):** `expire_unscored` also INSERTs `'stale: never scored'` user_jobs rows for old, unscored jobs that have no verdict row. The plan only UPDATEd existing rows, which left them unexpired.
- T4: test verdict reads use `(get_user_job(conn, 1, id) or {}).get("filter_reason")`.
- T6: `Settings.owner_email` is defined once (T1); T6 adds `google_client_id/secret`, `base_url`, `secret_key`, `cookie_secure`. Extra test: `test_another_account_cannot_claim_owner_by_email_after_sub_is_set`. `set_disabled` tolerates a missing row.
- T7: no deviations; respx around TestClient works (no monkeypatch of `exchange_code` needed).
- T8 (accepted by `manager`): conftest gains plain `signed_in_client(settings, user_id=1, *, follow_redirects, **app_kwargs)`; `client_as` delegates to it, and old web-test helpers that only take `settings` use it. The Today greeting reads `users.name`, so greeting tests set `users.name`. `tests/test_web_view.py` GETs `/today` signed in.
- T9: no deviations. `base_url` must equal the browser origin exactly, or every POST gets 403 "Request blocked".
- T10: no deviations. `admin.html` is a plain three-card page (Invites, Users, Usage); no new CSS (`.topbar-signout` has no rule yet).
- T11: the T8 guard tests passed vacuously. FastAPI 0.142 keeps included routers as `_IncludedRouter` in `app.routes`, so the `isinstance(r, APIRoute)` walks saw zero routes. The walk now uses `fastapi.routing.iter_route_contexts`, which gives effective paths plus router-level deps, and asserts it finds more than 20 routes. The real guards were already correct: all pass, and an unguarded `/leak` probe now fails. Acceptance on a live-DB copy: counts unchanged, fk check empty, the un-migrated copy refuses to start.
- P3-T1: the spec says "where" is complete with ≥1 city OR `remote_india_ok`, and remote defaults to True, so `UserPrefs().complete() == ["roles", "experience"]`. The plan's test expected all three; I kept the spec. `config/app.example.yaml`'s `default_title_deny` is the owner's full 18-item list. Personal values are gone from test fixtures: `tests/fixtures/preferences.yaml` uses "Asha Owner".
- P3-T1/T2 (ruling by `manager`, replaces my P3-T1 ruling): "where" is complete only with ≥1 city, or with `remote_india_ok` plus `UserPrefs.where_confirmed`. The Where step sets `where_confirmed` when saved; the importer sets it True for the migrated owner. `UserPrefs().complete() == ["roles", "where", "experience"]`.
- P3-T2: `tests/fixtures/facts.json` is anonymised (Acme Health, Bigfour Consulting); the conftest literal names real employers. `db/profile.py` starts in T2 with `get_user_prefs`, because T2's test needs it. `import_profile` aborts only on per-user golden fields: `min_prescore`/`thresholds` come from `app.yaml`, and an existing admin `app.yaml` wins. Live-copy acceptance with the REAL owner profile: v1+v2 ok, full golden dict equal, scorer prompt byte-identical, resume 600/700, fk check empty.
- Plan 2 security review (fresh Opus reviewer over `4a029ff..22fd45f`; `manager` ruled all five fixed, in commit "fix(auth): security review"):
  - I1: contacts and company_domains are shared rows, so user B could overwrite A's contacts. The interim gate is `require_owner` (404 for non-owners) on application `/contact`, `/drafts/{kind}`, `/draft`, `/approve`, `/followed-up`, and on every POST under `/contacts/`. The read-only card GET stays open. Covered by a route-walk test and a roommate-404 test. **Plan 5 replaces `require_owner` with `require_outreach` and adds copy-on-write contacts per spec 5; say so at the top of the outreach plan.**
  - I2: an invited email already bound to another Google `sub` gets a 403 on landing, "already linked to a different Google account", instead of a 500.
  - M1: `/logout/all` no longer re-issues the session cookie.
  - M2: the app refuses to start with a `SECRET_KEY` under 32 chars (`gen-key` gives 44).
  - M3: the OAuth cookie is cleared on every callback exit.
- Merge of build/devops2: `test_uninvited_gets_403_with_owner_name_and_no_row` now expects "Ask Asha for an invite.", since the fixture owner's name is imported since P3-T2.
- P3-T3: `db/backup.backup(db_path, dest, now)` no longer takes `facts_path`, because facts live in the DB. The web app refuses to start without `config/app.yaml`. A CLI `--user` with an unknown email exits 1. Tests use conftest `owner_resume(settings)` and `save_facts` in place of the removed `Settings` paths.
- Outreach UI is hidden for non-owners (ruling by `manager`). The `can_outreach` template flag is set in `render()` and is true only for the owner; plan 5 swaps it for `users.outreach_enabled`. A roommate's job page shows "Open job posting ↗" plus "Mark applied" (POST `/status` `applied_via_portal`, not owner-gated). It has no People or Draft tabs and no Approve/Find/Draft/Gmail markup, and its More menu drops Mark sent, followed-up and Regenerate. Covered by render tests. **Open:** Today still shows outreach tiles (Need contacts, Ready to approve, Send in Gmail) to roommates.
- P3-T4: the existing `.chip` style is kept, and only `.chip:has(input:checked)`, `.chip-group`, `.field`, `.field-err` and the sticky actions were added. The Where step saves `where_confirmed=True`. `/onboarding/resume` returns 404 until P3-T6.
- Today for non-owners (ruling by `manager`): the tiles are "New today" and "Shortlisted", and there is a "Shortlisted" section ("Apply on the company site, then tap Mark applied"). Send, Follow-ups, Ready and Find are hidden. `queries.today()` gains `shortlisted`. This closes the open item in the `can_outreach` ruling above.
- P3-T5: `reevaluate` skips a pre-outreach application whenever its job goes from unfiltered or never-judged to filtered; the plan skipped only on jobs that already had a verdict row. `verdict(job, prefs, facts, now, blocked, scored)` keeps the plan 2 contract. `pipeline/refilter.py` is gone; `jobseeker refilter [--user] [--apply]` wraps `reevaluate` and also lists restored jobs.
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
