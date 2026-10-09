# HANDOFF — job-seeker2.0 (2026-10-08, `main` @ `9f9c416`)

> **START HERE (new session):** §1–§7 describe the single-user app on `main`. The multi-user hosted app is **built on `multi-user`** (§8), waiting for the user's merge decision and the cutover checklist in §8.

## 1. OBJECTIVE
Personal, local, free-tier job-search copilot for Kshitij Meshram (he/him, PA @ Inito, ~1.3 yr exp). Every day it finds India PM/PA/APM/Founder's-Office roles; on demand it finds the 3 right people per company with work emails; Gmail drafts (never sent) go out from a phone-friendly dashboard.

## 2. CURRENT ARCHITECTURE
- **Stack:** Python 3.13 + uv; SQLite (WAL); FastAPI + Jinja + HTMX (`hx-boost`); vanilla JS/CSS; Groq free tier (`openai/gpt-oss-20b` scoring + website pick, `openai/gpt-oss-120b` drafting/facts/people ranking); `python-jobspy==1.2.0` (pinned: uses private `LinkedIn._get_job_details`); `dnspython`; `smtplib`; pytest + respx + pytest-socket (no network); `node --test` (Node 26) for `static/swipe.js`.
- **Layout** (all under `src/jobseeker/`):
  - `sources/`: Greenhouse/Lever/Ashby adapters + `jobspy_source` (LinkedIn/Naukri/Indeed) + `registry`.
  - `pipeline/`: `normalize`, `prefilter`, `prescore`, `discovery` (ATS board auto-discovery), `run` (daily orchestration).
  - `scoring/`, `outreach/` (drafter + guards), `profile/` (facts from resume), `gmail/` (compose scope, `drafts.create` only).
  - `contacts/`: `names` (cleanup, 8 email patterns, inference), `domains` (JD/website/MX, `pick_domain` via Groq, `FREE_MAIL`), `smtp_verify` (RCPT-only, catch-all probe, refusal → `VerifyUnavailable`), `tavily`, `people` (search, parse, `rank`, index-guarded), `providers` (Apify, Hunter), `finder` (orchestrator, `run_find` background job).
  - `db/`: `schema.sql`, `core` (`connect` auto-migrates: `REQUIRED_TABLES`, `NEW_COLUMNS`), `jobs`, `applications` (status machine, undo, blocklist), `queries`, `companies` (discovered boards), `contacts_repo`, `usage` (`Budget` free-tier guard), `runs`.
  - `web/`: `app` (`create_app`, `asset()` fingerprinted static URLs), `inbox`, `application` (detail, approve), `contacts` (find/card/remove/edit/domain/#3), `pipeline`; `templates/` (`base`, `inbox`, `application`, `_people`, `pipeline`); `static/` (`app.css` desktop, `mobile.css` phone ≤640px, `keys.js`, `swipe.js`, `manifest.webmanifest`, icons).
- **Runtime:**
  - launchd `com.kshitij.jobseeker`: daily run at 11:15 (runs on wake).
  - launchd `com.kshitij.jobseeker.web`: dashboard on `127.0.0.1:8000`, KeepAlive.
  - `tailscale serve --bg 8000`: `https://delulu.tail1c97dd.ts.net`, tailnet-only (Mac `delulu`, `iphone-15`).
  - Both launchd agents are installed by `scripts/install_launchd.sh`.
- **Config:**
  - `profile/preferences.yaml`: cities, title allow/deny, `drop_if_min_years_at_least: 2.5`, `min_prescore: 30`, `budgets` (score 80 / draft 10), `search:` (JobSpy), `contacts:` (Tavily 950/mo, Apify $4.50/mo, Hunter 45/mo, SMTP 60/day, `sender_email`).
  - `.env` (600, git-ignored): `GROQ_API_KEY`, `TAVILY_API_KEY`, `APIFY_API_TOKEN`, `HUNTER_API_KEY`.
  - `secrets/credentials.json` + `token.json`: Gmail OAuth, Testing mode, so re-auth about weekly with `uv run jobseeker auth-gmail`.
- **Docs** (`docs/superpowers/`): specs (MVP, job-discovery, mobile-access, contact-finder) + matching plans.

## 3. COMPLETED SO FAR
- [x] **MVP:** ATS fetch, dedup, prefilter, Groq scoring, drafting (email/LI note/DM, fact-grounded), dashboard, Approve → Gmail draft with resume and "Hi <first>," greeting.
- [x] **Job discovery:** JobSpy search by role × city (5,800 jobs/run), ATS board auto-discovery (5 boards found, 95 with none), local pre-score ranking, LinkedIn description fetch (≤15/run, 2 s pause).
- [x] **Mobile:**
  - phone layout (cards, sticky Approve bar, More menu, JD folded under the header);
  - swipe left = Skip, right = Snooze, with an Undo toast;
  - Undo-last-status route;
  - home-screen PWA;
  - fingerprinted assets (fixes iOS stale CSS).
- [x] **Contact finder:**
  - Find contacts button → background job + 3 s card polling;
  - Tavily public LinkedIn search → Groq top-3 (hiring_manager / team_lead / peer / recruiter / founder);
  - domain → MX → SMTP RCPT verify, with Apify/Hunter fallbacks;
  - Approve drafts wave 1 (#1 + #2, plus any manual contact as rank 0);
  - #3 offered 5 days after `sent` with no reply;
  - Not interested blocks all linked people;
  - editable per-company email domain.
- [x] **Live-verified:** Tracxn 3/3 SMTP-verified; slice set to `sliceit.com` (M365 refuses checks, so 3 likely); Headout 2 verified + 1 likely. Usage as of 2026-10-08: Tavily 29/950, Apify $0.21/$4.50, Hunter 4/45.
- [x] **Data state:** 3,948 jobs; applications drafted 15, shortlisted 9, approved 1, new 11, skipped 55 (2.5-yr cutoff); 3 apps have People.
- **Decisions and assumptions (do not re-ask):**
  - **Free only:** no paid APIs or proxies. Wellfound/YC/Instahyre/Cutshort out of scope.
  - **LinkedIn:** never automate the user's account (ToS/ban risk). Public `linkedin.com/in` via Tavily only.
  - **Email:** the app never sends email. SMTP stops before `DATA`.
  - **Experience cutoff:** 2.5 yrs (user changed from 8). Parser handles decimals, ranges (lower bound), "N+ years in/as/working", and skips company boilerplate (`_BOAST_BEFORE`).
  - **Title deny:** includes designer, engineer, engineering, developer, architect, product marketing.
  - **Contact finding:** on demand only. Outreach is top-2 now, #3 after 5 days. A re-run is refused once anyone has been emailed.
  - **Emails:** verified addresses are kept only if on the current company domain; bounced addresses are never re-guessed; personal/free-mail addresses are never used.
  - **SMTP replies:** `5.1.x` = no such mailbox; `5.4.x`/`5.7.x`/policy wording = refusal (`catch_all=2`, remembered).
  - **Network:** the office/home IP is on the Spamhaus SBL, so M365 servers refuse checks. Google Workspace works. Apify covers the gap.
  - **Daily run:** at 11:15 because the MacBook is closed before about 11:00. Dashboard reachable 11:00–23:59.
  - **No app login:** the tailnet is the access control.

## 4. NEXT STEPS (RANKED)
1. **FIRST:** `cd "/Users/user/Desktop/untitled folder/job-seeker2.0" && FORCE_COLOR= uv run pytest --color=no`. Expect `400 passed`. Node: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs` (19 passed). Then go to §8.
2. **User usage week:** send the 15 drafts from the phone (Find contacts → Approve → send in Gmail → **Mark sent**). Collect friction notes before building more.
3. **Deferred minors: DONE** (`c34ed71..8c84d75`, 11 commits, TDD). Notes for whoever touches them next:
   - `domain_from_text` uses a two-way prefix rule (label starts with the joined name, or the name starts with a label covering its first word). The handoff's strict "label starts with the full name" lost 28 of 271 correct real-data domains (sarvam.ai, kotak.com); the two-way rule loses 5 loose ones, which fall back to Groq pick.
   - `company_domains.catch_all_at` (new column, auto-migrated): TTL is 30 days (`CATCH_ALL_TTL`). Old rows date from `checked_at`.
   - Gmail errors now read "Gmail draft not created: …", and each message says what to do.
   - **Company alias table: skipped by agreement.** The live data has 167 Paytm jobs and 0 listed as One97. Build it only if the user sees a real duplicate under a legal name.
4. **`jobseeker refilter`: DONE** (`cb9574a`). It is a dry run unless `--apply`, never re-judges age, and skips only new/shortlisted/drafted apps. On live data (2026-10-08) it finds 0 changes because the earlier one-off scripts already applied the current rules.
5. **Reply tracking: DECIDED (2026-10-08).** Mark replied stays manual, and there is no Gmail read scope. Don't propose it again.
6. **Housekeeping: DONE** (2026-10-08). The 7 `data/*.bak*` files were deleted with the user's OK. `HANDOFF.md` is tracked in git since 2026-10-08 (the user asked to push it). Keep secrets out of it.

## 5. KNOWN BLOCKERS/BUGS
- **None failing.** 369 pytest + 15 node tests are green; nothing is half-refactored. Node tests: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/swipe.test.mjs`.
- **Environment gotchas:**
  - The session sets `FORCE_COLOR=3`. Prefix test commands with `FORCE_COLOR=` and use `--color=no`, and use `NO_COLOR=1` for node.
  - Don't pass `-q` (`addopts` already has `-q`; `-qq` hides the summary).
- **Port 8770 belongs to macOS `sharingd`.** Use 8771+ for throwaway test servers. Use `JOBSEEKER_HOME=<tmp copy>` with no `secrets/`, so Approve can't create real drafts. Copy the DB via `sqlite3 data/jobseeker.db ".backup '<tmp>/data/jobseeker.db'"`.
- **chrome-devtools MCP:** a stale automation Chrome can lock `~/.cache/chrome-devtools-mcp/chrome-profile`. Kill only that `--user-data-dir` process.
- **After code changes,** restart the dashboard: `launchctl kickstart -k gui/$(id -u)/com.kshitij.jobseeker.web`. Static assets are fingerprinted, so phones refresh automatically.
- **Groq daily quota** (200K tokens/model) gets exhausted by heavy manual testing. Scoring then stops cleanly and resumes.
- **The Gmail token expires about weekly** (Testing mode). Approve shows "Reconnect Gmail"; run `uv run jobseeker auth-gmail`.
- **API keys were pasted in chat on 2026-10-08.** The user chose not to rotate them; don't ask again.

## 6. IMPROVEMENT ROUND (2026-10-08), all pushed
Done, in the user's chosen order:
- **1. AI fallbacks:** `RouterLLM` + `FallbackLLM` in `llm.py`. Chains are in `Models.fallbacks`. Scoring: gpt-oss-20b → qwen/qwen3.8-27b → gemini:gemini-3.5-flash-lite → cloudflare:@cf/openai/gpt-oss-20b. Drafting: gpt-oss-120b → gemini:gemini-3.5-flash → cloudflare. The scoring JD is cut to 5,000 chars (drafting keeps 8,000). Cloudflare is live (token with the Workers AI template; uses @cf/openai/gpt-oss-120b, because its 20b ignores the JSON schema).
- **2. Backups:** `jobseeker backup` runs after each daily run and keeps 7 gzipped copies. They go to `BACKUP_DIR`, else iCloud Drive (off on this Mac), else `~/JobSeeker-backups`.
- **3.** "Add someone myself" prefills only a self-added contact.
- **4.** The header shows tappable plain-English run notes (`filters.explain_run`).
- **10/11.** Compact inbox cards with a next-step chip and a job count.
- **5.** Follow-up drafts to #1/#2 after 5 days (`nudge_due`, `application_contacts.nudged_at`, a template with no AI).
- **6.** The `/today` screen; the PWA `start_url` is now `/today`.
Not done (the user deferred it): the SaaS evaluation, after 2–3 weeks of use by the user and friends. Mark replied stays manual.
- **Mac power (2026-10-08):** the user ran `sudo pmset -a sleep 0`, so the Mac never idle-sleeps while the lid is open, and the dashboard is reachable whenever the lid is open. Closing the lid still sleeps it. The user declined Amphetamine and lid-closed hosting; don't re-propose them. Pages are gzipped and assets are cached as immutable (`deb1441`).


## 7. UI REDESIGN — MERGED into `main` (2026-10-08, fast-forward to `324722c`)
- **What:** the Stitch "Kinetic Horizon" look on Today, Jobs, Job detail and Pipeline. Spec: `docs/superpowers/specs/2026-10-08-ui-redesign-design.md`. Plan: `docs/superpowers/plans/2026-10-08-ui-redesign.md`.
- **Live:** on :8000 / `https://delulu.tail1c97dd.ts.net`. The preview (:8001/:8443), its launchd agent and the worktree are removed.
- **Tests:** 400 pytest + 19 node (`NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`).
- **Styles:** live only in `static/ui.css` (tokens on `:root`, dark mode, a phone section ≤640px, a tablet section 641–1240px). `app.css` and `mobile.css` are deleted. The phone tabs and pipeline chips use `static/tabs.js` (`[data-tabs]` / `[data-tab]` / `[data-panel]`).
- **Rollback:** the pre-redesign commit is `be39553`, and branch `ui-redesign` is kept on GitHub. To undo the whole redesign: `git revert --no-edit be39553..324722c`, then restart `com.kshitij.jobseeker.web`.
- **Deferred minors:**
  - With no `GROQ_API_KEY` at all, Find contacts and Regenerate return a 500 (the Groq client is built eagerly).
  - `nav_counts` runs the inbox query on every page render (fine at this size).

## 8. MULTI-USER: BUILT on `multi-user` (2026-10-09), not yet merged or deployed
The request (2026-10-08): share the app with 2 roommates as a real hosted app, with sign-in, onboarding and their own matches, and no dependency on the Mac. Decisions the user made: Oracle Always Free on PAYG with a ₹100 alert, DuckDNS + Caddy, Backblaze B2; invite-only Google sign-in, no invite emails; free only; roommates get matching only at launch, and outreach is switchable per user (`users.outreach_enabled`), with the owner keeping it. **Never merge to `main` without the user.** The PR description (changes, migrations, rollback, deferred minors) is `docs/superpowers/multi-user-PR.md`; the setup is in `README.md`.

**What was built** (each with a spec and plan in `docs/superpowers/`; the build log is `HANDOFF-backend.md` and `HANDOFF-devops.md`):
1. **Hosting** (`mu-hosting`): `bootstrap.sh` (idempotent Ubuntu 24.04 aarch64 setup), systemd units (`jobseeker-web`, `jobseeker-tick.timer` every 5 min, DuckDNS), Caddy, `ready.sh`, the `js` wrapper, and `scripts/deploy.sh` (refuses during a run, migrates, checks `/healthz`, rolls back on failure). The feasibility spike passed; port 25 is blocked on Oracle.
2. **Accounts and auth** (`mu-accounts-auth`, migration v1): users, invites, sessions, Google sign-in, `user_id` on every per-user table, route guards, an Origin-based CSRF check, and `/admin`.
3. **Onboarding and Settings** (`mu-onboarding-settings`, v2): preferences and facts move into the DB per user; 4-step onboarding plus resume reading; Settings with a two-way preview; export and delete account. Server-wide knobs live in `$JOBSEEKER_HOME/config/app.yaml`.
4. **Per-user pipeline** (`mu-per-user-pipeline`, v4): one shared fetch over the union of everyone's roles and cities, then filter, score and draft per user, with even per-user shares of the free quotas. Runs are driven by `tick`, with an IST clock and a run lock.
5. **Per-user outreach** (`mu-outreach`, v5): the per-user outreach switch, owner-scoped contacts with copy-on-write edits, a 30-day people-search cache, per-user Gmail via a web OAuth flow with tokens sealed under `TOKEN_KEY`, Reconnect Gmail, and `smtp_verify off|on|auto`.
6. **Extras** (`mu-extras`, v3): Fetch now, daily web push, nightly backups with an encrypted B2 copy, `jobseeker restore`, the admin usage view, and `gen-key`/`vapid-keys`.

Final state: 831 pytest and 26 node tests, also green under `TZ=UTC` and `TZ=America/New_York`. A fresh `.backup` copy of the live DB plus `profile/` migrates v0→v5 with every table's count unchanged (apps 242, scores 244, jobs 5487, contacts 16 split 15 shared / 1 private), an empty FK check, integrity ok, golden fields and facts equal, and a byte-identical scorer prompt.

**Cutover checklist** (hosting plan Task 5 + spec §2/§10; do it with the user, one step at a time, recording outcomes):
1. **Accounts** (spec §2; check each **(verify)** item against the provider's docs):
   - Oracle: home region Mumbai or Hyderabad (permanent; A1 only runs there), upgrade to PAYG, a ₹100/month budget alert. Confirm that idle reclaim doesn't apply to PAYG.
   - SSH key on the Mac: `ssh-keygen -t ed25519 -f ~/.ssh/jobseeker_oci` plus `Host jobseeker` in `~/.ssh/config`.
   - VM `VM.Standard.A1.Flex`, 2 OCPU / 12 GB, Ubuntu 24.04 aarch64, with a reserved public IP (confirm that it's free). Add ingress TCP 80/443 from `0.0.0.0/0` to the security list.
   - DuckDNS `<sub>` pointing at the IP (check the inactivity-expiry rule).
   - B2: a bucket, lifecycle rules, and a write-only key for that bucket.
   - UptimeRobot (`/healthz`) and Healthchecks.io.
2. **Google OAuth Web client** (one client for sign-in and Gmail):
   - Create an OAuth client of type **Web application** and enable the **Gmail API** in the same project.
   - Authorized redirect URIs: `https://<sub>.duckdns.org/auth/callback` and `https://<sub>.duckdns.org/gmail/callback`. Check that Google accepts `<sub>.duckdns.org` (it's on the public-suffix list). **Stop if it doesn't.**
   - The consent screen stays in **Testing**. Add **every outreach user's Gmail address as a test user**, the owner's included; otherwise Google answers "access blocked". The consent screen will say the app is unverified (Advanced → Continue).
   - Put the client ID and secret in the server `.env`.
3. **Bootstrap**, three passes (`ssh jobseeker 'sudo BASE_URL=https://<sub>.duckdns.org OWNER_EMAIL=<email> BRANCH=multi-user bash -s' < scripts/server/bootstrap.sh`): (a) add the printed deploy key in GitHub (read-only); (b) fill `/etc/duckdns.env` and `/srv/jobseeker/.env` (`js gen-key` for `SECRET_KEY`, `TOKEN_KEY` and `BACKUP_KEY`, each different; `js vapid-keys`; `BASE_URL` exactly the origin); (c) Caddy gets its certificate, and the services stay off with "missing: data/jobseeker.db, config/app.yaml". Check that `iptables -S INPUT` has 80/443 ACCEPT above the REJECT.
4. **Data move** (spec §10):
   1. Mac: `launchctl bootout gui/$(id -u)/com.kshitij.jobseeker` (stops scheduled runs).
   2. Mac: `sqlite3 data/jobseeker.db ".backup '/tmp/js-move.db'"`, `PRAGMA integrity_check` = ok, and record each table's count.
   3. `scp` the DB to the server, plus `profile/{resume.pdf,facts.json,preferences.yaml}`.
   4. Server: move the DB to `/srv/jobseeker/data/jobseeker.db` and the profile to `/srv/jobseeker/profile/` (owned by `jobseeker`); `js migrate --dry-run`, then `js migrate` (v1→v5; v2 imports the profile and writes `config/app.yaml`). Compare counts: each existing table matches.
   5. **`js refilter`, then `js refilter --apply` once** for the owner. Rule changes since the old verdicts hide about 5 jobs and bring back about 5, and skip 1 app (undoably). `evaluate` only re-judges new or changed jobs, so it won't fix these.
   6. Delete `/srv/jobseeker/profile/` and the `/tmp` copies; re-run `bootstrap.sh` (it enables the web service and timer).
5. **Owner checks on the phone:** sign in; Today, Jobs, a Job detail and Pipeline match the Mac; the first POST (save a setting) succeeds, not a 403 (proves `BASE_URL`). **Settings → Account → Connect Gmail once** (the Mac's `secrets/token.json` is not migrated). Run `js tick` once by hand; it exits 0.
6. **smtp_verify:** keep `contacts.smtp_verify: off` in the server's `config/app.yaml` (port 25 is blocked; `auto` probes it daily). If the Mac ever runs this code, set it to `on` there.
7. **Mac off:** `launchctl bootout gui/$(id -u)/com.kshitij.jobseeker.web` and `tailscale serve reset`. Keep the Mac's `data/jobseeker.db` untouched for 2 weeks as the rollback.
8. **Acceptance** (hosting spec §Acceptance 1–12): `/healthz` 200 over HTTPS, `http` redirects, `nc -z <ip> 8000` fails; a second bootstrap prints "No changes."; all four units are active after `sudo reboot`; the next 11:15 IST run and its Healthchecks ping happen; a trivial deploy works, a broken one (`--branch spike/broken`) rolls back, and one during a run is refused; the restore drill from a B2 `.enc` passes; `.env` is 600 and owned by `jobseeker`; Oracle billing shows ₹0 after a week.
9. **Invite the roommates:** `/admin` → Invites → their Google address, then send them the link yourself. Outreach stays off for them unless the owner turns it on (first add them as Google test users).
10. Record in this file: the live subdomain, region, the B2 bucket name (no keys) and any deviations.

**Rollback:** before step 7 of the data move, the Mac is untouched: `scripts/install_launchd.sh` brings it back. After cutover, the Mac DB copy (kept 2 weeks) plus `main` is the fallback; the nightly backups are on the server and in B2.
