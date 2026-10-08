# Proposal: sub-project 3, onboarding and Settings (draft, pre-spec)

**Date:** 2026-10-08 · **Branch:** `multi-user` · **Builds on:** `2026-10-08-multi-user-impact.md`, `2026-10-08-auth-scoping-proposal.md`.
**Rulings applied:** Gmail connect is not in v1 onboarding; it's an optional step that appears later, per user, once outreach is switched on. Each user's Groq usage is capped at an equal share of the global cap, with no pooling. No product code is changed here.

---

## (a) Per-user preferences in the DB; app settings stay in a server file

**Split the current `Preferences` model** (`src/jobseeker/config.py:115-137`) into:
- **`UserPrefs`** (per-user, editable):
  - `target_roles`, `cities`, `remote_india_ok`;
  - `experience_years` (new), `drop_if_min_years_at_least`, `max_age_days`;
  - `current_ctc_lpa` and `target_base_lpa`, both made **optional** (the scorer prompt at `src/jobseeker/scoring/scorer.py:36` must print "not given");
  - `must_haves`, `deal_breakers`, `title_allow`, `title_deny`, `experience_summary`;
  - `linkedin` and `github` (optional; only the outreach signature uses them).

  `name` and `email` come from `users`, filled by Google sign-in. They are not preferences.
- **`AppConfig`** (server file `config/app.yaml`, read at startup, admin-edited, restart to apply):
  - `models` and fallbacks (`config.py:83-92`);
  - the JobSpy knobs (`hours_old`, `results_per_search`, `sites`, `linkedin_descriptions_per_run`);
  - `thresholds` and `min_prescore` (one rubric for everyone keeps scores comparable);
  - global budgets (Groq per model, Tavily, Apify, Hunter, SMTP) and per-run caps;
  - a **role catalog** (below).

  Per-user budget shares are derived as global ÷ active users. Nobody edits them.
- **`effective_prefs(user_prefs, app_config, user) -> Preferences`**: an adapter that builds today's `Preferences` object. Because of it, `prefilter`, `prescore`, `score_job` and `draft_outreach` keep their signatures, which keeps the change small.

**Storage: a JSON blob, validated by `UserPrefs`** (recommended over typed columns):
```
user_prefs(user_id PRIMARY KEY REFERENCES users, data TEXT NOT NULL, version INTEGER NOT NULL,
           onboarding_step TEXT, onboarded_at TEXT, updated_at TEXT NOT NULL)
```
Why a blob:
- Most fields are lists. Typed columns would mean 6 child tables.
- No SQL ever filters on a preference; prefilter runs in Python.
- The Pydantic model is already the validation layer.

`version` lets a later field change be upgraded in code when the row is loaded.

**Role catalog.** Roommates won't understand `title_allow` or `search.queries`. So `AppConfig.roles` maps each friendly role to the search query and the title keywords it implies:
```yaml
roles:
  - {label: "Product Analyst", query: "Product Analyst", allow: [product, analyst, analytics]}
  - {label: "Associate PM / PM", query: "Product Manager", allow: [product]}
  - {label: "Founder's Office", query: "Founder's Office", allow: [founder, chief of staff, strategy]}
  # Growth, Data/BI Analyst, Business Analyst, Strategy & Ops ...
```
- The user's `title_allow` defaults to the union of their roles' `allow` keywords.
- The fetch step's search queries become the union over all users' roles (audit §5).
- `title_deny` starts from an app default list (sales, sde, intern, director, ...) and can be edited under "Exclusions".
- A free-text "other role" is allowed: it is added to `target_roles` (for the scorer) and `title_allow`, and the admin can see it to add it to the catalog.

## (b) Onboarding: 4 steps plus "done"

Routes are `/onboarding/{step}`, using `base.html` with no nav. They are reachable only while `onboarded_at IS NULL`. Each step is one card, laid out as follows:
- a step indicator ("Step 2 of 4", reusing the step-indicator styles from the application page);
- one primary button, which on phone (≤640px) sits in the sticky bottom bar, like Approve;
- "Back" as a secondary link.

Forms are plain POSTs under `hx-boost`. A validation error re-renders the same step with status 422 and messages next to the fields. Chips come from `ui.css` tokens (`--accent-wash` when selected).

| Step | Screen holds | Validation |
|---|---|---|
| 1. Roles | catalog chips (multi-select) plus an "Other role" text field | at least 1 role; other ≤ 60 chars, at most 3 others |
| 2. Where | city chips (Bengaluru, Gurgaon, Noida, Pune, Mumbai, Hyderabad, Chennai, Delhi plus "Other city"); "Remote within India is fine" toggle | at least 1 city or remote on |
| 3. Experience, pay, exclusions | years of experience (number); "Hide jobs asking for at least __ years" (defaults to years + 1, rounded to 0.5); current CTC and target base in LPA (optional); must-haves and deal-breakers (chips plus text); title exclusions (pre-filled with the default deny list, removable) | years 0-30; hide threshold above years; CTC 0-500; at most 10 items per list, 60 chars each |
| 4. Resume | upload (PDF ≤ 5 MB) → "Reading your resume…" card polled every 3 s (`hx-trigger="every 3s"`, like the People card) → review: headline, roles, skills (editable chips), achievements (editable textareas, delete), and an `experience_summary` textarea pre-drafted from the facts | constraints in (c); review: at least 1 skill, each achievement non-empty |
| Done | "You're set." Matching starts in the background; the card polls and shows "N jobs match so far" | — |

- **Save and continue:** every POST merges the step's fields into `user_prefs.data` (each step validates with its own partial model), sets `onboarding_step` to the next step, and redirects there.
- **Quitting halfway:** nothing is lost. A `require_onboarded` dependency on the app routers redirects any user with `onboarded_at IS NULL` to `/onboarding/{onboarding_step}`. Onboarding routes, `/logout` and `/settings/delete` are exempt, so a user can always leave. Add `require_onboarded` to the guard test (auth proposal §d).
- **Finishing:** "Finish" validates the **full** `UserPrefs` (a step skipped through a hand-typed URL fails here and sends the user back to it), sets `onboarded_at`, and starts the first evaluation as a background task. That task:
  - runs the per-user `evaluate` (audit §5: prefilter + prescore over every live job; no LLM, takes seconds);
  - then scores the top candidates within the user's daily Groq share (`score_per_run` from `AppConfig`, capped by the share).

  The Done card's poll reads that user's `runs` row, so "first matches in a few minutes" is accurate.
- **Gmail later:** Settings shows a "Connect Gmail" card only when `users.outreach_enabled` is set (new flag, admin-toggled). That flow belongs to sub-project 5.

## (c) Resume storage and per-user facts

- **Layout:** `JOBSEEKER_HOME/data/users/<user_id>/resume.pdf`. The directory is mode 700 and the file 600. The filename is never taken from the upload. Only the current resume is kept; a replacement writes `resume.pdf.tmp`, checks it, and renames it over the old file.
- **Upload limits:**
  - ≤ 5 MB (also `request_body max_size 6MB` at Caddy);
  - `Content-Type: application/pdf` **and** the file starts with `%PDF-`;
  - opens with PyMuPDF (`src/jobseeker/profile/resume.py:6-8`);
  - ≤ 10 pages;
  - extracted text ≥ 300 characters, otherwise: "This looks like a scanned PDF. Export a text PDF from Word or Docs."

  The upload is read with FastAPI's `UploadFile`; `python-multipart` is already a dependency.
- **Facts move into the DB:**
  ```
  user_facts(user_id PRIMARY KEY REFERENCES users, resume_sha256 TEXT, facts TEXT, edited INTEGER NOT NULL DEFAULT 0,
             extract_status TEXT NOT NULL DEFAULT 'idle', extract_error TEXT NOT NULL DEFAULT '',
             extract_started_at TEXT, updated_at TEXT NOT NULL)
  ```
- **Splitting `load_or_build_facts`** (`src/jobseeker/profile/facts.py:50-63`):
  - `extract_facts(llm, text, model) -> Facts` is pure, and keeps `FACTS_SYSTEM` and the "copy metrics verbatim" rules.
  - `db/profile.py` gets `get_facts(conn, user_id)`, `save_facts(conn, user_id, sha, facts, edited)`, and `claim_extract`/`set_extract_status`. The claim uses the same stale-claim pattern as `claim_find` (`src/jobseeker/db/contacts_repo.py:23-29`).

  Extraction is a background task with its own connection, like `run_find` (`src/jobseeker/contacts/finder.py:233`). If the sha256 matches the stored one, there's no LLM call (today's cache behaviour). `load_facts` callers (`src/jobseeker/web/application.py:45, 115`, `src/jobseeker/cli.py:46`) switch to `get_facts(conn, user.id)`.
- **Groq budget:** extraction uses `models.facts` (gpt-oss-120b, the drafting model's daily quota). It counts against the user's share as `usage(service='groq:facts', period=day)`, with a hard cap of **3 extractions per user per day** to stop upload loops. Over the cap: "You can re-read your resume again tomorrow; your current facts stay." If the global quota is gone, the status is `failed` with "AI limit reached for today", and the review screen offers **"Enter my skills myself"**, so onboarding is never blocked by a quota.
- **Edits win until the resume changes.** Saving the review sets `edited=1`. Uploading a different PDF (new sha) re-extracts and shows the review again with a note: "Your earlier edits were replaced by the new resume."

## (d) The Settings page (`/settings`)

There is a new nav item: in the sidebar below Pipeline, and on phone as a 4th tab with a gear icon (`_icons.html`). Sections are cards, top to bottom:

1. **Profile:** name and email from Google (read-only); LinkedIn and GitHub (optional).
2. **What I'm looking for:** the same partial templates as onboarding steps 1-3 (`_prefs_roles.html`, `_prefs_where.html`, `_prefs_experience.html`), posted to `/settings/prefs/{section}`.
3. **Resume and facts:** the current file name, upload date, a "Replace" button, and the facts review form from step 4.
4. **Account:**
   - Gmail ("Connect Gmail", only if `outreach_enabled`);
   - "Sign out" and "Sign out everywhere" (auth proposal §c);
   - "Download my data";
   - "Delete my account".

**Saving preferences triggers re-evaluation.** Generalize `src/jobseeker/pipeline/refilter.py` into `reevaluate(conn, user_id, prefs, facts, now, apply)`:
- It recomputes `prefilter` + `prescore` for every live job and writes `user_jobs` **in both directions**. Today's refilter only ever hides jobs; per-user verdicts mean a loosened preference must bring jobs back. Age is still not re-judged.
- Applications on newly hidden jobs follow the existing rule, `BEFORE_OUTREACH → skipped` (undoable, `refilter.py:11, 35-36`). Later statuses keep their status.
- Before saving, an HTMX preview reuses `apply=False`: "This hides 120 jobs, brings back 14, and skips 3 drafted applications. Save?" That's the existing CLI dry-run, as a confirm card.
- Filter fields (roles, cities, remote, years, exclusions) re-evaluate synchronously in a threadpool. It's pure Python over about 4.5k rows; check that it stays under 2 s in tests with 5k rows.
- **Scoring fields** (`experience_summary`, CTC, must-haves, deal-breakers) don't refilter. They make existing scores stale. Add `scores.prefs_hash` (the hash of the scoring-relevant fields), and `jobs_needing_score` (`src/jobseeker/db/jobs.py:126-138`) treats a different hash like a changed `jd_hash`. The per-run cap then refreshes the best jobs first. The message says: "Scores refresh over the next runs."
- The same `reevaluate` replaces `jobseeker refilter` (`cli.py:82-99`), which becomes `--user <email>`.

**Download my data:** `GET /settings/export` streams `jobseeker-<email>-<date>.zip` containing:
- `profile.json` (user, prefs, facts) and `resume.pdf`;
- `applications.json` (each with its job's title, company and URL, latest score, drafts, events, linked people and their emails);
- `job_verdicts.csv` (job id, title, company, filter reason, prescore).

It's built in memory, since the data is small. Shared data unrelated to the user's applications is left out.

**Delete my account:** `POST /settings/delete`, after a confirm card that asks the user to type their email. It explains that shared job listings stay, and that nightly backups keep copies for up to 7 days.
1. One transaction deletes: drafts, events, application_contacts and contact_candidates of the user's applications; then applications, scores, user_jobs, blocklist, usage, runs (`user_id`), user_prefs, user_facts, sessions and their `invites` row (they need a new invite to come back); then `users`.
2. After the commit: `rm -r data/users/<id>`.

Shared `contacts` and `company_domains` rows found for them stay, as the shared cache (Q1 ruling). The last admin can't delete themselves (the button is disabled, with the reason shown).

## (e) Replacing `app.state.prefs`

- Remove `app.state.prefs` (`src/jobseeker/web/app.py:54`). Add a request-scoped dependency `current_prefs(user=Depends(current_user), conn=Depends(get_conn)) -> Preferences`. It does a primary-key read of `user_prefs`, parses the JSON, validates it, and returns `effective_prefs(...)`. That costs well under 1 ms and is cached per request by FastAPI. Edits are therefore visible on the very next request, with nothing to invalidate.
- `app.state.app_config` replaces it for global settings (models, fallbacks for `llm_factory` at `app.py:58`, budgets). It's loaded once from `config/app.yaml`; changing it requires a restart, as with `.env`.
- Every reader in the audit's §2 switches over:
  - `src/jobseeker/web/application.py:116, 191` and `src/jobseeker/web/contacts.py:33, 50` use `current_prefs`;
  - `src/jobseeker/web/templates/today.html:6` uses `user.name`.
- Background tasks (`run_find`, fact extraction, the first evaluation) take **`user_id`, never a prefs object**, and load fresh preferences in their own connection. A long-running task therefore can't act on stale preferences.
- **Migration v2** (on top of v1):
  - create `user_prefs` and `user_facts`;
  - import the owner from `profile/preferences.yaml` (per-user fields) and `profile/facts.json` (keeping `resume_sha256`, `edited=1`);
  - copy `profile/resume.pdf` to `data/users/1/resume.pdf`;
  - set `onboarded_at`, so the owner never sees onboarding;
  - write `config/app.yaml` from the global parts of the same YAML, and map the owner's `search.queries` onto catalog roles.

## (f) Tests

- **Model and adapter:** `UserPrefs` partial validation per step. `effective_prefs` produces a `Preferences` that gives the same `prefilter`/`prescore`/`score_job` prompt for the migrated owner as today's YAML. That's the golden test that the migration changes nothing for the owner. Optional CTC renders "not given".
- **Onboarding flow** (`tests/test_onboarding.py`, using `client_as(new_user)`):
  - each step's 422 errors;
  - save, then leave, then sign in again → resumes at the same step;
  - an un-onboarded user hitting `/`, `/today` or `/applications/1` → 303 to their step;
  - a hand-typed `/onboarding/done` with step 2 missing → sent back;
  - Finish → `onboarded_at` set and a background evaluation queued (task runner stubbed).
- **Resume:**
  - rejects non-PDF content-type, a wrong magic number, > 5 MB, > 10 pages, scanned/empty text;
  - stored at `data/users/<id>/resume.pdf` with mode 600;
  - same sha → no LLM call;
  - a 4th extraction in a day → refused with facts kept;
  - global quota gone → manual-entry path works;
  - edits persist until a new sha arrives.
- **Settings:**
  - the preview counts match `apply=True`;
  - loosening cities **un-hides** jobs;
  - tightening skips only `BEFORE_OUTREACH` applications, and Undo works;
  - a scoring-field edit changes `prefs_hash` so `jobs_needing_score` returns those jobs again;
  - user B's settings never change A's `user_jobs`.
- **Export/delete:**
  - the zip contains exactly the caller's applications (two-user `seeded_two`), with none of B's ids;
  - delete removes every per-user row (a test enumerates every table with `user_id` or an `applications` FK and asserts 0 rows for the deleted user, and B's rows untouched) plus the directory;
  - the last admin can't delete;
  - delete without the typed email is refused.
- **Guard test:** `/settings*` and `/onboarding*` are in the route walk. App routers must carry `require_onboarded`; onboarding routes must not.
- **Migration v2:** a v1 fixture DB plus the fixture YAML and facts → `user_prefs`, `user_facts`, the resume file and `config/app.yaml` produced; re-running is a no-op.

## Open points for the coordinator
1. The role catalog's initial list. I'd seed it from the owner's current `search.queries` plus Growth, Data/BI Analyst, Business Analyst, Strategy & Ops.
2. The 4th phone tab for Settings vs putting it under a profile avatar. A tab is simpler and consistent.
3. Whether `thresholds`/`min_prescore` should ever be per-user. Proposed: no, in v1.
