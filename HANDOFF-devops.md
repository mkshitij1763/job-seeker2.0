# HANDOFF: devops-lead (multi-user build), 2026-10-08

> **START HERE (new session).** You are **devops-lead**, a senior dev on job-seeker2.0's multi-user hosted app. You report to the coordinator session **`manager`** (use `SendMessage` to `manager`), not to the user. Send design questions to `manager`; it makes the calls or passes them to the user. Background on the product: `HANDOFF.md` §1–§3. Treat §8 there as history; this file supersedes it for your work.

## 1. Where you work
- **Worktree:** `/Users/user/Desktop/untitled folder/js-devops2`, branch **`build/devops2`** (from `origin/multi-user` `2f473a9`, the merge of `build/devops` into plan 2). You are the only writer on it. The old `js-build` / `build/devops` is merged and finished.
- **The Bash cwd resets to the MAIN checkout after every call.** That checkout is on `main` and runs the LIVE app. Start every command with `cd "/Users/user/Desktop/untitled folder/js-devops2" && …`. **Never touch the main checkout or `multi-user`.** backend-lead owns `multi-user`, in `../js-mu-backend`.
- **Git:** commit per task, ending messages with the attribution lines your session uses. Don't push. Push `build/devops2` only (never force, never main or multi-user); `manager` merges it into `multi-user`.
- **zsh doesn't word-split `$VAR` commands;** use a shell function. Don't chain `grep … && git commit`, because grep also matches "failed".

## 2. Status (at pause)
- **Order set by `manager`:** pipeline T1 ✓ → hosting T1–T4 ✓ → **extras T1–T6** → **pipeline T2, T6** → stand by.
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
| (this commit) | extras T8, `nightly_backup` + `jobseeker backup` (tiny cli.py edit: the `backup` command body only) |

- **Tests at `2f473a9` (multi-user, plan 2 complete):** 550 pytest per `manager`.
- **NEXT (approved by `manager`, in order):** extras T10 (notify) → pipeline T9 → T10 → T11 → T15 → extras T11 (unblocked: plan 3 T4 landed at `3ab1864`; merge origin/multi-user first; `/push/*` and `/sw.js` stay WITHOUT `require_onboarded`, so add them to the guard test's exemption list) → merge origin/multi-user (plan 3 T5 `69585bc`) → pipeline T8 (build ON plan 3's `pipeline/evaluate.py`, don't redefine `verdict`) → T12 → T13. Still waiting on plan 3: extras T12, T14; pipeline T14, T16; hosting T5 (manual). Stay out of files plan 3 T4–T9 edit (web/app.py, web/deps.py, cli.py, pipeline/evaluate.py, pipeline/refilter.py, db/account.py, base.html, onboarding/settings modules) or keep edits tiny and report them. The executing-plans final whole-branch review is still owed at the end.
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
