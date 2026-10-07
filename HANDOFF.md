# HANDOFF — job-seeker2.0 (2026-10-08, `main` @ `846074c`)

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
1. **FIRST:** `cd "/Users/user/Desktop/untitled folder/job-seeker2.0" && FORCE_COLOR= uv run pytest --color=no`. Expect `369 passed`. Then open `src/jobseeker/contacts/finder.py`, the riskiest live code.
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


## 7. UI REDESIGN — branch `ui-redesign` (NOT merged; 2026-10-08)
- **What:** the Stitch "Kinetic Horizon" look on Today, Jobs, Job detail and Pipeline. Spec: `docs/superpowers/specs/2026-10-08-ui-redesign-design.md`. Plan: `docs/superpowers/plans/2026-10-08-ui-redesign.md`. No new backend features.
- **Where:**
  - worktree `/Users/user/Desktop/untitled folder/job-seeker2.0-ui` (branch `ui-redesign`); the main folder stays on `main`.
  - Preview: `https://delulu.tail1c97dd.ts.net:8443`, served by launchd `com.kshitij.jobseeker.uipreview` on :8001. It uses the **real** data, .env and Gmail (actions there are real).
  - Live `main` UI is unchanged on :8000.
- **Tests:** `cd ../job-seeker2.0-ui && FORCE_COLOR= uv run pytest --color=no` (399 passed) and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs` (19 passed).
- **Restart the preview after edits:** `launchctl kickstart -k gui/$(id -u)/com.kshitij.jobseeker.uipreview`.
- **To merge (only when the user finalises):**
  1. `cd "/Users/user/Desktop/untitled folder/job-seeker2.0" && git merge ui-redesign && git push`
  2. `launchctl kickstart -k gui/$(id -u)/com.kshitij.jobseeker.web`
  3. `../job-seeker2.0-ui/scripts/preview_ui.sh remove && git worktree remove ../job-seeker2.0-ui`
- **To abandon:**
  1. `../job-seeker2.0-ui/scripts/preview_ui.sh remove`
  2. `git worktree remove ../job-seeker2.0-ui`
  3. `git branch -D ui-redesign && git push origin --delete ui-redesign`
- **Branch-only fixes found in QA:** the doubled LinkedIn greeting ("Hi Anshu, Hi, …") is fixed in `filters.personal_note`, so `main` still has that bug until the merge.
