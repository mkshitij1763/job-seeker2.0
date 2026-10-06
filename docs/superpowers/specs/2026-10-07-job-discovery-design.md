# job-seeker2.0: job discovery by role and city (design)

**Date:** 2026-10-07
**Status:** Approved in brainstorming (sections 1–4 by the user, approach A). Awaiting review of this written spec.
**Builds on:** `docs/superpowers/specs/2026-10-07-job-seeker-mvp-design.md` (the MVP, merged to `main`). Everything in that spec still holds unless this document changes it.

## 1. Problem and goal

The MVP finds jobs only at the 13 companies in `companies.yaml`. The user doesn't know every relevant company, and keeping a list up to date by hand defeats the point of the tool. The first live run showed the cost: 1,199 new jobs gave only 9 candidates and 5 drafts, all from 2 companies.

**Goal:** find relevant openings by **role and city**, at companies the user has never heard of, with no list to maintain. The scoring, drafting, dashboard and Gmail flow stay as they are.

**Success criteria:**
1. A normal daily run, with no change to `companies.yaml`, produces candidates from companies outside that file.
2. Companies with a public Greenhouse, Lever or Ashby board are discovered automatically and fetched from their board on later runs.
3. The AI's daily budget (35 scorings) goes to the most promising candidates, not just the newest.
4. If any one job site blocks or breaks, the run still completes and records one clear error.
5. Everything stays **free**: no paid APIs, proxies or services.

## 2. Decisions made in brainstorming

| Topic | Decision |
|---|---|
| Approach | **A**: search job sites by role × city, then discover company boards from the results. |
| Sources | LinkedIn, Naukri and Indeed India via the free `python-jobspy` library, plus the existing Greenhouse, Lever and Ashby adapters. |
| Budget | **Strictly free.** Occasional blocks are accepted; that source is skipped for the day. |
| Startup boards | Wellfound, YC Work at a Startup, Instahyre and Cutshort are **out of scope**: no free public access (login walls or bot blocking). Startups are reached through the job sites and board discovery instead. |
| `companies.yaml` | Becomes an optional favourites list that is always fetched. The user is never required to edit it. |
| Company management UI | None. The existing **Not interested → also block company** action covers removal. Visibility comes from a read-only CLI command. |

## 3. Facts this design relies on

These were checked on 2026-10-07 against the JobSpy README (github.com/speedyapply/JobSpy):
- JobSpy supports LinkedIn, Indeed (with `country_indeed="india"`), Naukri, Glassdoor, Google, ZipRecruiter, Bayt and BDJobs. It needs Python ≥ 3.10.
- **LinkedIn** usually rate-limits one IP around the 10th results page. Its search results carry no job description unless descriptions are fetched (`fetch_description`), which costs extra requests. Proxies are recommended but not used here.
- Every job board caps a single search at about 1,000 results.
- Indeed and Naukri return descriptions in their search results.

The build plan's first task re-checks the installed version's API (function name, parameters, returned columns) and adjusts names to match it.

## 4. Design

### 4.1 Daily searches (new job-site sources)

**Configuration:** a new `search` block in `profile/preferences.yaml`:
```yaml
search:
  queries: [Product Analyst, Associate Product Manager, Product Manager, Founder's Office, Growth Analyst]
  locations: [Bengaluru, Gurgaon, Noida, Pune]
  remote_query: true          # one extra "India" search per query, for remote roles
  hours_old: 72
  results_per_search: 25
  sites: [linkedin, naukri, indeed]
  linkedin_descriptions_per_run: 15
```
All keys have defaults (the values above), so an older `preferences.yaml` without the block still loads.

**Search plan per site:**
- **Naukri and Indeed India:** each query × each location, plus each query × "India" when `remote_query` is true. With the defaults that's 25 searches per site.
- **LinkedIn:** each query once, with location "India" (5 searches), to stay well under its rate limit. The existing city filter removes jobs outside the target cities. Search results are fetched **without** descriptions.

**Mapping to `RawJob`:** `source` is `linkedin`, `naukri` or `indeed`. `source_job_id` is the site's job ID. `apply_url` is the site's job URL. `posted_at` is the posting date when present. `salary_text` comes from the min/max/currency/interval fields when present. `jd_text` is the description converted to plain text (with the existing `html_to_text` when it contains HTML), or empty for LinkedIn. `remote` comes from the site's remote flag. `company` is the site's company name.

**Integration:** each site is one `Source` (the existing protocol), so the existing per-source error isolation, normalisation, cross-source dedup and prefilter apply unchanged. The JobSpy call is wrapped behind an injectable `scrape` function so tests never touch the network.

**Known gap (accepted):** a job site may use a company's legal name ("One97 Communications" for Paytm). Fingerprint dedup then misses that pair and the user may see the same role twice. No alias table in this iteration.

### 4.2 Company discovery

**Trigger:** after the sources are fetched, every company name from the job-site sources that is not yet in the discovered-companies table and not in `companies.yaml` is queued for discovery, up to **20 new companies per run** in order of first appearance.

**Probe:**
1. **Candidate slugs.** Strip `normalize_company`'s stop words, then generate up to 3 variants: words joined with nothing (`pocketfm`), joined with hyphens (`pocket-fm`), and the first word alone when the name has more than one word (`pocket`). Duplicates are removed.
2. **Each ATS.** For each slug, request Greenhouse, Lever and Ashby's public board endpoints (the URLs the existing adapters use). That's at most 9 requests per company, through the existing retrying `get_json`. A 404 means "no board here".
3. **Confirmation.** A board found at a slug is accepted only if **either**:
   - at least one job on the board has a `normalize_title` equal to the `normalize_title` of a job seen for that company on a job site in this run, **or**
   - (Greenhouse only) the board's name, from `GET /v1/boards/{slug}`, normalises (`normalize_company`) to the same string as the company name.

   **Order:** for each slug in the order generated, try Greenhouse, then Lever, then Ashby. The first board that passes confirmation wins and probing stops.

**Stored state:** new table `discovered_companies`:
```
discovered_companies  id, name_norm UNIQUE, display_name, ats NULL, slug NULL,
                      status CHECK IN ('active','none','inactive'),
                      checked_at, jobs_seen INTEGER DEFAULT 0
```
- **`active`:** a confirmed board. Fetched every run from then on, alongside the `companies.yaml` entries.
- **`none`:** no confirmed board. Re-checked after **30 days**.
- **`inactive`:** a previously active board that now returns 404. It is no longer fetched and is re-checked after 30 days.
- **Probe failures:** a timeout or 5xx on any request leaves the company unrecorded, so it is retried next run. A transport error is never recorded as `none`.
- **`jobs_seen`:** the number of jobs from that company that passed the prefilter, counted across sources, for the CLI listing.

**Blocking:** a company blocked through the existing blocklist (normalised name) is skipped by discovery and filtered out as today.

**CLI:** `jobseeker companies` prints the discovered companies grouped by status (name, ATS and slug, `jobs_seen`, last checked). It is read-only.

### 4.3 Pre-score ranking

**Purpose:** choose which candidates the AI scores within the existing `budgets.score_per_run` (35).

**Pre-score (0–100), computed locally when a job passes the prefilter, stored in the new column `jobs.prescore`:**

| Part | Max | Rule |
|---|---|---|
| Title | 40 | `normalize_title` contains "product analyst", "associate product manager", "founders office", "founder s office" or "chief of staff": 40. Contains "product manager": 35. Contains any other `title_allow` term: 20. Otherwise: 5. |
| Skills | 30 | Count the `facts.skills` that appear in `jd_text` (case-insensitive, word-boundary). Each counts 3 points, capped at 30. An empty `jd_text` scores a neutral 15. |
| Experience | 20 | `min_years_required(jd_text)`: ≤ 3 gives 20, `None` gives 12, 4–5 gives 12, 6–7 gives 4. (8+ is already dropped by the prefilter.) |
| Location | 10 | `location_city` in the target cities: 10. Remote within India: 8. Otherwise: 0. |

**Selection:** `jobs_needing_score` orders by `prescore DESC`, then the existing newest-first order. Jobs with a NULL prescore (rows created before this change) are computed lazily at the start of a run.

**Minimum:** a new preference `min_prescore` (default **30**). A job below it gets `filter_reason = "low pre-score: <n>"` and is never sent to the AI.

**Expiry:** at the start of scoring, any unscored, unfiltered job whose `posted_at` (or `first_seen_at` when `posted_at` is missing) is older than `max_age_days` gets `filter_reason = "stale: never scored"`.

**LinkedIn descriptions:** before scoring, for each selected job with `source = 'linkedin'` and empty `jd_text`:
1. If the fingerprint matches a job from an ATS source (an alternate URL already merged by dedup), the ATS description is already present. Nothing to do.
2. Otherwise, fetch the description (via JobSpy's single-job fetch, or LinkedIn's public guest job-posting page, as the plan determines), up to `linkedin_descriptions_per_run` per run. On success, the description is stored with `upsert_job`'s keep-longest rule, and the pre-score is recomputed.
3. On failure, or past the cap, the job is skipped this run and stays in the queue.

The selection is then re-ordered with the updated pre-scores, and the top `score_per_run` jobs that have a non-empty `jd_text` are scored.

**Run summary:** `RunStats` gains `candidates` (unscored, unfiltered jobs considered this run), `below_cutoff` (jobs set aside by `min_prescore`) and `discovered` (new boards confirmed this run).

### 4.4 Failure handling

| Failure | Behaviour |
|---|---|
| A job site blocks, times out or changes format | That source records one error (`linkedin: <type>: <message>`). Other sources continue. |
| A discovery probe times out or returns 5xx | The company is not recorded and is retried next run. |
| A LinkedIn description fetch fails | That job is skipped for this run and stays queued. |
| An unexpected exception anywhere in `run_daily` | Caught at the top level. The error is appended and `finish_run` always runs (try/finally). This resolves the MVP's deferred minor "M5". |

## 5. Changes to existing code

| File | Change |
|---|---|
| `config.py` | Add `SearchConfig` (§4.1) and `Preferences.search: SearchConfig = SearchConfig()`. Add `Preferences.min_prescore: int = 30`. |
| `db/schema.sql` and `db/core.py` | Add `discovered_companies` and `jobs.prescore`. `connect()` adds the table and column to an existing database when missing (`CREATE TABLE IF NOT EXISTS`, plus `ALTER TABLE jobs ADD COLUMN prescore INTEGER` when `PRAGMA table_info` lacks it). Existing data is untouched. |
| `db/jobs.py` | `set_prescore(conn, job_id, n)`. `jobs_needing_score` orders by prescore. |
| `db/companies.py` (new) | Discovered-company CRUD: get/record by `name_norm`, list active, list due for re-check, increment `jobs_seen`. |
| `sources/jobspy_source.py` (new) | `JobSpySource(site, search_config, scrape=…)` implementing `Source`, plus the LinkedIn description fetcher. |
| `sources/registry.py` | `build_sources(companies, discovered, search)` returns the yaml companies, then the active discovered companies, then the job-site sources. |
| `pipeline/discovery.py` (new) | Candidate slugs, probe, confirmation, recording (§4.2). |
| `pipeline/prescore.py` (new) | `prescore(job, facts, prefs) -> int` (§4.3). |
| `pipeline/run.py` | After fetch: discovery. After prefilter: pre-score and the min cutoff. Before scoring: expiry, LinkedIn descriptions, re-rank. New stats. Top-level try/finally. |
| `cli.py` | Pass discovered companies and search settings into `build_sources`. New `companies` command. |
| `pyproject.toml` | Add `python-jobspy` via `uv add`. |

**Unchanged:** the dashboard, scoring prompt and rubric, drafting and guards, Gmail, the status machine, and the launchd schedule.

## 6. Testing

- **No network in tests**, as today (`pytest-socket`). Job-site results come from fixtures recorded once from real searches and trimmed to a few rows per site (`tests/fixtures/jobspy_<site>.json`), fed through the injectable `scrape` function. ATS probes are mocked with `respx`.
- **Unit tests:**
  - Mapping each site's rows to `RawJob`.
  - Slug candidates (including "Observe.AI", "Pocket FM", "Meesho Technologies Pvt Ltd").
  - Confirmation accepting a title match, accepting a Greenhouse name match, and rejecting a same-slug different company.
  - Status transitions: active, none, inactive, the 30-day re-check, and "timeout is not none".
  - Each pre-score part and its boundaries.
  - The min-cutoff reason, expiry, and the LinkedIn description cap and failure path.
  - The database migration on an MVP-schema database.
- **Integration tests (`run_daily`):**
  - Job-site and board sources merge as duplicates into one job.
  - A newly discovered board is fetched on the next run.
  - The AI scores in pre-score order, within budget.
  - A source raising an exception still yields a finished run with one error.
  - An unexpected exception still writes `finished_at`.
- **Live check after the build:** one real `jobseeker run`. The stats should show job-site sources fetched, `discovered > 0` and `candidates` > the MVP's 9, with no crash. Then `jobseeker companies` lists the new boards.

## 7. Out of scope

- Wellfound, YC Work at a Startup, Instahyre and Cutshort (no free public access).
- Proxies, or any paid scraping service or API.
- A company alias table for legal-name vs brand-name dedup.
- A dashboard page for managing companies, and showing the pre-score in the UI.
- Re-running the prefilter on existing jobs when filter rules change (MVP open item).
- Using the `tier` field of `companies.yaml` in scoring.
