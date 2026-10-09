# HANDOFF: backend-lead (multi-user build), updated 2026-10-09 by manager

> **START HERE (new or /cleared session).** You are **backend-lead2** (session name), formerly backend-lead, a senior dev on job-seeker2.0's multi-user hosted app. You report to the coordinator session **`manager`** (use `SendMessage` to `manager`), not to the user. Send design questions to `manager`; it makes the calls or passes them to the user. Background on the product: `HANDOFF.md` §1–§3 (in the same repo). Treat §8 there as history; this file supersedes it for your work.

## 1. Where you work
- **Worktree:** `/Users/user/Desktop/untitled folder/js-mu-backend`, branch **`multi-user`**. You are the only writer on `multi-user`.
- **The Bash cwd resets to the MAIN checkout after every call.** That checkout is on `main` and runs the LIVE app (launchd `com.kshitij.jobseeker` + `.web`). Start every command with `cd "/Users/user/Desktop/untitled folder/js-mu-backend" && …`. **Never edit, switch or build in the main checkout, and never touch its `data/`.**
- **Git:** commit per task, ending messages with the attribution lines your session uses, then `git push origin multi-user` (never force, never `main`). Never merge to `main`; only the user can approve that.
- **devops-lead2** works on `build/devops2` (worktree `../js-devops2`). All its product work is DONE and already merged into `multi-user` (last merge `e32a467` = build/devops2 `74d041e`). When `manager` says so, you merge `origin/build/devops2` into `multi-user` (you own that branch).

## 2. Status (as of 2026-10-09, multi-user @ `e32a467`)
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
  | P3-T5 two-way reevaluate replaces refilter | `69585bc` |
  | P3-T6 resume upload, fact extraction, review, Finish | `c0fe3e5` |
  | P3-T7 Settings page | `b1b3eed` |
  | P3-T8 export and delete account | `770f00f` |
  | P3-T9 safety test, acceptance, Advanced matching, handoff | `558b0fd` |

- **Plan 5** `docs/superpowers/plans/2026-10-08-mu-outreach.md` (spec `docs/superpowers/specs/2026-10-08-mu-outreach-design.md`), base `ee7bed9`:

  | Task | Commit |
  |---|---|
  | P5-T1 token sealing under TOKEN_KEY | `444ff5c` |
  | P5-T2 migration v5, User.outreach_enabled | `d9f0017` |
  | P5-T3 require_outreach gate, outreach router, admin toggle, matching-only pipeline | `d57c803` |
  | P5-T4 owner-scoped contacts, copy-on-write edits, private not-interested | `e69326f` |
  | P5-T5 30-day people-search cache, per-user outreach shares | `f1a8f32` |
  | P5-T6 draft units: ranking, domain pick, Draft now; drafting follows outreach_enabled | `da345fb` |
  | P5-T7 smtp_verify off/on/auto (default off), daily port-25 probe | `ee46a24` |
  | P5-T8 per-user Gmail: connect/callback, sealed tokens, refresh write-back, Reconnect | `f7222dd` |
  | P5-T9 (part 1) delete/export cover gmail_tokens + private contacts | (this commit) |

- **Tests at `e32a467` (all of plans 2, 3, 4, 6 + plan 5 T1–T2):** 736 pytest, 26 node (node baseline is now 26, not 19). `git status` is clean.
- **`manager` independently verified T3:** a real migrate on a `.backup` copy of the live DB gives user_version 1, an empty foreign_key_check, integrity ok, apps 167 / scores 168 / jobs 4497 / user_jobs 4497, all on user 1.
- **NEXT (resume here after /clear):** plan 5 **T9 is half done**. Done and committed: Steps 1–3 (delete/export coverage; 798 pytest, 26 node). **Still to do for T9:** Step 4 acceptance (scratchpad only, never the main checkout): (1) `.backup` copy of the live DB + owner `profile/`, `jobseeker migrate` → v5, FK check `[]`, contacts 15 shared / 1 private, every `application_contacts` link resolves; (2) serve on 127.0.0.1:8010 with throwaway env incl. `TOKEN_KEY` from `jobseeker gen-key`, 390×844 browser (agent-browser) as the owner: job page shows People/Draft/Approve; Settings shows Connect Gmail + the unverified-app note; Approve with no token shows **Reconnect Gmail** → `/gmail/connect?next=/applications/<id>`; (3) as a scripted matching-only roommate: every outreach URL 404s, job page shows "Open job posting ↗" + "Mark applied". Step 5: `HANDOFF.md` "Sub-project 5 built" (TOKEN_KEY separate from BACKUP_KEY; second redirect URI `BASE_URL/gmail/callback`; outreach users are Google test users; owner taps Connect Gmail once; `contacts.smtp_verify: off` on the server; the admin toggle; test count). Then run `task-done docs/superpowers/plans/2026-10-08-mu-outreach.md 9 f7222dd -- …`, push, report T9 to `manager` (it asked for the live-copy migrate + 390px acceptance results), and do the **final whole-branch review** of plan 5 (fresh most-capable reviewer; review range 970c272..HEAD; plan's Review Focus + token handling). Ledger `.superpowers/sdd/2026-10-08-mu-outreach/progress.md`. Every commit also updates this §2 table, this NEXT line and §3, then `git push origin multi-user`. Keep the `_fetch_now_slot.html` includes, the `fetch_now` router line, the alerts card, and runs-deleted-last in `delete_account`. Known minors deferred from the plan 3 review: #4, #7, #8 (see §3).
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
- P3-T6: resume and facts logic lives in shared helpers in `web/onboarding.py` (`accept_upload`, `status_context(conn, uid, base)`, `parse_facts_form`, `save_facts_form`), which Settings reuses with `base="/settings"`. `run_extract(db_path, home, uid, sha, app_config, llm_factory)`. The test PDF helper writes short lines, because PyMuPDF clips long ones.
- P3-T7: `title_deny` is capped at 30 items rather than 10, because the default exclusions alone are 18 words. Settings is the 4th tab, and the phone tab bar is 4 columns. Sign out has moved from the sidebar and top bar into Settings → Account. Settings reuses the P3-T6 helpers.
- P3-T8: `delete_account` nulls `invites.invited_by` for the deleted user, and their invites stay valid. `user_scoped_tables()` is the schema-walk oracle; `invites` is keyed by email and deleted explicitly. Export and delete sit on `settings.account_router` (signed in, not `require_onboarded`). The last admin gets a 403, and the button is disabled.
- P3-T9:
  - **Advanced disclosure (ruling by `manager`):** Settings → Roles has "Advanced (custom matching)", shown only when `title_allow_extra`/`target_roles_text` is set. "Use the role chips instead" clears both. `title_allow_extra` is a filter field (it previews), `target_roles_text` is scoring-only, and an unchanged save keeps the effective Preferences equal.
  - **Extraction errors:** `run_extract` never shows provider text. Any `LLMError` or crash shows "Couldn't read your resume right now…" and is logged. Acceptance caught a raw 401 message on the page.
  - **Test speed:** conftest builds the imported owner DB once per session (32 s → 21 s).
  - **Refilter drift:** the live-copy `refilter` dry run shows 5 hidden and 5 restored. That's pre-existing drift, not the move: migrated and original prefs give identical reports. Spec 4's `jd_hash` re-evaluation should absorb it.
- Plan 3 final review (fresh Opus; rulings by `manager`):
  - Fixed, test-first, in "fix(onboarding): review findings":
    - #1: an onboarded user's POST to `/onboarding/*` (steps, resume, facts, finish) gets a 303 to `/settings` and changes nothing.
    - #2: `parse_facts_form` pairs each achievement with its org before dropping cleared ones.
    - #5: the v2 report lists search queries that are no longer searched.
    - #6: an upload while an extraction is running is refused ("Still reading your previous upload; try again in a minute"), and `run_extract` never saves facts when the file's sha differs from the one it was queued for.
  - #3 (`_apps_needing_drafts` unscoped) was solved upstream by the pipeline merge.
  - **Known minors, deferred:**
    - #4: an unmatched query that isn't already a title word aborts v2's golden check (latent; the live owner passes).
    - #7: Caddy's 6 MB cap gives a bare 413 above 6 MB.
    - #8: deleting an account frees that day's global facts headroom.
- P5-T1: no deviations. `TOKEN_KEY` is required at web startup; `scripts/server/env.example` and `ready.sh` already list it. Tests get it through `AUTH_TEST`.
- P5-T2: no deviations. Live-copy migrate v1→v5 is clean: the FK check is empty, contacts split 15 shared / 1 private (the owner's), the owner has `outreach_enabled=1`, and there are no dangling `application_contacts`. The 5,000-job reevaluate timing test now takes the median of 3 runs (`c48d5e7`, a devops-lead2 flake report).
- P5-T3: `require_owner` is replaced by `require_outreach` (`require_onboarded` + `users.outreach_enabled`, else 404), and `can_outreach` now reads `users.outreach_enabled`. The outreach routes moved verbatim from `web/application.py` to `web/outreach.py` (`_back` stays in `web.application`; `_raw_for` is imported from `web.outreach`). `outreach.router` and `contacts.router` are mounted with `[require_onboarded, owned_app, require_outreach]`, so the contacts `card` GET is gated too. Ruling: `test_roommate_gets_404_on_outreach_routes_of_their_own_application` now requests each route with its own methods (a POST to the now-gated `card` GET would be 405, not 404). Ruling: pipeline cards' "Ready to approve"/"Find contacts"/"Send in Gmail" labels are also skipped when `not can_outreach` (belt and braces; `drafted` is unreachable for them anyway). Merge of `build/devops2` `13cfdfa` (security-review fixes) is `970c272`.
- P5-T4 (closes plan 2's I1 at the root): `upsert_contact` only ever matches shared rows (`owner_user_id IS NULL`). `edit_contact` copies shared rows on write (new private row, only this application's link re-pointed), except a bounce-only edit, which updates the shared row. A user's own row is edited in place. `save_contact` always writes or updates the user's own private row. Ruling: `save_contact` still raises `BlockedContact` when the acting user blocked a shared row or their own row with the same email or LinkedIn URL (the plan's narrower match would have let a blocked person be re-added by hand). Extra test: `test_i1_replay_roommate_edit_leaves_owner_row_untouched`.
- P5-T4 trade-off (accepted by `manager`, per the spec): a bounce-only edit by any outreach-enabled user, a roommate included, marks the shared row bounced for everyone.
- P5-T5: `outreach_limits(conn, contacts, global_drafts_per_day)` splits every service by `max(1, eligible_count(conn, "draft"))`, so the n is onboarded, not-disabled, outreach-on users (manager's ruling: reuse `pipeline/eligible.py`, not `outreach_user_count`). For that, `drafts_enabled(user)` now returns `user.outreach_enabled` (pulled forward from T6). Ruling: the plan's usage test inserts user 2 without prefs; ours onboards user 2, because eligible_count counts only onboarded users (a not-yet-onboarded user can't reach outreach routes anyway). `_search` and the Apify people search go through `people_searches` (30 days, keyed by normalised company + query/kwargs or role words + city); a hit spends nothing. Budget notes read "Your X share is used for <Month>" / "Shared X budget used for <Month>" (`Budget.exhausted_note`), and `Budget.summary` shows "Your … · All …". The finder's Budget uses IST `app_now`. `contacts_limits` remains only for `tests/test_contacts_setup.py`. Updated existing tests: `test_budget_exhausted_skips_searches` (wording), `test_budget_caps_and_summary` (summary), `test_draft_round_robin` (`test_drafts_enabled_follows_the_switch`; the slice test makes user 2 an outreach user instead of an admin).
- P5-T6: people ranking and `pick_domain` each spend 1 `draft` unit in `find_contacts` (ranking refused with "Your drafting share is used for today" as a FinderError, before any LLM call; a refused domain pick adds the note and leaves the domain unset). `draft_now` checks the share first and spends after a successful draft. Ruling: `draft_round_robin` keeps devops's `share_divisor(conn, "draft", len(drafters))` share instead of the plan's `outreach_limits` rewrite: since T5, eligible_count("draft") counts outreach users, so they agree, and share_divisor keeps the security-review floor (`in_run`). The plan's `test_drafts_enabled_follows_the_switch` landed in T5; T6's new round-robin tests passed on first run for the same reason.
- P5-T7: `ContactsConfig.smtp_verify` defaults to `off` (also in `config/app.example.yaml`), so on the Mac too, finds skip SMTP unless `app.yaml` says `on` or `auto`. **The owner's current Mac setup verified over SMTP; if the Mac stays live after this lands, set `contacts.smtp_verify: on` in its `config/app.yaml`.** `auto` uses `contacts/smtp_probe.port25_open` (TCP to gmail-smtp-in:25, 5 s, remembered 24 h in `app_state`). A `PortBlocked` during `on` now shows the same server wording. `tests/test_contacts_finder.py` gets an autouse fixture that sets `smtp_verify="on"` (those tests cover SMTP itself), and its port-blocked test expects the new wording.
- P5-T8: `/gmail/connect` + `/gmail/callback` (behind `require_outreach`; cookie `__Host-js_gmail_oauth`; scope `openid email gmail.compose`, offline, consent, `login_hint`, PKCE). Tokens live in `gmail_tokens`, sealed under `TOKEN_KEY` with AAD `user:<id>` (`db/gmail_tokens.py`); `account_email` comes from the ID token, so Settings shows where drafts really go. `load_service(conn, uid, key)` writes a refreshed token back; `invalid_grant`, a decrypt failure (row moved to another user, key rotated) or an unparsable token mark it `expired` → Reconnect. `create_draft` 401/403 → `reconnect=True`; callers go through `outreach.gmail_failed`, which marks it expired and redirects with `reconnect=1`, so the error flash shows **Reconnect Gmail** back to the same job (drafts already made stay named). `app.state.gmail_factory(conn, uid)`. `auth.exchange_code` returns the token JSON (`redirect_path` param). Removed: `authorize`, `InstalledAppFlow`, `jobseeker auth-gmail`, `Settings.secrets_dir`. Settings → Account has the Gmail card (only with outreach on). Ruling: tests compare unescaped HTML where copy has an apostrophe; `auth_message.html` takes optional `retry`/`heading`. **Cutover: the owner taps Settings → Connect Gmail once (the Mac's `secrets/token.json` is not migrated). Every outreach user's Gmail address must first be added as a test user in Google Cloud → OAuth consent screen, and the Web client needs the redirect URI `BASE_URL/gmail/callback`.**
- P5-T9 (part 1): `delete_account` unlinks `applications.contact_id` before the second loop, which deletes `contacts WHERE owner_user_id = ?` (found by `user_scoped_tables`) and `gmail_tokens`; `runs` still go last. `export_zip` adds `gmail.json` (`account_email`, `connected_at`; never the token). Ruling: the plan's export test checked `b"rt" not in` every file, which matches ordinary words ("start"); it now uses a distinctive refresh token `rt-SECRET-42`.
- devops-lead2's Fetch now (pipeline T14) put `{% include "_fetch_now_slot.html" %}` in `today.html`, `settings.html` (Account) and `onboarding/done.html`, and `include_router(fetch_now, require_onboarded)` in `app.py`. **Keep those lines** when plan 5 edits these files.
- devops-lead2's pipeline T16 found an FK bug in `delete_account`: `run_requests.run_id` can point at the user's own run. `runs` is now deleted last in the second loop (`tests/test_account_pipeline.py`). Plan 5 T9's delete changes must keep that ordering.
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
