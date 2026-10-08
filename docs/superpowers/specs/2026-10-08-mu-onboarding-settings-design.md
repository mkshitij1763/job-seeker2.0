# job-seeker2.0 multi-user: onboarding and Settings (design)

**Date:** 2026-10-08
**Status:** The combined multi-user design was approved by the user on 2026-10-08. This is the written spec for sub-project 3, awaiting review.
**Depends on:** sub-project 2 (`2026-10-08-mu-accounts-auth-design.md`): users, sessions, `current_user`, the guard test, `user_jobs`, the migrate framework, and `Budget(conn, user_id, limits, now)`.
**Used by:**
- sub-project 4: `AppConfig`, `effective_prefs`, `evaluate`/`reevaluate`, the role catalog;
- sub-project 5: `users.outreach_enabled` UI hooks on Settings;
- sub-project 6: the "Daily match alerts" Settings card (`UserPrefs.notify_new_matches`), and export/delete coverage of its tables.

Research: `docs/superpowers/research/2026-10-08-onboarding-settings-proposal.md`.

## 1. Goal

A roommate who has just been invited signs in and is guided through **4 short steps** (roles, places, experience and pay, resume), and gets matches built for **their** requirements. Everyone can later change preferences, replace their resume, download their data or delete their account from a **Settings** tab. Preferences live in the database, per user. Server-wide settings live in a server file.

## 2. Non-goals

- Gmail connect. It isn't part of onboarding; it appears in Settings only when outreach is on for the user (sub-project 5).
- Push alerts (sub-project 6 adds a Settings card).
- The per-user daily run, Fetch now, and score staleness (`profile_hash`): sub-project 4. This spec saves the fields that feed them.
- Per-user thresholds or `min_prescore`: these stay global.
- Per-user time zones: the app uses `Asia/Kolkata` (sub-project 4).
- Editing the rubric or the companies list in the UI.

## 3. Decisions (brainstorming and coordinator rulings)

| Topic | Decision |
|---|---|
| Storage | `user_prefs.data`: a **JSON blob** validated by a Pydantic `UserPrefs` model, with a `version`. Not typed columns: most fields are lists, and no SQL filters on preferences. |
| Global settings | `config/app.yaml` under `JOBSEEKER_HOME`, read once at startup into `AppConfig`; a change needs a restart. |
| Compatibility | `effective_prefs(user_prefs, app_config, user) -> Preferences` rebuilds today's `Preferences` object, so `prefilter`, `prescore`, `score_job` and `draft_outreach` keep their signatures. |
| Role catalog | Seeded from the owner's `search.queries` (Product Analyst, Associate Product Manager, Product Manager, Founder's Office, Growth Analyst), plus **Business Analyst, Data Analyst, Program Manager, Strategy & Ops**. It lives in `config/app.yaml`, so the admin extends it without code. **One** free-text custom role per user. |
| Onboarding | 4 steps plus Done. Each step saves as it goes; quitting resumes at the same step. Gmail isn't included. |
| Resume | PDF only, ≤ 5 MB, ≤ 10 pages, must contain text. Stored at `data/users/<id>/resume.pdf`. Facts move into the DB. |
| Facts AI budget | `groq:facts`: 3 extractions per user per day, plus a global daily cap. A manual skills path when blocked. |
| Settings | A **4th tab** (sidebar and phone tab bar). Sections: Profile, What I'm looking for, Resume and facts, Account. |
| Re-filtering | Generalised and **two-way**: a loosened preference brings jobs back. A preview runs before saving. |
| Export and delete | A zip export of the user's own data. Delete needs the typed email, removes every per-user row, and keeps the shared caches. |

## 4. Design

### 4.1 `UserPrefs`, `AppConfig` and `effective_prefs` (`src/jobseeker/config.py`)

**`UserPrefs`** (version 1). Every field has a default, so a partially filled row validates during onboarding:

| Field | Type, default | Notes |
|---|---|---|
| `roles` | `list[str] = []` | catalog labels |
| `custom_role` | `str = ""` | ≤ 60 chars |
| `cities` | `list[str] = []` | |
| `remote_india_ok` | `bool = True` | |
| `experience_years` | `float \| None = None` | |
| `drop_if_min_years_at_least` | `float \| None = None` | |
| `max_age_days` | `int = 7` | |
| `current_ctc_lpa`, `target_base_lpa` | `float \| None = None` | **optional** |
| `must_haves`, `deal_breakers` | `list[str] = []` | |
| `title_deny` | `list[str] \| None = None` | `None` = the app default |
| `title_allow_extra` | `list[str] = []` | |
| `experience_summary` | `str = ""` | |
| `linkedin`, `github` | `str = ""` | |
| `notify_new_matches` | `bool = True` | read by sub-project 6's daily alert; toggled on its "Daily match alerts" Settings card |

- A separate `UserPrefs.complete()` validator, used at Finish and on Settings saves, requires:
  - ≥ 1 role or a custom role;
  - ≥ 1 city or `remote_india_ok`;
  - `drop_if_min_years_at_least`, which must be > `experience_years` when years is set;
  - a non-empty `experience_summary`.

  `experience_years` is required by the onboarding `experience` step, not by `complete()`. A migrated owner without it can therefore still save any Settings section.
- Lists hold at most 10 items, each at most 60 chars.

**`AppConfig`**, from `JOBSEEKER_HOME/config/app.yaml`:
- `models` (with fallbacks; moved from `Preferences.models`);
- `thresholds`, `min_prescore`;
- `search` (the JobSpy knobs: `hours_old`, `results_per_search`, `sites`, `linkedin_descriptions_per_run`; the cap fields are added by sub-project 4);
- `contacts` (the limits from `config.py:106-111`);
- `budgets`: `score_per_run`, `draft_per_run`, `facts_per_user_per_day: 3`, `facts_per_day: 10`; sub-project 4 adds the daily score and draft caps;
- `default_title_deny`: today's owner list;
- `cities`: the chip list;
- `roles`: the catalog, `[{label, query, allow: [keywords]}]`;
- `companies_path` and `rubric_path`, defaulting to the **code checkout's** `companies.yaml` and `rubric.yaml` (the repo root, found from the package location), not `JOBSEEKER_HOME`.

The last point fixes the server layout from the hosting spec, where `JOBSEEKER_HOME=/srv/jobseeker` and the checkout is `/srv/jobseeker/app`. On the Mac the two paths are the same. `Settings.companies_path` and `Settings.rubric_path` (`config.py:60-66`) are removed in favour of these. A missing `config/app.yaml` stops startup with "Run `jobseeker migrate` (with the owner's files in $JOBSEEKER_HOME/profile/), or copy config/app.example.yaml"; an example file ships in the repo.

**Catalog seed** (written to `app.yaml` by v2; editable later):
```yaml
roles:
  - {label: Product Analyst,           query: Product Analyst,           allow: [product, analyst, analytics]}
  - {label: Associate Product Manager, query: Associate Product Manager, allow: [product, apm]}
  - {label: Product Manager,           query: Product Manager,           allow: [product]}
  - {label: Founder's Office,          query: Founder's Office,          allow: [founder, chief of staff, strategy]}
  - {label: Growth Analyst,            query: Growth Analyst,            allow: [growth, analyst]}
  - {label: Business Analyst,          query: Business Analyst,          allow: [business analyst, analyst]}
  - {label: Data Analyst,              query: Data Analyst,              allow: [data analyst, analytics, insights, business intelligence]}
  - {label: Program Manager,           query: Program Manager,           allow: [program manager, programme manager]}
  - {label: Strategy & Ops,            query: Strategy and Operations,   allow: [strategy, operations]}
cities: [Bengaluru, Gurgaon, Noida, Pune, Mumbai, Hyderabad, Chennai, Delhi]
```

**`effective_prefs(up, cfg, user) -> Preferences`** fills today's model as follows:

| `Preferences` field | Comes from |
|---|---|
| `name`, `email` | `users` |
| `target_roles` | the roles' labels, plus the custom role |
| `title_allow` | the union of the roles' `allow`, plus `title_allow_extra`, plus the custom role's words |
| `title_deny` | `up.title_deny`, or else `cfg.default_title_deny` |
| `search.queries` | the roles' `query`, plus the custom role (sub-project 4 builds the cross-user union) |
| `models`, `thresholds`, `min_prescore`, `budgets`, `contacts` | `cfg` |
| everything else | 1:1 from `up` |

`Preferences.current_ctc_lpa` and `target_base_lpa` become `float | None`. The scorer prompt (`src/jobseeker/scoring/scorer.py:36`) prints "not given" for `None`.

### 4.2 Request-scoped preferences (replaces `app.state.prefs`)

- **Removed:** `app.state.prefs` (`src/jobseeker/web/app.py:54`).
- **Added:**
  - `app.state.app_config`, loaded once;
  - `current_prefs(user=Depends(current_user), conn=Depends(get_conn), request) -> Preferences`, which is a primary-key read of `user_prefs`, then `UserPrefs.model_validate_json`, then `effective_prefs`. It's cached per request by FastAPI's dependency cache, so an edit is visible on the very next request.
- **Readers that switch:**
  - `web/application.py:116, 191` and `web/contacts.py:33, 50` use `current_prefs`;
  - `llm_factory`'s fallbacks (`app.py:58`) use `app_config.models.fallbacks`;
  - `today.html:6` already reads `user.name` (sub-project 2).
- **Background tasks** (fact extraction here; `run_find` and the run in later sub-projects) receive **`user_id`, never a prefs object**, and load fresh preferences on their own connection.
- **CLI:** `_load` (`cli.py:14-16`) becomes `load_user_context(conn, user_id) -> (Preferences, Facts)`. Commands that act on one user take `--user EMAIL`, defaulting to the owner.

### 4.3 Onboarding (`src/jobseeker/web/onboarding.py`, templates `onboarding/*.html`)

- **`require_onboarded`:** a dependency added to every app router (inbox, pipeline/today, application, contacts, admin, settings). If `user_prefs.onboarded_at IS NULL` it redirects 303 to `/onboarding/<onboarding_step or 'roles'>`, or for HTMX returns 401 with `HX-Redirect`.
- **Exempt:** `/onboarding/*`, `/logout*`, `/settings/delete` and `/settings/export`. A user can always leave or take their data. The guard test (sub-project 2 §7) also asserts `require_onboarded` on every app route and its absence on `/onboarding/*`.
- **Layout:**
  - `base.html` with no nav; one card per step; a header "Step N of 4" using the application page's step-indicator styles;
  - one primary button, in the sticky bottom bar on phones (≤ 640px), like Approve; a "Back" secondary link;
  - forms are plain POSTs under `hx-boost`;
  - chips are checkbox inputs styled with the `ui.css` tokens (`--accent-wash` when checked).

| Step (route) | Fields | Step validation (422 re-render, messages next to the fields) |
|---|---|---|
| `roles` | catalog chips; "Other role" text (one) | ≥ 1 chip or the other role; other ≤ 60 chars |
| `where` | city chips from `cfg.cities`; "Other city" text; "Remote within India is fine" toggle | ≥ 1 city or remote on |
| `experience` | years of experience; "Hide jobs asking for at least __ years" (shown pre-filled with `ceil((years + 1) * 2) / 2` once years is entered); current CTC and target base (LPA, optional); must-haves and deal-breakers (chips plus text); title exclusions, pre-filled from `cfg.default_title_deny`, each removable | years 0-30; threshold > years; CTC 0-500; ≤ 10 items each |
| `resume` | upload → processing card → review (§4.4) | §4.4 |
| `done` | "You're set." plus progress | — |

- **Saving each step:** `POST /onboarding/<step>` validates that step's fields with a partial model and merges them into `user_prefs.data`. It sets `onboarding_step` to the next step and `updated_at`, then redirects 303 to the next step. `GET` of any step pre-fills from the saved data, so Back works with nothing lost.
- **Finish:** `POST /onboarding/finish` (the button on the resume review):
  - runs `UserPrefs.complete()`. If it fails, redirect to the first incomplete step with a message. This covers steps skipped through a hand-typed URL;
  - otherwise sets `onboarded_at`, then queues the **first evaluation** as a `BackgroundTask` with its own connection: `reevaluate(conn, user_id, apply=True)` (§4.6), which needs no LLM and takes seconds;
  - redirects to `/onboarding/done`.
- **The Done card:** polls `GET /onboarding/done/status` every 3 s (`hx-trigger="every 3s"`, as on the People card). It shows "Checking 4,497 jobs… / 212 match your filters", then "Your first scores arrive with the next run" (sub-project 4 adds a Fetch-now trigger here). It has a "Go to Jobs" button.

### 4.4 Resume and facts

- **Storage:** `JOBSEEKER_HOME/data/users/<user_id>/resume.pdf`. The directory is mode 700 and the file 600. The filename never comes from the upload.
- **Upload** (`POST /onboarding/resume` and `POST /settings/resume`), read with `UploadFile` (`python-multipart` is already a dependency). Checks, in order:
  1. the request body is ≤ 5 MB (streamed with a counter; also capped at Caddy);
  2. `Content-Type: application/pdf`;
  3. the first bytes are `%PDF-`;
  4. it opens with PyMuPDF (`src/jobseeker/profile/resume.py:6-8`);
  5. ≤ 10 pages;
  6. extracted text ≥ 300 characters.

  Each failure returns a 422 with the message from §6. The upload is written to `resume.pdf.tmp`, checked, then renamed over `resume.pdf`.
- **`user_facts` table** (§5). `src/jobseeker/profile/facts.py` is split:
  - `extract_facts(llm, text: str, model) -> Facts`: pure; keeps `FACTS_SYSTEM`;
  - in `db/profile.py`: `get_facts(conn, user_id) -> Facts | None`, `save_facts(conn, user_id, sha, facts, edited)`, `claim_extract(conn, user_id, now) -> bool` (with the same 20-minute stale-claim rule as `claim_find`, `src/jobseeker/db/contacts_repo.py:23-29`), and `set_extract_status`.

  `load_or_build_facts` and `load_facts` (`facts.py:45-63`) are removed. Their callers (`web/application.py:45, 115`, `cli.py:31-32, 46`) use `get_facts(conn, user.id)`.
- **Extraction:**
  - after a successful upload, if `sha256` equals `user_facts.resume_sha256`, nothing runs (the cache);
  - otherwise `claim_extract`, then a `BackgroundTask` `run_extract(db_path, user_id)`: check the budget, `extract_facts` through `FallbackLLM(build_llm(settings), cfg.models.fallbacks)` with `cfg.models.facts`, `save_facts(edited=0)`, status `done`;
  - the resume step and the Settings card poll `GET /…/resume/status` every 3 s: "Reading your resume…" → the review form.
- **Budget:** `Budget(conn, user_id, {"groq:facts": Limit(period="day", global_cap=cfg.budgets.facts_per_day, share_cap=cfg.budgets.facts_per_user_per_day)}, now)`. The day is the IST date. The check and `spend` happen before the LLM call. If refused, the status is `failed` with "You can re-read your resume again tomorrow; your current facts stay." If the provider quota is gone (`LLMQuotaExceeded`/`LLMUnavailable`), the status is `failed` with "AI limit reached for today."

  When there are no facts yet and extraction failed, the review shows **"Enter my skills myself"**: a form for headline, skills, and up to 6 achievements, saved with `edited=1` and `resume_sha256` set. Onboarding is never blocked by a quota.
- **Review form:** headline; roles (title, org, start, end; editable, removable); skills (chips, ≥ 1); achievements (textareas, removable; metrics are re-derived by regex from the text); and `experience_summary`, pre-drafted the first time from the roles and dates in plain text, with no LLM. Saving sets `edited=1`.
- **A new resume** (different sha) re-extracts and shows the review again with "Your earlier edits were replaced by the new resume."

### 4.5 Settings (`/settings`, `src/jobseeker/web/settings.py`)

**Nav:** a 4th item, "Settings", with a gear icon added to `_icons.html`. It goes in the sidebar after Pipeline and in the phone tab bar as the 4th tab (`base.html:22-23` items list). It carries no count.

The sections are cards, top to bottom:
1. **Profile:** name and email (read-only, from Google); LinkedIn and GitHub (`POST /settings/profile`).
2. **What I'm looking for:** the same partial templates as onboarding (`_prefs_roles.html`, `_prefs_where.html`, `_prefs_experience.html`), each posting to `/settings/prefs/<section>`. A save of a **filter-affecting section** (roles, where, or the experience threshold and exclusions) first returns a preview card (§4.6), "This hides 120 jobs, brings back 14 and skips 3 drafted applications", with **Save** and **Cancel**. Save applies it. Scoring-only fields (summary, CTC, must-haves, deal-breakers) save directly, with "Scores refresh over the next runs" (sub-project 4).
3. **Resume and facts:** file name, upload date, Replace (§4.4), and the facts review form.
4. **Account:** "Download my data", "Sign out", "Sign out everywhere", "Delete my account". Sub-project 5 adds the Gmail card, and sub-project 6 adds the "Daily match alerts" card.

### 4.6 Re-evaluation, two-way (`src/jobseeker/pipeline/evaluate.py`)

`reevaluate(conn, user_id, prefs, facts, now, apply: bool) -> Report` generalises `src/jobseeker/pipeline/refilter.py:14-37`:
- For every **live** job (not older than `max_age_days` since `posted_at` or `first_seen_at`):
  - compute `prefilter(job, prefs, now, blocked_companies(conn, user_id))` and `prescore(job, facts, prefs)`;
  - compare with the user's `user_jobs` row (missing = new);
  - `stale:` reasons from age are ignored, as today.
- **Report:** `hidden` (was unfiltered, now filtered), `restored` (was filtered, now passes), `new` (no row), `skipped_apps` (applications on newly hidden jobs in `new`, `shortlisted` or `drafted`, the `BEFORE_OUTREACH` set from `refilter.py:11`), and `kept_apps` (later statuses).
- **With `apply=True`:** upsert `user_jobs(filter_reason, prescore, jd_hash, evaluated_at)` and transition the `skipped_apps` to `skipped` with `{"reason": "settings: <reason>"}`, which stays undoable. Restored jobs simply become eligible again. Applications that were skipped earlier are **not** un-skipped automatically; the user can Undo them.
- **Performance:** it runs in a threadpool for Settings. The test with 5,000 jobs must finish in < 2 s.
- `jobseeker refilter [--user EMAIL] [--apply]` becomes a thin wrapper around this (`src/jobseeker/cli.py:82-99`), and `refilter.py` is removed. Sub-project 4's per-run `evaluate` reuses the same per-job function.

### 4.7 Export and delete

- **`GET /settings/export`** streams `jobseeker-<email>-<YYYY-MM-DD>.zip` (built in memory, with a `Content-Disposition` attachment header). It contains:
  - `profile.json`: user (email, name, created), prefs, facts;
  - `resume.pdf`, if present;
  - `applications.json`: per application, the job's title, company, location and URL, the status, the latest score and recommendation, the drafts, the events, and linked people (name, role, LinkedIn, email, email status);
  - `job_verdicts.csv`: `job_id, title, company, filter_reason, prescore`.

  It contains no other user's data and no shared data beyond what's linked from the user's own applications.
- **`GET /settings/delete`:** a confirm card. "Type your email to confirm. Shared job listings stay. Backups keep copies for up to 4 weeks." For the last admin, the button is disabled with "You're the only admin".
- **`POST /settings/delete`** (email must match): one transaction deleting, in order:
  1. `drafts`, `events`, `application_contacts` and `contact_candidates` for the user's applications;
  2. `applications`, `scores`, `user_jobs`, `blocklist`, `usage`, `runs WHERE user_id`, `user_prefs`, `user_facts`, `sessions`, and the user's `invites` row (re-entry needs a new invite);
  3. `users`.

  After the commit: `rm -r data/users/<id>`. Then expire the cookie and redirect to `/login`.
- **Tables added later:** sub-projects 4-6 add tables with `user_id` (`run_requests`, `gmail_tokens`, `push_subscriptions`, contacts with `owner_user_id`). Each of those specs must add its table to this delete list and to the export, where it holds user data. The table-enumeration test (§7) enforces this.

### 4.8 Migration v2: preferences, facts and resume

`jobseeker migrate` reads the owner's files from **`DIR = $JOBSEEKER_HOME/profile/`** (there's no import flag). For the move, the hosting runbook copies the Mac's `profile/` there:
1. `CREATE TABLE user_prefs`, `user_facts` (§5).
2. Read `DIR/preferences.yaml` with today's `load_preferences`:
   - **Per-user fields** become user 1's `UserPrefs`. `roles` are mapped from `search.queries` to catalog labels by an exact `query` match. Unmatched queries become `title_allow_extra` words, and the first unmatched one becomes `custom_role`. `title_deny` and `experience_summary` are copied verbatim, and `experience_years` is parsed from the summary if a "~N years" pattern is found, otherwise left `None`. `onboarded_at = now`, so the owner never sees onboarding, with the gaps reported.
   - **Global fields** (`models`, `thresholds`, `min_prescore`, `budgets`, `search.*` knobs, `contacts`) plus the catalog seed (§4.1) are written to `JOBSEEKER_HOME/config/app.yaml`, **only if it doesn't exist**.
3. `DIR/facts.json` → `user_facts(1, resume_sha256, facts, edited=1)`.
4. Copy `DIR/resume.pdf` → `data/users/1/resume.pdf` (modes 700/600).
5. **Post-check (the golden check):** `effective_prefs(user 1)` equals the original `Preferences` on every field that `prefilter`, `prescore` and `score_job` read (title allow/deny, cities, remote, years threshold, max age, experience summary, target roles, CTC, must-haves, deal-breakers). A mismatch aborts the migration with a field-by-field diff.

If `DIR/preferences.yaml` doesn't exist, v2 still creates the tables, inserts `user_prefs(1)` with `onboarded_at NULL`, and writes `app.yaml` from defaults. The owner then onboards like anyone else.

## 5. Data model (added by v2)

```sql
user_prefs(user_id INTEGER PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, version INTEGER NOT NULL,
           onboarding_step TEXT, onboarded_at TEXT, updated_at TEXT NOT NULL)
user_facts(user_id INTEGER PRIMARY KEY REFERENCES users(id), resume_sha256 TEXT, facts TEXT,
           edited INTEGER NOT NULL DEFAULT 0, extract_status TEXT NOT NULL DEFAULT 'idle'
             CHECK (extract_status IN ('idle', 'running', 'done', 'failed')),
           extract_error TEXT NOT NULL DEFAULT '', extract_started_at TEXT, resume_uploaded_at TEXT,
           updated_at TEXT NOT NULL)
```

A new user gets a `user_prefs` row (`data='{}'`, `version=1`, `onboarding_step='roles'`) at their first sign-in. This spec extends sub-project 2's sign-in resolver (§4.3 there) to insert that row in the same transaction as the `users` row. Files: `JOBSEEKER_HOME/config/app.yaml` and `JOBSEEKER_HOME/data/users/<id>/resume.pdf`. `profile/preferences.yaml`, `facts.json` and `resume.pdf` are no longer read at runtime.

## 6. Errors

| Situation | Message or behaviour |
|---|---|
| Upload > 5 MB | "That file is over 5 MB. Export a smaller PDF." |
| Not a PDF (content type or magic bytes) | "Please upload your resume as a PDF." |
| PyMuPDF can't open it | "That PDF couldn't be read. Try exporting it again." |
| > 10 pages | "Resumes over 10 pages aren't supported." |
| < 300 characters of text | "This looks like a scanned PDF. Export a text PDF from Word or Google Docs." |
| Facts budget used (per user or global) | Extraction status `failed`: "You can re-read your resume again tomorrow; your current facts stay." Manual entry is offered when there are no facts |
| Provider quota or outage | `failed`: "AI limit reached for today." Manual entry is offered |
| Extraction stuck > 20 min | Shown as failed with "Try again" (stale claim) |
| Step validation | 422, the same step re-rendered with field messages, data kept |
| Finish with gaps | 303 to the first incomplete step with "Please finish this step" |
| Missing `config/app.yaml` | Startup refused with the `jobseeker migrate` / example-file hint |
| v2 golden check mismatch | Migration rolled back; a field-by-field diff is printed |
| Delete with the wrong email | 422 "The email doesn't match" |
| Last admin deletes | Refused (button disabled; the POST returns 403) |

## 7. Testing

- **Config:**
  - `UserPrefs` partial validation per step and `complete()` rules;
  - `effective_prefs` mapping (roles → `title_allow`/queries, `title_deny` default, optional CTC);
  - `AppConfig` loads the example file;
  - `companies_path`/`rubric_path` resolve to the checkout when `JOBSEEKER_HOME` is elsewhere.
- **Golden test for the owner:** using the fixture `preferences.yaml` and `facts.json` (copies of the real files' structure, with no personal values), migration v2 gives `effective_prefs` equal on every filter and score field. The `prefilter` reasons and `prescore` values for a fixed 50-job fixture are identical before and after. The scorer prompt string is identical.
- **Onboarding** (`client_as(new_user)`):
  - each step's 422 errors;
  - save, then sign out, then sign in again → lands on the same step with the data pre-filled;
  - an un-onboarded user on `/`, `/today`, `/applications/<id>` or `/settings` gets a 303 to their step, and an HTMX request gets a 401 with `HX-Redirect`;
  - `/onboarding/finish` with a step missing → sent back;
  - Finish sets `onboarded_at` and queues `reevaluate` (the task runner is stubbed);
  - the Done status endpoint reports counts;
  - the guard test covers `require_onboarded`.
- **Resume:**
  - each rejection in §6 (fixture PDFs: a 5.1 MB file, a PNG renamed to `.pdf`, a corrupt PDF, 11 pages, image-only);
  - stored path and modes 700/600; atomic replace;
  - same sha → no LLM call (a fake LLM that fails if called);
  - 4th extraction in a day → refused with facts kept;
  - global `facts_per_day` reached → refused for everyone;
  - quota error → manual entry saves `edited=1`;
  - a new sha replaces edits with the note.
- **Settings:**
  - the preview counts equal what `apply=True` changes;
  - loosening cities **restores** jobs; tightening skips only `BEFORE_OUTREACH` applications, and Undo restores them;
  - scoring-only edits don't call `reevaluate`;
  - user B's save never changes user A's `user_jobs`;
  - 5,000-job `reevaluate` in < 2 s;
  - Settings appears as the 4th tab on the phone layout (`test_web_mobile.py` pattern).
- **Export:** the zip has exactly the listed files; using `seeded_two`, the owner's export contains none of the roommate's application ids, job verdicts or drafts.
- **Delete:**
  - after deleting the roommate, a test walks `sqlite_master` and, for **every** table with a `user_id` or `owner_user_id` column or an `application_id` foreign key, asserts 0 rows for that user while the owner's rows are unchanged; `data/users/2` is gone;
  - the wrong email is refused; the last admin can't delete;
  - this test fails automatically when a later sub-project adds a user table without extending the delete.
- **Migration v2:**
  - the fixture import produces `user_prefs`, `user_facts`, the resume file and `app.yaml`;
  - an existing `app.yaml` isn't overwritten;
  - a re-run is a no-op;
  - with no `$JOBSEEKER_HOME/profile/preferences.yaml`, it creates an empty, un-onboarded `user_prefs(1)`.

## 8. Acceptance criteria

1. A new invited user completes onboarding on an iPhone-sized viewport in under 3 minutes. Leaving at step 3 and coming back resumes at step 3 with nothing lost.
2. After Finish, that user's Jobs list is built from their own preferences (verified on `seeded_two`: different roles give different `user_jobs` verdicts for the same jobs).
3. The owner's matching after v2 is unchanged (the golden test passes on a copy of the live data).
4. Settings: loosening a city brings jobs back; tightening shows a correct preview and skips only pre-outreach applications.
5. Resume rules hold; a scanned PDF gets the scanned-PDF message; fact extraction never exceeds 3 per user per day.
6. Export contains only the caller's data. Delete removes every per-user row and the resume, and the user can't sign in again without a new invite.
7. No code reads `profile/preferences.yaml`, `facts.json` or `profile/resume.pdf` at runtime (checked with grep in a test); `app.state.prefs` is gone.
8. All tests pass, with no network.
