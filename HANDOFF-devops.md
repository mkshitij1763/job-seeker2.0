# HANDOFF: devops-lead (multi-user build), 2026-10-08

> **START HERE (new session).** You are **devops-lead**, a senior dev on job-seeker2.0's multi-user hosted app. You report to the coordinator session **`manager`** (use `SendMessage` to `manager`), not to the user. Send design questions to `manager`; it makes the calls or passes them to the user. Background on the product: `HANDOFF.md` §1–§3. Treat §8 there as history; this file supersedes it for your work.

## 1. Where you work
- **Worktree:** `/Users/user/Desktop/untitled folder/js-build`, branch **`build/devops`** (from `plans/devops` `7136ea9`). You are the only writer on it.
- **The Bash cwd resets to the MAIN checkout after every call.** That checkout is on `main` and runs the LIVE app. Start every command with `cd "/Users/user/Desktop/untitled folder/js-build" && …`. **Never touch the main checkout or `multi-user`.** backend-lead owns `multi-user`, in `../js-mu-backend`.
- **Git:** commit per task, ending messages with the attribution lines your session uses. Don't push. `manager` merges `build/devops` into `multi-user` after plan 2 lands.
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

- **Tests at `99b7102`:** 443 pytest, 19 node, verified by `manager`. `git status` is clean.
- **NEXT:** **extras Task 1** in `docs/superpowers/plans/2026-10-08-mu-extras.md`, then T2 crypto, T3 SigV4, T4 archive + retention, T5 restore, T6 push send. Then pipeline **T2** (profile_hash) and **T6** (build_plan + plan-driven JobSpy sources) in `docs/superpowers/plans/2026-10-08-mu-per-user-pipeline.md`. Then report to `manager` and stand by. Everything else (extras T7–T14, pipeline T3–T5 and T7–T16, hosting T5) waits for plans 2/3 and `manager`'s merge.
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
