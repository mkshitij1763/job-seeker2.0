# HANDOFF — job-seeker2.0 (2026-10-08, `main` @ `9f9c416`)

> **START HERE (new session):** the user's current request is in **§8 MULTI-USER HOSTED APP**. Work in progress: brainstorming, which had **not started asking questions yet**. Read §8, then resume at its "Next action".

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

## 8. MULTI-USER HOSTED APP — NEW REQUEST (2026-10-08), brainstorming not yet started
**What the user asked (paraphrased faithfully):**
- Share the app with **2 roommates** without them setting up the project.
- They should feel it is **a real app**: a home screen, **proper authentication / login**, then **onboarding that asks for job preferences**. After that, jobs are **fetched and scored for their own requirements**.
- Host it **on a public server**, so there is **no dependency on the Mac** (it isn't always awake). Replace the Tailscale VPN way of reaching it from web and phone with something else.
- "Some more features" are fine, plus "a few more small additional features".
- Do all of this **in a separate branch**, strictly for feature development. The user said "from the ui branch"; `ui-redesign` is already merged into `main`, so **branch from `main`** (suggested name `multi-user`). **The branch has NOT been created yet.**
- The user wants **brainstorming first**: tell back what features to add, how the flow looks, what's on each screen, and the hosting solution. Then spec → plan → build (superpowers flow: brainstorming → writing-plans → executing-plans). The user prefers **Native (inline) execution** and autonomous rulings when away. **Never merge to `main` until the user says so.**

**Classification:** architectural, and too big for one spec. Decompose and give each sub-project its own spec → plan → build:
1. **Hosting + feasibility spike (do first, it decides the rest).** Run a fetch from a cloud VM and check, from a datacenter IP:
   - Do LinkedIn, Naukri and Indeed (JobSpy) still return jobs? Datacenter IPs are often blocked. The ATS APIs (Greenhouse, Lever, Ashby) should be fine.
   - Is outbound SMTP port 25 open? It is blocked on Oracle, GCP and most clouds, and that kills `smtp_verify`; the fallback is Apify/Hunter or pattern guesses.
2. **Accounts + auth:**
   - a `users` table, sign-in with Google, sessions
   - an invite-only allow-list of emails (the site is public)
   - every per-user table scoped by `user_id`
3. **Onboarding + Settings:**
   - preferences move from `profile/preferences.yaml` into the DB, per user
   - resume upload, then the existing `load_or_build_facts`, then review/edit of the extracted facts
4. **Per-user pipeline:**
   - fetch once, on the union of all users' roles × cities, into the shared `jobs` table
   - prefilter, score and draft **per user** (`scores` and `applications` get `user_id`)
   - per-user budgets, because the free Groq/Tavily/Apify/Hunter quotas are shared by 3 people
5. **Per-user Gmail:**
   - each user's own OAuth token
   - the Google app stays in **Testing mode** with the roommates added as test users, so no Google verification or CASA audit is needed (`gmail.compose` is a restricted scope)
   - consent still expires about weekly, so add a one-tap "Reconnect Gmail"
6. **Extras (keep small):**
   - an in-app Settings page
   - "Fetch now"
   - daily web-push "N new matches" (iOS 16.4+ PWA)
   - an admin view for the user (invites, usage per person)
   - export or delete my data

**Hosting options to present (the user has been "free only" so far; ask them):**
- **Oracle Cloud Always Free ARM VM:** free forever and plenty of power. Signup needs a card, and the Mumbai region often has no capacity. Runs Docker or plain uv, Caddy for HTTPS, SQLite on disk, launchd replaced by systemd timers.
- **Hetzner CX22, about €4.5/month:** reliable and cheap. Not free.
- **GCP e2-micro free tier:** US regions only, 1 GB RAM, tight.
- **Avoid:** Render/Railway free tiers (they sleep and have ephemeral disks, so SQLite would be lost).
- **Public access without VPN:** HTTPS on a domain. Either a free DuckDNS subdomain plus Caddy, or a Cloudflare Tunnel with a cheap domain. The PWA "Add to Home Screen" keeps the app feel on phones.
- **Data:** move the DB to the server and run nightly backups to object storage; this replaces `~/JobSeeker-backups`. Secrets live in a server `.env`, never in git.
- **Honest risk to tell the user:** job-site scraping may get worse from a datacenter IP. Mitigation if the spike shows it's blocked: keep ATS boards plus Indeed, or keep a small optional fetcher on the Mac that pushes jobs up (this brings back some Mac dependency, so it's a last resort).

**Screens to propose:**
- **Public landing:** what it is, plus "Continue with Google".
- **Onboarding (5 steps):** roles → cities and remote → experience, salary and exclusions → resume upload and review of the extracted facts → connect Gmail → "You're set; first matches in about N minutes" (this triggers a first run for that user).
- **The app:** the existing Today, Jobs, Job detail and Pipeline, plus Settings (preferences, resume, Gmail status, sign out, delete data).
- **Admin (owner only):** invites, users, usage and budgets.

**Next action:**
1. Create the branch: `git switch -c multi-user && git push -u origin multi-user`.
2. Re-invoke `superpowers:brainstorming`. Classify it as architectural and decomposed; present the decomposition above and the write-back of what the user wants.
3. Ask **one question at a time**, starting with: *hosting budget, strictly free (Oracle Always Free) or about ₹400/month (Hetzner)?* Then: invite-only Google sign-in OK? Gmail drafts for roommates too, or just job matching for them?
4. Propose running the hosting/scraping **spike** before writing specs.


**Sub-project 2 built (accounts + auth), on `multi-user`, 2026-10-09:**
- New env vars in `.env`. The web app refuses to start without the first four:
  - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (a Web OAuth client, redirect `<BASE_URL>/auth/callback`)
  - `BASE_URL` (the exact browser origin, e.g. `https://<name>.duckdns.org`; the CSRF check 403s any POST from another origin)
  - `SECRET_KEY` (32+ random chars; signs the short-lived OAuth cookie)
  - `OWNER_EMAIL` (the owner's Google email; claims user 1 and admin)
  - `COOKIE_SECURE` (default true; the `__Host-` cookies need HTTPS)
- `jobseeker migrate` upgrades the DB to v1 (users, invites, sessions, user_jobs, `user_id` on per-user tables). Stop the web service and the run timer first. `--dry-run` previews. Both the web app and the pipeline refuse an un-migrated DB with `SchemaOutOfDate`.
- The live Mac app stays on `main` until cutover. Never run `migrate` against the live `data/` from `multi-user`.
- Tests: 472 pytest, 19 node. Acceptance on a `.backup` copy of the live DB: migrate leaves counts unchanged (apps 167, scores 168, jobs 4497, user_jobs 4497), foreign_key_check is empty, and the un-migrated copy refuses to start. Real Google sign-in is checked at deploy.
