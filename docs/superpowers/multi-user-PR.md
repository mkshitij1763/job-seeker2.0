# PR: multi-user hosted app (`multi-user` → `main`)

> Draft description. **Not opened.** Merging to `main` needs the user's approval.

## Summary
This turns the single-user Mac app into a small invite-only web app for the owner and two roommates, hosted on an Oracle Always Free VM behind Caddy + DuckDNS. Each person signs in with Google, onboards with their own roles, cities, pay and resume, and gets their own filtered and scored matches. Outreach (contact finding, drafts, Gmail drafts) is a per-user switch: on for the owner, off for roommates at launch. The app still never sends email.

Base: `main` @ `933d1f4` (the merge base). 141 commits; 234 files changed, +27,764 / −1,162.

## What changed
Each sub-project has a spec and plan in `docs/superpowers/{specs,plans}/2026-10-08-mu-*`.

- **Hosting** (`mu-hosting`): `scripts/server/` (`bootstrap.sh`, `ready.sh`, `js`, `update.sh`, systemd/Caddy/DuckDNS templates, `env.example`), `scripts/deploy.sh` (refuses during a run, migrates, `/healthz` check, automatic rollback), and `serve --proxy-headers`.
- **Accounts and auth** (`mu-accounts-auth`): Google sign-in (an OAuth Web client), invite-only allow-list, server-side sessions (`__Host-` cookies), sign out / sign out everywhere, route guards (signed-in user, `require_onboarded`, `owned_app`, `require_admin`), an Origin-based CSRF check, `/admin` (invites, users, usage), and a versioned migration framework (`jobseeker migrate`, which backs up first and refuses an un-migrated DB at startup).
- **Onboarding and Settings** (`mu-onboarding-settings`): per-user preferences and facts in the DB; 4-step onboarding plus resume upload and AI fact extraction with review; Settings with a two-way "hides N, brings back M" preview; `refilter` becomes a two-way `reevaluate`; Download my data (zip) and Delete my account. Server-wide knobs move to `$JOBSEEKER_HOME/config/app.yaml`.
- **Per-user pipeline** (`mu-per-user-pipeline`): one shared fetch over the union of all users' searches (with a rotating cap), then filter, score and draft per user (`user_jobs`, per-user `scores`/`applications`), even per-user shares of every free quota, `tick` every 5 minutes with an IST clock and a heartbeat run lock, Fetch now, and run notes per user.
- **Per-user outreach** (`mu-outreach`): `users.outreach_enabled` with an admin toggle (`require_outreach` 404s everything when off); owner-scoped contacts (shared finder rows, private copy-on-write edits, per-user domain overrides and block lists); a 30-day people-search cache; per-user Gmail through a web OAuth flow (`gmail.compose`, PKCE), tokens sealed with AES-GCM under `TOKEN_KEY`, a compare-and-set refresh write-back, and Reconnect Gmail; `contacts.smtp_verify: off|on|auto` (default `off`; port 25 is blocked on Oracle); `Budget.take`/`refund`, so a failed AI call costs nothing.
- **Extras** (`mu-extras`): daily web push "N new matches" (VAPID), nightly backup archives with an encrypted B2 copy, `jobseeker restore`, `gen-key`/`vapid-keys`, and the admin usage view.
- **Removed**: `jobseeker auth-gmail`, the installed-app Gmail flow and `secrets/`; the runtime reads of `profile/` (imported once by migration v2).
- **Docs**: `README.md` rewritten for the hosted app (plus a short "run locally" section), `.env.example` lists every `Settings` field, and `HANDOFF.md` §8 has the summary and the cutover checklist.

## Migrations (forward-only; `jobseeker migrate`, with a pre-migration snapshot in `data/backups/`)
| Version | Name | What it does |
|---|---|---|
| v1 | users and scoping | `users`, `invites`, `sessions`, `user_jobs`; rebuilds `applications`, `scores`, `blocklist` and `usage` with `user_id NOT NULL`; every existing row goes to user 1 (`OWNER_EMAIL`) |
| v2 | preferences, facts and resume | `user_prefs`, `user_facts`; imports the owner's `profile/` (preferences, facts, resume → `data/users/1/`), writes `config/app.yaml`, and aborts unless the golden matching fields are unchanged |
| v3 | extras | `push_subscriptions`, the per-user alert marker, the `backups` log |
| v4 | pipeline | `locks`, `run_requests`, run triggers/parents, `board_fetches` (Fetch now skips boards fetched OK within 12 h), `scores.profile_hash` (back-filled) |
| v5 | per-user outreach | `users.outreach_enabled` (the owner 1), `contacts.owner_user_id` (found contacts shared, hand-added ones private to the owner), `people_searches`, `gmail_tokens`, `user_company_domains` |

Each migration runs in its own transaction with foreign keys off and is rolled back if `foreign_key_check` isn't empty. A fresh DB is created directly at v5.

**Verified on a fresh `.backup` copy of the live DB plus `profile/` (2026-10-09, then deleted):** v0→v5 clean; every pre-existing table's count unchanged (applications 242, scores 244, jobs 5487, contacts 16 → 15 shared / 1 private, drafts 165, events 239, runs 10); `user_jobs` 5487; `foreign_key_check` empty; `integrity_check` ok; golden fields and facts equal to the files; the scorer system prompt byte-identical (6172 chars).

## Testing
- 831 pytest, 26 node tests; also green with `TZ=UTC` and `TZ=America/New_York`.
- Route-walk tests prove every non-public route is guarded and every outreach route 404s for a user with outreach off.
- Acceptance runs on live-DB copies after plans 2, 3 and 5, plus a full local trial run of the cutover (CSRF, invites, onboarding, isolation, outreach gating, a forged Gmail callback, tick, Fetch now, an encrypted restore, export and delete).
- Real Google consent, Caddy/Let's Encrypt and the VM are checked at deploy (hosting plan Task 5).

## Deploy / cutover
Follow `HANDOFF.md` §8 "Cutover checklist" (hosting plan Task 5 + hosting spec §2/§10). The key manual steps: the Web OAuth client with both redirect URIs and outreach users as test users; `.env` with distinct `SECRET_KEY`/`TOKEN_KEY`/`BACKUP_KEY`; `js migrate`; `js refilter --apply` once for the owner; `contacts.smtp_verify: off` on the server; the owner taps **Connect Gmail** once.

## Rollback
- **Before the Mac agents are turned off** (cutover step 7): nothing on the Mac has changed. Run `scripts/install_launchd.sh` and carry on with `main`.
- **After cutover:** the Mac's `data/jobseeker.db` is kept untouched for 2 weeks; `main` runs on it as before (anything done on the server since is lost). `main` can't open a v1+ DB, so don't point it at the server's DB.
- **Server, bad deploy:** `scripts/deploy.sh` rolls back code automatically when `/healthz` fails; `scripts/deploy.sh --rollback` does it on demand. If a migration ran, restore its snapshot from `data/backups/pre-migrate-v<N>-<ts>.db` (stop web and the timer first).
- **Data loss on the server:** `js restore` the latest nightly archive (local, or the `.enc` from B2).
- **Undo the merge on `main`:** `git revert -m 1 <merge sha>`.

## Known deferred minors
- Plan 3 review #4: a search query that isn't already a title word aborts v2's golden check. This is latent; the live owner passes.
- Plan 3 review #7: Caddy's 6 MB request cap gives a bare 413 for a resume over 6 MB.
- From `main`: with no `GROQ_API_KEY` at all, Find contacts and Regenerate return a 500.
- A bounce-only contact edit by any outreach user marks the shared row bounced for everyone (an accepted trade-off of spec 5).
- Found in the readiness pass: on a fresh install, `jobseeker init` says "Run `jobseeker migrate` to … write config/app.yaml", but `migrate` on a new DB says "Already at v5" and writes nothing. Copy `config/app.example.yaml` by hand (the README says so). A wording fix in `init`.
- Found in the readiness pass: `config/app.yaml` isn't in `.gitignore`. On the server it lives outside the checkout (`/srv/jobseeker/config`), but a local run with `JOBSEEKER_HOME=.` would leave it untracked in the repo.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
