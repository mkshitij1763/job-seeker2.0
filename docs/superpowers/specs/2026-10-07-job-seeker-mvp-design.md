# job-seeker2.0 — MVP Design

**Date:** 2026-10-07
**Status:** Approved in brainstorming (sections 1–4 by user; section 5 and this document self-reviewed at user's request)
**Scope:** Sub-project A (discovery → scoring → tracker → dashboard) plus the drafting slice of sub-project B (outreach drafts + Gmail drafts, manual contacts).

---

## 1. Goal

A local, single-user tool that every morning gives Kshitij a short list of high-fit (score ≥ 70) new job openings, each with a suggested contact and ready-to-review outreach drafts (cold email + LinkedIn note/DM). Approving one application takes under 2 minutes. Every application's status is visible at a glance.

**The north-star metric is interviews, not emails sent.** The tool favours fewer, better-targeted applications over volume.

**Hard rule: the app never sends anything.** "Approve" creates a Gmail *draft*; the user presses Send in Gmail. LinkedIn messages are copied to the clipboard for manual sending.

### Success criteria
1. A daily run (scheduled at 07:30 local) produces new jobs scored ≥ 70 with drafts ready before the user opens the dashboard.
2. Reviewing and approving one application — read job, check contact, edit draft, approve — takes < 2 minutes.
3. The pipeline view shows the status of every application and flags ones needing a follow-up.

## 2. Candidate profile

Stored in `profile/preferences.yaml` (user-editable). Initial values:

| Field | Value |
|---|---|
| Target roles | Senior Product Analyst, Product Analyst, APM, PM, AI PM; open to Founder's Office and analytics roles |
| Experience | ~1.3 years full-time (Product Analyst, Inito, since Jul 2025) + 3-month PwC internship |
| Locations | Bengaluru, Gurgaon, Noida, Pune; remote-within-India acceptable |
| Current CTC | 20.7 LPA |
| Target base | ~25 LPA |
| Must-haves / deal-breakers | None stated (fields exist, empty) |
| Resume | `profile/resume.pdf` — source of truth for skills and achievements |
| LinkedIn | https://www.linkedin.com/in/kshitijmeshram1763/ |
| GitHub | https://github.com/mkshitij1763 |

**Pre-requisite (user action, outside the app):** the resume PDF header has wrong display text for LinkedIn/GitHub and a broken `mailto:` link. Fix in the Overleaf source (`heading.tex`), recompile, and save as `profile/resume.pdf`. Until then the current `winter_arc.pdf` is used.

## 3. Out of scope for MVP (planned later phases)

- **Phase 2 sources:** JobSpy and Apify adapters (LinkedIn, Naukri, Instahyre, Indeed, Glassdoor), with per-source rate limits.
- Contact discovery via Hunter/Apollo and email verification.
- LinkedIn assist mode and "we're hiring" post monitoring.
- Reply detection (Gmail read scope), automated follow-up drafting.
- Tailored resume per JD, cover letters.
- Analytics beyond the basic stat strip.
- Workday and other non-public ATSs (Darwinbox, Keka, Zoho Recruit).

## 4. Architecture

Python 3.13, managed with `uv`. One package, `jobseeker`, of small single-purpose modules:

```
jobseeker/
  config.py        load preferences.yaml, companies.yaml, rubric.yaml, .env (pydantic-settings)
  profile/         resume.pdf → text (PyMuPDF) → facts.json via Claude (cached by resume hash)
  sources/
    base.py        Source protocol: name, fetch(since) -> list[RawJob]
    greenhouse.py  boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    lever.py       api.lever.co/v0/postings/{slug}?mode=json
    ashby.py       api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
    jsearch.py     RapidAPI JSearch: query per (role × city), country=in, date_posted=3days
  pipeline/
    normalize.py   RawJob → Job (common schema), city/title canonicalisation
    dedup.py       exact (source, source_job_id) + cross-source fingerprint
    prefilter.py   rule-based drops (no LLM)
  scoring/         Claude structured-output scorer + rubric.yaml
  outreach/        contact suggestion, email, LinkedIn note, LinkedIn DM; fact & style guards
  gmail/           OAuth (gmail.compose) + create draft with resume attachment
  db/              SQLite schema, migrations, repository functions
  web/             FastAPI app, Jinja2 templates, HTMX partials, static CSS
  cli.py           `jobseeker run | serve | auth-gmail | rescore | init`
```

Each source adapter is independent: adding JobSpy/Apify in phase 2 means adding one file implementing `Source`, plus an entry in config.

### Data flow (`jobseeker run`)

```
sources (in parallel, each isolated) → normalize → dedup (vs DB) → prefilter
  → score (Claude, only new or changed JD/rubric) → for score ≥ 70: draft outreach (Claude)
  → persist to SQLite → write run summary (counts per stage, errors)
```

`jobseeker serve` starts the dashboard at `http://127.0.0.1:8000` (bound to localhost only).

## 5. Data model (SQLite)

```
jobs          id, source, source_job_id, company, title, location_city, remote (bool),
              posted_at, salary_text, jd_text, apply_url, fingerprint, first_seen_at,
              filter_reason (nullable; set when dropped by the prefilter),
              UNIQUE(source, source_job_id)
scores        job_id, score, breakdown (json), matches (json), gaps (json),
              recommendation, model, rubric_version, jd_hash, created_at
contacts      id, company, name, role, linkedin_url, email,
              email_status (unverified | verified | bounced), source, notes
applications  id, job_id, contact_id (nullable), status, snoozed_until,
              applied_via_portal (bool), followups_sent (int, 0–2), notes (free text),
              created_at, updated_at,
              UNIQUE(job_id, contact_id)
drafts        id, application_id, kind (email | li_note | li_dm), subject, body,
              edited (bool), gmail_draft_id, created_at
events        id, application_id, at, type, payload (json)   -- append-only audit trail
blocklist     contact_id, company, reason, at                -- "not interested"
runs          id, started_at, finished_at, stats (json), errors (json)
```

### Dedup
1. **Exact:** same `(source, source_job_id)` → same job; update fields if changed.
2. **Cross-source fingerprint:** `sha1(norm(company) | norm(title) | norm(city))`, where normalisation lowercases, strips punctuation, expands abbreviations (`sr` → `senior`, `pm` → `product manager`) and maps city aliases (`bangalore` → `bengaluru`, `gurugram` → `gurgaon`). On fingerprint collision, keep the record with the longer JD; remember the other source/URL as an alternate.

### Status machine

An `applications` row is created for every job that passes the prefilter, once it has been scored (`contact_id` is null until a contact is attached). Jobs dropped by the prefilter get no application; they keep `jobs.filter_reason`.

```
new → shortlisted (score ≥ 70) → drafted → approved (Gmail draft created) → sent
    → replied → interview → offer | rejected
side exits from any active state: skipped · snoozed (returns to previous state at snoozed_until)
                                  · applied_via_portal · not_interested
```
- Every transition writes an `events` row.
- `sent` is set manually ("Mark sent") in MVP; it starts the follow-up clock.
- A contact can be on at most one application per job (DB unique constraint).
- `not_interested` adds the contact (and company, if chosen) to `blocklist`; blocked contacts cannot be attached to new applications.

### Re-scoring
A score is reused if `jd_hash` and `rubric_version` both match. `jobseeker rescore` forces it.

## 6. Pre-filter (rules, no LLM)

A job is dropped (kept in `jobs` with `filter_reason` set, never deleted, and never scored) if:
- its location is not one of the four cities and it is not remote-within-India;
- its title matches the deny-list in `preferences.yaml` (initial: sales, SDE/software engineer, intern, director, head of, VP);
- its JD explicitly requires **8+ years** of experience (regex over "N+ years" patterns);
- it was posted more than 7 days ago.

## 7. Scoring

Claude (default `claude-sonnet-5-5`, configurable) with structured JSON output. The JD is passed as clearly delimited untrusted data; the system prompt instructs the model to ignore any instructions inside it.

### Rubric (`rubric.yaml`, versioned)

| Dimension | Pts | Rules |
|---|---|---|
| Role fit | 30 | Full: Senior PA, PA, APM, PM, AI PM, Founder's Office. Partial: analytics/BI roles with product focus. Low: generic data roles. |
| Experience fit | 25 | Required yrs 0–3 → 25 · 3–5 → 22 · 5–6 → 12 · 7+ → 4 · unstated → 20 |
| Skills match | 20 | Overlap between JD requirements and resume facts (A/B testing, SQL/BigQuery, Amplitude, ML/churn modelling, discovery, notification/growth work) |
| Company | 15 | Product company, AI-first or well-funded startup, or on the watchlist → high; agency/staffing → low |
| Location / pay | 10 | One of the 4 cities or remote; bonus if disclosed salary ≥ 25 LPA; penalty only if disclosed salary clearly < 20.7 LPA; undisclosed → neutral |

Output: `score`, `breakdown`, `matches` (≤ 3), `gaps` (≤ 2), `recommendation`:
- **≥ 70 → `apply`**: application moves to `shortlisted`, outreach drafted (→ `drafted`).
- **50–69 → `review`**: application stays `new`; visible in the inbox under a "review" filter, no drafts until requested ("Draft now" button).
- **< 50 → `hide`**: application stays `new`; hidden by default.

## 8. Outreach drafting

Generated only for `apply` jobs (or on demand). Default model `claude-opus-5-5`, configurable.

1. **Contact suggestion:** the target role to contact (Founder's Office → founder / chief of staff; APM/PM → hiring PM or product lead; analyst → analytics lead or recruiter), reasoning in one line, and a LinkedIn people-search URL (`linkedin.com/search/results/people/?keywords=<company> <role>`). The user pastes the actual name/email; email defaults to `unverified`.
2. **Cold email:** ≤ 150 words, subject line, a specific hook from the JD/company, 2–3 achievements selected from `facts.json`, one clear ask, mentions the attached resume.
3. **LinkedIn connection note:** ≤ 300 characters.
4. **LinkedIn follow-up DM:** ≤ 600 characters.

### Guards (enforced in code, not just prompts)
- **Fact grounding:** every number or percentage in a draft must appear in `facts.json`; otherwise the draft is regenerated (max 2 retries), then shown with a warning.
- **Style:** a banned-phrase list (e.g. "I hope this finds you well", "passionate", "leverage", "synergy", "I am writing to express") and a limit on em-dashes; violations trigger regeneration.
- **Length:** hard limits above, checked after generation.
- **Untrusted input:** JD text is data; outputs are plain text, and HTML is escaped when rendered.

### Resume facts
`jobseeker init` extracts resume text with PyMuPDF, asks Claude to produce `profile/facts.json` (a list of achievements with their exact metrics, skills, roles, dates), and writes it to disk for the user to review/edit. Re-extracted only when the resume file hash changes.

## 9. Dashboard (FastAPI + Jinja2 + HTMX)

Server-rendered, keyboard-friendly, light/dark mode, dense "inbox" styling (guided by the ui-ux-pro-max skill).

1. **Inbox (`/`):** today's `apply` jobs sorted by score. Row: score, title, company, city, age, source, top 2 matches, top gap. Filters: score band, role family, city, source, status. Keys: `j/k` move, `enter` open, `s` skip, `z` snooze 3 days.
2. **Application (`/applications/{id}`):** left side has the JD with matched terms highlighted and the score breakdown. Right side has the contact card (suggestion, LinkedIn search link, name/email fields with verification toggle), draft tabs (Email / LI note / LI DM; inline edit, regenerate, live counter) and notes. Actions:
   - **Approve → Gmail draft**: creates the draft with the resume attached and shows an "Open in Gmail" link.
   - **Copy LI note**: copies to the clipboard and opens the LinkedIn URL.
   - **Mark sent**, **Mark applied via portal**, **Skip**, **Snooze**, **Not interested**.
   - Approving with an `unverified` email shows a confirmation warning.
3. **Pipeline (`/pipeline`):** kanban columns by status; status changed through a menu. Card shows days since last event and a "follow up" badge after 5 days in `sent` with no newer event. A **Mark followed up** action increments `followups_sent` and restarts the 5-day clock; after 2 follow-ups the badge is no longer shown.
4. **Stat strip** (top of pipeline): drafted, sent, reply rate, interviews, jobs per source (last 30 days).

## 10. Gmail integration

- OAuth 2.0 desktop flow via `jobseeker auth-gmail`; scope **`gmail.compose` only**.
- `credentials.json` and `token.json` live in `secrets/` (git-ignored).
- Approve builds a MIME message (plain-text body, `resume.pdf` attachment) and calls `users.drafts.create`; stores `gmail_draft_id`; the dashboard links to the Gmail Drafts folder (`https://mail.google.com/mail/u/0/#drafts`). A per-draft deep link is a nice-to-have, added only if verified to work during implementation.
- If the token is missing or expired and can't be refreshed, Approve shows "Reconnect Gmail" and nothing is lost (draft text stays in the DB).

## 11. Scheduling, errors, secrets

- **Schedule:** a macOS `launchd` agent (`~/Library/LaunchAgents/com.kshitij.jobseeker.plist`) runs `jobseeker run` daily at 07:30; if the Mac was asleep it runs on wake. Logs go to `data/logs/`.
- **Source isolation:** each source runs in its own try block with a timeout (20 s per request, 3 retries with backoff on 429/5xx). One failing source never fails the run; its error is recorded in `runs.errors` and shown as a banner in the dashboard.
- **LLM failures:** a job whose scoring fails stays `new` and is retried on the next run; failed drafts can be regenerated from the UI.
- **Budgets:** per-run caps in config (default: score ≤ 80 jobs, draft ≤ 15 jobs, JSearch ≤ 8 requests/day to fit the free tier).
- **Secrets:** `ANTHROPIC_API_KEY`, `RAPIDAPI_KEY` in `.env`; `.env`, `secrets/`, `data/` (DB, logs) and `profile/resume.pdf` are git-ignored. `.env.example` is committed.

## 12. Configuration files

- `profile/preferences.yaml`: profile values from §2, title deny-list, cities, salary numbers, thresholds.
- `companies.yaml`: watchlist entries `{name, ats: greenhouse|lever|ashby, slug, tier}`. Seeded during implementation with Indian product/AI companies whose public board endpoints are **verified to respond**; unverifiable entries are left out. The user extends it over time.
- `rubric.yaml`: weights and rules from §7, plus `version`.

## 13. Testing

- `pytest`, with network disabled by default.
- **Source adapters:** tested against recorded JSON fixtures of real Greenhouse/Lever/Ashby/JSearch responses.
- **Pipeline:** unit tests for normalisation (city/title aliases), fingerprint collisions, prefilter rules (including "8+ years" regex edge cases).
- **LLM components:** tested through a fake client returning canned structured output. Guard tests cover a draft with an invented metric (rejected), a banned phrase (regenerated) and an over-length note (regenerated).
- **Status machine:** tests for allowed and disallowed transitions, event logging, the unique (job, contact) constraint and the blocklist.
- **Gmail:** MIME building tested offline; the API call is mocked.
- **Web:** FastAPI TestClient smoke tests for each page and each action endpoint.
- **One manual end-to-end check** before calling the MVP done: real run → dashboard → approve → draft visible in Gmail with the attachment.

## 14. Reference material

- v1 project (`../Trial/Job_Seeker`): rubric and state ideas; lessons are that URL-only dedup is insufficient and that the scorer must read enriched data.
- The career-ops plugin: reference for ATS endpoints, company lists and rubric structure (no code reuse). Use it manually for urgent applications while the MVP is being built.
