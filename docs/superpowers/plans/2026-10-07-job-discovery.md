# Job Discovery by Role and City Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find relevant openings by role × city on LinkedIn, Naukri and Indeed India, discover the companies' Greenhouse/Lever/Ashby boards automatically, and spend the AI budget on the highest pre-scored candidates.

**Architecture:** Each job site is one more `Source` (via `python-jobspy`). After fetching, a discovery step probes ATS boards for unseen companies and remembers them in a new `discovered_companies` table; active ones become ordinary ATS sources on later runs. A local pre-score (title/skills/experience/location) is stored per job and orders `jobs_needing_score`. LinkedIn descriptions are fetched only for top candidates.

**Tech Stack:** Python 3.13, uv, SQLite, httpx, pydantic, `python-jobspy==1.2.0`, pytest + respx + pytest-socket.

**Spec:** `docs/superpowers/specs/2026-10-07-job-discovery-design.md` (builds on `docs/superpowers/specs/2026-10-07-job-seeker-mvp-design.md`).

## Global Constraints

- Strictly free: no paid APIs, proxies or services.
- Tests never touch the network (`--disable-socket`). HTTP is mocked with `respx`; job-site results come through an injectable `scrape` function and recorded fixtures.
- `python-jobspy` is pinned to `==1.2.0` (the plan uses `LinkedIn._get_job_details`, a private method verified against 1.2.0 on 2026-10-07).
- Discovery probes at most **20** new companies per run; a company with no confirmed board is re-checked after **30** days.
- Pre-score parts: title 40, skills 30 (3 per matched skill, neutral 15 when the JD is empty), experience 20, location 10. `min_prescore` default **30**.
- LinkedIn descriptions: at most `linkedin_descriptions_per_run` (default **15**) per run.
- Existing databases are migrated in place; no data is deleted.
- The dashboard, scoring prompt, drafting, Gmail and status machine are not changed.
- Timestamps stay ISO-8601 UTC strings (`iso()`).

## Review Focus

1. **LinkedIn blocks part-way through its searches.** Expected: jobs from the searches that succeeded are kept and one warning is recorded; nothing crashes. Test: Task 4 `test_partial_failure_keeps_jobs_and_warns`.
2. **A different company owns the guessed slug** (e.g. a "Zeta" board that isn't the Zeta from LinkedIn). Expected: not added. Test: Task 5 `test_rejects_board_with_unrelated_titles`.
3. **Job-site company names carry legal suffixes or punctuation** ("Meesho Technologies Pvt Ltd", "Observe.AI", "Pocket FM"). Expected: sensible slugs are tried. Test: Task 5 `test_candidate_slugs`.
4. **The user's existing MVP database is opened by the new code.** Expected: the new column and table appear; jobs, applications and drafts are untouched. Test: Task 1 `test_migrates_mvp_database`.
5. **A job-site row is missing its company, title or URL** (scrapers return partial rows). Expected: that row is skipped, the rest are kept. Test: Task 4 `test_rows_missing_required_fields_are_skipped`.

---

### Task 1: Dependency, search settings and database migration

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Modify: `src/jobseeker/config.py`, `src/jobseeker/db/schema.sql`, `src/jobseeker/db/core.py`
- Test: `tests/test_config.py`, `tests/test_db_migration.py`

**Interfaces:**
- Produces: `config.SearchConfig` (fields per spec §4.1), `Preferences.search: SearchConfig`, `Preferences.min_prescore: int = 30`; table `discovered_companies`; column `jobs.prescore INTEGER`; `connect()` migrates older databases.

- [ ] **Step 1: Add the dependency**

Run: `uv add "python-jobspy==1.2.0"`
Expected: `pyproject.toml` lists `python-jobspy==1.2.0`; `uv run python -c "import jobspy"` exits 0.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_config.py`:
```python
def test_search_defaults_when_block_missing(prefs):
    assert prefs.search.sites == ["linkedin", "naukri", "indeed"]
    assert prefs.search.queries[0] == "Product Analyst"
    assert prefs.search.linkedin_descriptions_per_run == 15
    assert prefs.min_prescore == 30


def test_search_block_parsed(tmp_path):
    from jobseeker.config import load_preferences

    p = tmp_path / "p.yaml"
    p.write_text("""name: A
email: a@x.com
linkedin: https://l
experience_summary: x
target_roles: [PM]
cities: [Pune]
current_ctc_lpa: 1
target_base_lpa: 2
min_prescore: 45
search:
  queries: [APM]
  sites: [naukri]
""")
    prefs = load_preferences(p)
    assert prefs.search.queries == ["APM"] and prefs.search.sites == ["naukri"]
    assert prefs.search.hours_old == 72 and prefs.min_prescore == 45
```

Create `tests/test_db_migration.py`:
```python
import sqlite3

from jobseeker.db.core import connect
from jobseeker.db.jobs import upsert_job
from tests.factories import make_job


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_fresh_database_has_new_schema(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    assert "prescore" in _columns(conn, "jobs")
    assert "jobs_seen" in _columns(conn, "discovered_companies")


def test_migrates_mvp_database(tmp_path):
    path = tmp_path / "db.sqlite"
    conn = connect(path)
    job_id, _ = upsert_job(conn, make_job())
    # Turn it back into an MVP-era database.
    conn.execute("ALTER TABLE jobs DROP COLUMN prescore")
    conn.execute("DROP TABLE discovered_companies")
    conn.commit()
    conn.close()

    conn = connect(path)
    assert "prescore" in _columns(conn, "jobs")
    assert "status" in _columns(conn, "discovered_companies")
    assert conn.execute("SELECT title FROM jobs WHERE id = ?", (job_id,)).fetchone()[0] == "Senior Product Analyst"


def test_reconnect_does_not_alter_again(tmp_path):
    path = tmp_path / "db.sqlite"
    connect(path).close()
    connect(path).close()
    raw = sqlite3.connect(path)
    assert [r[1] for r in raw.execute("PRAGMA table_info(jobs)")].count("prescore") == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_db_migration.py`
Expected: FAIL (`AttributeError: 'Preferences' object has no attribute 'search'`, and missing `prescore` column)

- [ ] **Step 4: Implement**

In `src/jobseeker/config.py`, add above `class Preferences`:
```python
class SearchConfig(BaseModel):
    queries: list[str] = ["Product Analyst", "Associate Product Manager", "Product Manager",
                          "Founder's Office", "Growth Analyst"]
    locations: list[str] = ["Bengaluru", "Gurgaon", "Noida", "Pune"]
    remote_query: bool = True
    hours_old: int = 72
    results_per_search: int = 25
    sites: list[Literal["linkedin", "naukri", "indeed"]] = ["linkedin", "naukri", "indeed"]
    linkedin_descriptions_per_run: int = 15
```
and inside `class Preferences`, after `models: Models = Models()`:
```python
    search: SearchConfig = SearchConfig()
    min_prescore: int = 30
```

In `src/jobseeker/db/schema.sql`, add `prescore INTEGER,` to the `jobs` table directly after `filter_reason TEXT,`, and append:
```sql
CREATE TABLE IF NOT EXISTS discovered_companies (
  id INTEGER PRIMARY KEY,
  name_norm TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  ats TEXT,
  slug TEXT,
  status TEXT NOT NULL CHECK (status IN ('active', 'none', 'inactive')),
  checked_at TEXT NOT NULL,
  jobs_seen INTEGER NOT NULL DEFAULT 0
);
```

In `src/jobseeker/db/core.py`, replace the schema block in `connect` with:
```python
    # Only touch the schema when something is missing, so a reader never needs a write lock while the daily run writes.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'discovered_companies'"
    ).fetchone() is None:
        conn.executescript(SCHEMA)  # every statement is IF NOT EXISTS: creates a fresh DB or adds new tables
    if "prescore" not in {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}:
        conn.execute("ALTER TABLE jobs ADD COLUMN prescore INTEGER")
        conn.commit()
    return conn
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/jobseeker/config.py src/jobseeker/db/schema.sql src/jobseeker/db/core.py tests/test_config.py tests/test_db_migration.py
git commit -m "feat: search settings, pre-score column and discovered-companies table with in-place migration"
```

---

### Task 2: Repositories for discovered companies and pre-scores

**Files:**
- Create: `src/jobseeker/db/companies.py`
- Modify: `src/jobseeker/db/jobs.py`
- Test: `tests/test_db_companies.py`, `tests/test_db_jobs.py`

**Interfaces:**
- Consumes: `connect`, `iso` (Task 1 schema)
- Produces:
  - `db.companies`: `RECHECK_DAYS = 30`, `get_company(conn, name_norm) -> dict|None`, `record_company(conn, name_norm, display_name, status, ats=None, slug=None, now=None)`, `needs_check(conn, name_norm, now) -> bool`, `active_companies(conn) -> list[tuple[str, Company]]`, `mark_inactive(conn, name_norm, now)`, `bump_jobs_seen(conn, name_norm)`, `list_companies(conn) -> list[dict]`
  - `db.jobs`: `set_prescore(conn, job_id, score)`, `set_jd_text(conn, job_id, text)`, `expire_unscored(conn, now, max_age_days) -> int`, `jobs_missing_prescore(conn) -> list[dict]`; `jobs_needing_score` orders by `prescore` first (limit `-1` = no limit)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db_companies.py`:
```python
from datetime import UTC, datetime, timedelta

from jobseeker.db.companies import (
    active_companies, bump_jobs_seen, get_company, list_companies, mark_inactive, needs_check, record_company,
)
from jobseeker.db.core import connect

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def test_record_and_list_active():
    conn = connect(":memory:")
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", NOW)
    record_company(conn, "acme", "Acme", "none", now=NOW)
    [(norm, company)] = active_companies(conn)
    assert norm == "tracxn" and (company.name, company.ats, company.slug) == ("Tracxn", "lever", "tracxn")
    assert [r["name_norm"] for r in list_companies(conn)] == ["tracxn", "acme"]


def test_needs_check_rules():
    conn = connect(":memory:")
    assert needs_check(conn, "new co", NOW)
    record_company(conn, "a", "A", "active", "lever", "a", NOW)
    record_company(conn, "n", "N", "none", now=NOW)
    assert not needs_check(conn, "a", NOW + timedelta(days=90))
    assert not needs_check(conn, "n", NOW + timedelta(days=29))
    assert needs_check(conn, "n", NOW + timedelta(days=30))


def test_mark_inactive_and_recheck():
    conn = connect(":memory:")
    record_company(conn, "a", "A", "active", "lever", "a", NOW)
    mark_inactive(conn, "a", NOW)
    assert get_company(conn, "a")["status"] == "inactive" and active_companies(conn) == []
    assert needs_check(conn, "a", NOW + timedelta(days=31))


def test_bump_jobs_seen_only_for_known():
    conn = connect(":memory:")
    record_company(conn, "a", "A", "active", "lever", "a", NOW)
    bump_jobs_seen(conn, "a")
    bump_jobs_seen(conn, "a")
    bump_jobs_seen(conn, "unknown")
    assert get_company(conn, "a")["jobs_seen"] == 2


def test_rerecord_updates_status():
    conn = connect(":memory:")
    record_company(conn, "a", "A", "none", now=NOW)
    record_company(conn, "a", "A Ltd", "active", "ashby", "a", NOW + timedelta(days=31))
    row = get_company(conn, "a")
    assert (row["status"], row["ats"], row["display_name"]) == ("active", "ashby", "A Ltd")
```

Append to `tests/test_db_jobs.py`:
```python
def test_jobs_needing_score_orders_by_prescore():
    from jobseeker.db.jobs import set_prescore

    conn = _conn()
    a, _ = upsert_job(conn, make_job(source_job_id="a", fingerprint="fa"))
    b, _ = upsert_job(conn, make_job(source_job_id="b", fingerprint="fb"))
    c, _ = upsert_job(conn, make_job(source_job_id="c", fingerprint="fc"))
    set_prescore(conn, a, 40)
    set_prescore(conn, b, 90)
    assert [r["id"] for r in jobs_needing_score(conn, "v1", -1)] == [b, a, c]


def test_set_jd_text_keeps_longer_and_rehashes():
    from jobseeker.db.jobs import set_jd_text

    conn = _conn()
    job_id, _ = upsert_job(conn, make_job(jd_text=""))
    set_jd_text(conn, job_id, "full description")
    set_jd_text(conn, job_id, "short")
    row = get_job(conn, job_id)
    assert row["jd_text"] == "full description" and row["jd_hash"] == jd_hash("full description")


def test_expire_unscored_and_missing_prescore():
    from datetime import UTC, datetime, timedelta

    from jobseeker.db.jobs import expire_unscored, jobs_missing_prescore, set_prescore

    now = datetime(2026, 10, 7, tzinfo=UTC)
    conn = _conn()
    old, _ = upsert_job(conn, make_job(source_job_id="old", fingerprint="fo", posted_at=now - timedelta(days=9)))
    fresh, _ = upsert_job(conn, make_job(source_job_id="new", fingerprint="fn", posted_at=now - timedelta(days=1)))
    scored, _ = upsert_job(conn, make_job(source_job_id="s", fingerprint="fs", posted_at=now - timedelta(days=9)))
    save_score(conn, scored, ScoreResult(score=80, breakdown={}, matches=[], gaps=[], recommendation="apply",
                                         role_family="other"), "m", "v1", "h")
    assert expire_unscored(conn, now, 7) == 1
    assert get_job(conn, old)["filter_reason"] == "stale: never scored"
    assert get_job(conn, scored)["filter_reason"] is None
    assert [r["id"] for r in jobs_missing_prescore(conn)] == [fresh]
    set_prescore(conn, fresh, 50)
    assert jobs_missing_prescore(conn) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db_companies.py tests/test_db_jobs.py`
Expected: FAIL (`ModuleNotFoundError: jobseeker.db.companies`; `ImportError` for `set_prescore`)

- [ ] **Step 3: Implement `src/jobseeker/db/companies.py`**

```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from jobseeker.config import Company
from jobseeker.db.core import iso, utcnow

RECHECK_DAYS = 30


def get_company(conn: sqlite3.Connection, name_norm: str) -> dict | None:
    row = conn.execute("SELECT * FROM discovered_companies WHERE name_norm = ?", (name_norm,)).fetchone()
    return dict(row) if row else None


def record_company(conn: sqlite3.Connection, name_norm: str, display_name: str, status: str,
                   ats: str | None = None, slug: str | None = None, now: datetime | None = None) -> None:
    conn.execute(
        """INSERT INTO discovered_companies (name_norm, display_name, ats, slug, status, checked_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT (name_norm) DO UPDATE SET display_name = excluded.display_name, ats = excluded.ats,
             slug = excluded.slug, status = excluded.status, checked_at = excluded.checked_at""",
        (name_norm, display_name, ats, slug, status, iso(now) if now else utcnow()),
    )
    conn.commit()


def needs_check(conn: sqlite3.Connection, name_norm: str, now: datetime) -> bool:
    row = get_company(conn, name_norm)
    if row is None:
        return True
    if row["status"] == "active":
        return False
    return row["checked_at"] <= iso(now - timedelta(days=RECHECK_DAYS))


def active_companies(conn: sqlite3.Connection) -> list[tuple[str, Company]]:
    rows = conn.execute(
        "SELECT name_norm, display_name, ats, slug FROM discovered_companies WHERE status = 'active' ORDER BY id"
    ).fetchall()
    return [(r["name_norm"], Company(name=r["display_name"], ats=r["ats"], slug=r["slug"])) for r in rows]


def mark_inactive(conn: sqlite3.Connection, name_norm: str, now: datetime) -> None:
    conn.execute("UPDATE discovered_companies SET status = 'inactive', checked_at = ? WHERE name_norm = ?",
                 (iso(now), name_norm))
    conn.commit()


def bump_jobs_seen(conn: sqlite3.Connection, name_norm: str) -> None:
    conn.execute("UPDATE discovered_companies SET jobs_seen = jobs_seen + 1 WHERE name_norm = ?", (name_norm,))
    conn.commit()


def list_companies(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM discovered_companies
           ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'none' THEN 1 ELSE 2 END, jobs_seen DESC, id"""
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Extend `src/jobseeker/db/jobs.py`**

Replace `jobs_needing_score` with:
```python
def jobs_needing_score(conn: sqlite3.Connection, rubric_version: str, limit: int,
                       force: bool = False) -> list[dict]:
    order = "ORDER BY COALESCE(j.prescore, -1) DESC, j.first_seen_at DESC, j.id DESC LIMIT ?"
    if force:
        sql = f"SELECT j.* FROM jobs j WHERE j.filter_reason IS NULL {order}"
        params: tuple = (limit,)
    else:
        sql = f"""SELECT j.* FROM jobs j WHERE j.filter_reason IS NULL AND NOT EXISTS (
                    SELECT 1 FROM scores s WHERE s.job_id = j.id
                    AND s.rubric_version = ? AND s.jd_hash = j.jd_hash) {order}"""
        params = (rubric_version, limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
```
and add after `get_job`:
```python
def set_prescore(conn: sqlite3.Connection, job_id: int, score: int) -> None:
    conn.execute("UPDATE jobs SET prescore = ? WHERE id = ?", (score, job_id))
    conn.commit()


def set_jd_text(conn: sqlite3.Connection, job_id: int, text: str) -> None:
    """Store a fetched description, keeping whichever text is longer."""
    row = conn.execute("SELECT jd_text FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row and len(text) > len(row["jd_text"]):
        conn.execute("UPDATE jobs SET jd_text = ?, jd_hash = ? WHERE id = ?", (text, jd_hash(text), job_id))
        conn.commit()


def expire_unscored(conn: sqlite3.Connection, now: datetime, max_age_days: int) -> int:
    cutoff = iso(now - timedelta(days=max_age_days))
    cur = conn.execute(
        """UPDATE jobs SET filter_reason = 'stale: never scored'
           WHERE filter_reason IS NULL AND COALESCE(posted_at, first_seen_at) < ?
           AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.job_id = jobs.id)""", (cutoff,))
    conn.commit()
    return cur.rowcount


def jobs_missing_prescore(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT j.* FROM jobs j WHERE j.filter_reason IS NULL AND j.prescore IS NULL
           AND NOT EXISTS (SELECT 1 FROM scores s WHERE s.job_id = j.id) ORDER BY j.id""").fetchall()
    return [dict(r) for r in rows]
```
and change the imports at the top of `db/jobs.py` to include `timedelta`:
```python
from datetime import datetime, timedelta
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/db/companies.py src/jobseeker/db/jobs.py tests/test_db_companies.py tests/test_db_jobs.py
git commit -m "feat: discovered-company repository, pre-score ordering, JD backfill and expiry"
```

---

### Task 3: Pre-score

**Files:**
- Create: `src/jobseeker/pipeline/prescore.py`
- Test: `tests/test_prescore.py`

**Interfaces:**
- Consumes: `Job` (models), `Facts` (profile.facts), `Preferences`, `normalize_title`, `min_years_required`
- Produces: `prescore(job, facts, prefs) -> int` (0–100)

- [ ] **Step 1: Write the failing tests `tests/test_prescore.py`**

```python
import pytest

from jobseeker.pipeline.prescore import prescore
from tests.factories import make_job


def test_default_job(prefs, facts):
    # title 40 + skills SQL, A/B Testing = 6 + experience "2-4 years" = 20 + Bengaluru = 10
    assert prescore(make_job(), facts, prefs) == 76


@pytest.mark.parametrize("title,points", [
    ("Senior Product Analyst", 40), ("APM - Growth", 40), ("Founder's Office Associate", 40),
    ("Chief of Staff", 40), ("Product Manager II", 35), ("Growth Lead", 20), ("Program Lead", 5),
])
def test_title_points(prefs, facts, title, points):
    job = make_job(title=title, jd_text="", location_city=None, is_remote=False)
    assert prescore(job, facts, prefs) == points + 15 + 12


def test_skills_capped_and_neutral_when_empty(prefs, facts):
    many = " ".join(facts.skills) * 3
    full = make_job(jd_text=many, location_city=None)
    assert prescore(full, facts, prefs) == 40 + 18 + 12  # 6 skills x 3
    facts.skills = [f"skill{i}" for i in range(20)]
    capped = make_job(jd_text=" ".join(facts.skills), location_city=None)
    assert prescore(capped, facts, prefs) == 40 + 30 + 12


@pytest.mark.parametrize("jd,points", [
    ("1-3 years of experience", 20), ("5+ years of experience", 12), ("6+ years of experience", 4), ("", 12),
])
def test_experience_points(prefs, facts, jd, points):
    job = make_job(jd_text=jd, location_city=None)
    skills = 15 if not jd else 0
    assert prescore(job, facts, prefs) == 40 + skills + points


def test_location_points(prefs, facts):
    base = dict(jd_text="", title="Product Analyst")
    assert prescore(make_job(location_city="pune", **base), facts, prefs) == 40 + 15 + 12 + 10
    assert prescore(make_job(location_city=None, is_remote=True, **base), facts, prefs) == 40 + 15 + 12 + 8
    assert prescore(make_job(location_city="mumbai", **base), facts, prefs) == 40 + 15 + 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prescore.py`
Expected: FAIL (`ModuleNotFoundError: jobseeker.pipeline.prescore`)

- [ ] **Step 3: Implement `src/jobseeker/pipeline/prescore.py`**

```python
from __future__ import annotations

import re

from jobseeker.config import Preferences
from jobseeker.models import Job
from jobseeker.pipeline.normalize import normalize_title
from jobseeker.pipeline.prefilter import min_years_required
from jobseeker.profile.facts import Facts

# Cheap, local ranking used to spend the LLM budget on the most promising jobs (spec §4.3).
_TOP_TITLES = ("product analyst", "associate product manager", "founders office", "founder s office",
               "chief of staff")


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _title_points(job: Job, prefs: Preferences) -> int:
    title = normalize_title(job.title)
    if any(_has(title, t) for t in _TOP_TITLES):
        return 40
    if _has(title, "product manager"):
        return 35
    if any(_has(job.title.lower(), t.lower()) for t in prefs.title_allow):
        return 20
    return 5


def _skill_points(job: Job, facts: Facts) -> int:
    jd = job.jd_text.lower()
    if not jd.strip():
        return 15
    matched = sum(1 for s in facts.skills if s.strip() and _has(jd, s.strip().lower()))
    return min(30, 3 * matched)


def _experience_points(job: Job) -> int:
    years = min_years_required(job.jd_text)
    if years is None:
        return 12
    if years <= 3:
        return 20
    if years <= 5:
        return 12
    return 4


def _location_points(job: Job, prefs: Preferences) -> int:
    if job.location_city and job.location_city in {c.lower() for c in prefs.cities}:
        return 10
    return 8 if job.is_remote else 0


def prescore(job: Job, facts: Facts, prefs: Preferences) -> int:
    return (_title_points(job, prefs) + _skill_points(job, facts) + _experience_points(job)
            + _location_points(job, prefs))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prescore.py`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/pipeline/prescore.py tests/test_prescore.py
git commit -m "feat: local pre-score for ranking candidates before LLM scoring"
```

---

### Task 4: Job-site source (LinkedIn, Naukri, Indeed via JobSpy)

**Files:**
- Create: `src/jobseeker/sources/jobspy_source.py`
- Create fixtures: `tests/fixtures/jobspy_linkedin.json`, `tests/fixtures/jobspy_naukri.json`, `tests/fixtures/jobspy_indeed.json` (recorded)
- Test: `tests/test_sources_jobspy.py`

**Interfaces:**
- Consumes: `SearchConfig` (Task 1), `RawJob`, `canonical_city`, `parse_iso`
- Produces:
  - `jobspy_scrape(**kwargs) -> list[dict]` (the real scraper, JSON-safe rows)
  - `fetch_description(source, source_job_id) -> str` (LinkedIn only; `""` otherwise)
  - `to_raw_job(site, row, search_location) -> RawJob | None`
  - `JobSpySource(site, search, scrape=jobspy_scrape, sleep=time.sleep)` with `name == site`, `discovers = True`, `warnings: list[str]`, `searches() -> list[tuple[str, str]]`, `fetch(client) -> list[RawJob]`

- [ ] **Step 1: Record real fixtures (one-off, needs network)**

```bash
uv run python - <<'EOF'
import json
from jobspy import scrape_jobs
for site, kw in {
    "linkedin": dict(search_term="Product Analyst", location="India"),
    "naukri": dict(search_term="Associate Product Manager", location="Bengaluru", fetch_description=True),
    "indeed": dict(search_term="Product Analyst", location="Bengaluru", country_indeed="india"),
}.items():
    df = scrape_jobs(site_name=[site], results_wanted=4, hours_old=72, description_format="markdown", **kw)
    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    for r in rows:
        r["description"] = (r.get("description") or "")[:1500] or None
    open(f"tests/fixtures/jobspy_{site}.json", "w").write(json.dumps(rows, indent=1))
    print(site, len(rows))
EOF
```
Expected: three lines, each with a count ≥ 1.

- [ ] **Step 2: Write the failing tests `tests/test_sources_jobspy.py`**

```python
import json
from pathlib import Path

import pytest

from jobseeker.config import SearchConfig
from jobseeker.sources.jobspy_source import JobSpySource, fetch_description, to_raw_job

FIX = Path(__file__).parent / "fixtures"


def rows(site):
    return json.loads((FIX / f"jobspy_{site}.json").read_text())


def fake_scrape(table):
    calls = []

    def scrape(**kw):
        calls.append(kw)
        out = table(kw) if callable(table) else table
        if isinstance(out, Exception):
            raise out
        return out
    scrape.calls = calls
    return scrape


@pytest.mark.parametrize("site", ["linkedin", "naukri", "indeed"])
def test_recorded_rows_map_to_raw_jobs(site):
    jobs = [to_raw_job(site, r, "Bengaluru" if site != "linkedin" else "India") for r in rows(site)]
    jobs = [j for j in jobs if j]
    assert jobs and all(j.source == site and j.title and j.company and j.apply_url.startswith("http") for j in jobs)


def test_search_plan_per_site():
    search = SearchConfig()
    assert len(JobSpySource("linkedin", search).searches()) == 5
    assert JobSpySource("linkedin", search).searches()[0] == ("Product Analyst", "India")
    naukri = JobSpySource("naukri", search).searches()
    assert len(naukri) == 25 and ("Product Analyst", "Pune") in naukri and ("Product Analyst", "India") in naukri
    no_remote = SearchConfig(remote_query=False)
    assert len(JobSpySource("indeed", no_remote).searches()) == 20


def test_fetch_passes_site_options_and_dedups():
    row = {"id": "nk-1", "title": "APM", "company": "Tracxn", "location": "Bengaluru, India",
           "job_url": "https://naukri.com/1", "description": "d"}
    scrape = fake_scrape([row])
    src = JobSpySource("naukri", SearchConfig(queries=["APM"], locations=["Bengaluru"]), scrape=scrape,
                       sleep=lambda s: None)
    jobs = src.fetch(None)
    assert len(jobs) == 1 and len(scrape.calls) == 2  # Bengaluru + India, same job once
    kw = scrape.calls[0]
    assert kw["site_name"] == ["naukri"] and kw["fetch_description"] is True
    assert kw["country_indeed"] == "india" and kw["hours_old"] == 72 and kw["results_wanted"] == 25


def test_partial_failure_keeps_jobs_and_warns():
    row = {"id": "li-1", "title": "PM", "company": "X", "location": "Pune, India", "job_url": "https://l/1"}
    seq = iter([[row], RuntimeError("429 Too Many Requests")])
    src = JobSpySource("linkedin", SearchConfig(queries=["PM", "APM", "PA"]),
                       scrape=fake_scrape(lambda kw: next(seq)), sleep=lambda s: None)
    jobs = src.fetch(None)
    assert [j.source_job_id for j in jobs] == ["li-1"]
    assert len(src.warnings) == 1 and "429" in src.warnings[0] and "1 of 3" in src.warnings[0]


def test_first_failure_raises():
    src = JobSpySource("linkedin", SearchConfig(), scrape=fake_scrape(RuntimeError("blocked")),
                       sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        src.fetch(None)


def test_rows_missing_required_fields_are_skipped():
    assert to_raw_job("naukri", {"id": "1", "title": "PM", "company": None, "job_url": "https://x"}, "Pune") is None
    assert to_raw_job("naukri", {"id": "1", "title": "", "company": "C", "job_url": "https://x"}, "Pune") is None
    assert to_raw_job("naukri", {"id": None, "title": "PM", "company": "C", "job_url": "https://x"}, "Pune") is None


def test_indeed_state_only_location_gets_search_city():
    job = to_raw_job("indeed", {"id": "in-1", "title": "PA", "company": "C", "location": "KA, IN",
                                "job_url": "https://in.indeed.com/1"}, "Bengaluru")
    assert job.location == "Bengaluru, KA, IN"
    remote = to_raw_job("indeed", {"id": "in-2", "title": "PA", "company": "C", "location": "IN",
                                   "job_url": "https://in.indeed.com/2"}, "India")
    assert remote.location == "IN"


def test_naukri_experience_salary_remote_and_date():
    job = to_raw_job("naukri", {
        "id": "nk-9", "title": "APM", "company": "C", "location": "Pune, India", "job_url": "https://n/9",
        "experience_range": "6-11 Yrs", "description": "Build things.", "work_from_home_type": "Remote",
        "min_amount": 1500000, "max_amount": 2500000, "currency": "INR", "interval": "yearly",
        "date_posted": "2026-10-06T00:00:00.000"}, "Pune")
    assert job.jd_text == "Experience: 6-11 Yrs\n\nBuild things."
    assert job.remote is True and job.salary_text == "1500000–2500000 INR yearly"
    assert job.posted_at.isoformat() == "2026-10-06T00:00:00+00:00"


def test_fetch_description_only_for_linkedin():
    assert fetch_description("naukri", "nk-1") == ""
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_jobspy.py`
Expected: FAIL (`ModuleNotFoundError: jobseeker.sources.jobspy_source`)

- [ ] **Step 4: Implement `src/jobseeker/sources/jobspy_source.py`**

```python
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from jobseeker.config import SearchConfig
from jobseeker.models import RawJob
from jobseeker.pipeline.normalize import canonical_city
from jobseeker.sources.base import parse_iso

Scrape = Callable[..., list[dict[str, Any]]]
_PAUSE = {"linkedin": 3.0, "naukri": 1.0, "indeed": 1.0}  # seconds between searches, to stay polite


def jobspy_scrape(**kwargs) -> list[dict[str, Any]]:
    from jobspy import scrape_jobs

    df = scrape_jobs(**kwargs)
    return json.loads(df.to_json(orient="records", date_format="iso"))  # NaN -> None, dates -> ISO strings


def fetch_description(source: str, source_job_id: str) -> str:
    """Full description of one job-site posting. Only LinkedIn search results lack one."""
    if source != "linkedin":
        return ""
    from jobspy.linkedin import LinkedIn
    from jobspy.model import DescriptionFormat, ScraperInput, Site

    scraper = LinkedIn()
    scraper.scraper_input = ScraperInput(site_type=[Site.LINKEDIN], description_format=DescriptionFormat.MARKDOWN)
    details = scraper._get_job_details(source_job_id.removeprefix("li-")) or {}  # private in jobspy 1.2.0
    return (details.get("description") or "").strip()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _salary(row: dict) -> str | None:
    low, high = row.get("min_amount"), row.get("max_amount")
    if low is None:
        return None
    return f"{int(low)}–{int(high if high is not None else low)} {_text(row.get('currency'))} " \
           f"{_text(row.get('interval'))}".strip()


def to_raw_job(site: str, row: dict, search_location: str) -> RawJob | None:
    job_id, title, company, url = (_text(row.get(k)) for k in ("id", "title", "company", "job_url"))
    if not (job_id and title and company and url):
        return None
    location = _text(row.get("location"))
    if canonical_city(location) is None and search_location != "India":
        # Indeed India often reports only the state ("KA, IN"); the searched city is the better signal.
        location = f"{search_location}, {location}" if location else search_location
    description = _text(row.get("description"))
    experience = _text(row.get("experience_range"))
    if experience:
        description = f"Experience: {experience}\n\n{description}".strip()
    remote = row.get("is_remote") is True or _text(row.get("work_from_home_type")).lower() == "remote"
    return RawJob(source=site, source_job_id=job_id, company=company, title=title, location=location,
                  remote=remote, posted_at=parse_iso(_text(row.get("date_posted")) or None),
                  salary_text=_salary(row), jd_text=description, apply_url=url)


class JobSpySource:
    discovers = True  # companies seen here feed board discovery

    def __init__(self, site: str, search: SearchConfig, scrape: Scrape = jobspy_scrape,
                 sleep: Callable[[float], None] = time.sleep):
        self.site, self.search, self.scrape, self.sleep = site, search, scrape, sleep
        self.name = site
        self.warnings: list[str] = []

    def searches(self) -> list[tuple[str, str]]:
        if self.site == "linkedin":
            locations = ["India"]  # one search per query keeps LinkedIn under its rate limit
        else:
            locations = list(self.search.locations) + (["India"] if self.search.remote_query else [])
        return [(q, loc) for q in self.search.queries for loc in locations]

    def fetch(self, client: httpx.Client | None) -> list[RawJob]:
        self.warnings = []
        plan = self.searches()
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for i, (query, location) in enumerate(plan):
            if i:
                self.sleep(_PAUSE.get(self.site, 1.0))
            try:
                rows = self.scrape(site_name=[self.site], search_term=query, location=location,
                                   results_wanted=self.search.results_per_search, hours_old=self.search.hours_old,
                                   country_indeed="india", description_format="markdown",
                                   fetch_description=self.site == "naukri", verbose=0)
            except Exception as e:
                if not jobs:
                    raise
                self.warnings.append(f"stopped after {i} of {len(plan)} searches: {type(e).__name__}: {e}")
                break
            for row in rows:
                job = to_raw_job(self.site, row, location)
                if job and job.source_job_id not in seen:
                    seen.add(job.source_job_id)
                    jobs.append(job)
        return jobs
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_jobspy.py`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/jobseeker/sources/jobspy_source.py tests/fixtures/jobspy_*.json tests/test_sources_jobspy.py
git commit -m "feat: LinkedIn, Naukri and Indeed India sources via JobSpy"
```

---

### Task 5: Company board discovery

**Files:**
- Create: `src/jobseeker/pipeline/discovery.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `db.companies.needs_check`, `record_company` (Task 2); `get_json` (sources.http); `normalize_company`, `normalize_title`
- Produces: `MAX_PER_RUN = 20`, `candidate_slugs(name) -> list[str]`, `find_board(client, name, seen_titles, sleep=time.sleep) -> tuple[str, str] | None`, `discover(conn, client, seen: dict[str, tuple[str, set[str]]], skip: set[str], now, limit=MAX_PER_RUN, sleep=time.sleep) -> int` (number of new active boards). `seen` maps a normalised company name to (display name, set of `normalize_title` titles).

- [ ] **Step 1: Write the failing tests `tests/test_discovery.py`**

```python
from datetime import UTC, datetime, timedelta

import httpx
import respx

from jobseeker.db.companies import get_company, record_company
from jobseeker.db.core import connect
from jobseeker.pipeline.discovery import candidate_slugs, discover, find_board

NOW = datetime(2026, 10, 7, tzinfo=UTC)
GH = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"
LV = "https://api.lever.co/v0/postings/{}"
AB = "https://api.ashbyhq.com/posting-api/job-board/{}"
NO_SLEEP = dict(sleep=lambda s: None)


def test_candidate_slugs():
    assert candidate_slugs("Pocket FM") == ["pocketfm", "pocket-fm", "pocket"]
    assert candidate_slugs("Observe.AI") == ["observeai", "observe-ai", "observe"]
    assert candidate_slugs("Meesho Technologies Pvt Ltd") == ["meesho"]
    assert candidate_slugs("Pvt Ltd") == []


@respx.mock
def test_finds_lever_board_by_title():
    respx.get(LV.format("tracxn")).respond(json=[{"text": "Senior Associate Product Manager"}])
    respx.route().respond(404)
    hit = find_board(httpx.Client(), "Tracxn", {"tracxn senior associate product manager"}, **NO_SLEEP)
    assert hit == ("lever", "tracxn")


@respx.mock
def test_finds_greenhouse_board_by_name_when_titles_differ():
    respx.get(GH.format("groww")).respond(json={"jobs": [{"title": "Data Engineer"}]})
    respx.get("https://boards-api.greenhouse.io/v1/boards/groww").respond(json={"name": "Groww"})
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Groww", {"product analyst"}, **NO_SLEEP) == ("greenhouse", "groww")


@respx.mock
def test_rejects_board_with_unrelated_titles():
    respx.get(LV.format("zeta")).respond(json=[{"text": "Line Cook"}, {"text": "Barista"}])
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Zeta", {"product manager ii"}, **NO_SLEEP) is None


@respx.mock
def test_ashby_board_found():
    respx.get(AB.format("sarvam")).respond(json={"jobs": [{"title": "AI Product Manager"}]})
    respx.route().respond(404)
    assert find_board(httpx.Client(), "Sarvam", {"ai product manager"}, **NO_SLEEP) == ("ashby", "sarvam")


@respx.mock
def test_discover_records_active_and_none_and_respects_skip_and_limit():
    respx.get(LV.format("tracxn")).respond(json=[{"text": "APM"}])
    respx.route().respond(404)
    conn = connect(":memory:")
    seen = {"tracxn": ("Tracxn", {"associate product manager"}), "acme": ("Acme", {"pm"}),
            "cred": ("CRED", {"pm"}), "later": ("Later", {"pm"})}
    found = discover(conn, httpx.Client(), seen, skip={"cred"}, now=NOW, limit=2, **NO_SLEEP)
    assert found == 1
    assert get_company(conn, "tracxn")["status"] == "active"
    assert get_company(conn, "acme")["status"] == "none"
    assert get_company(conn, "cred") is None and get_company(conn, "later") is None


@respx.mock
def test_timeout_is_not_recorded_as_none():
    respx.route().mock(side_effect=httpx.ConnectTimeout("slow"))
    conn = connect(":memory:")
    assert discover(conn, httpx.Client(), {"acme": ("Acme", {"pm"})}, set(), NOW, **NO_SLEEP) == 0
    assert get_company(conn, "acme") is None


@respx.mock
def test_recently_checked_company_is_not_probed_again():
    route = respx.route().respond(404)
    conn = connect(":memory:")
    record_company(conn, "acme", "Acme", "none", now=NOW - timedelta(days=5))
    discover(conn, httpx.Client(), {"acme": ("Acme", {"pm"})}, set(), NOW, **NO_SLEEP)
    assert route.call_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_discovery.py`
Expected: FAIL (`ModuleNotFoundError: jobseeker.pipeline.discovery`)

- [ ] **Step 3: Implement `src/jobseeker/pipeline/discovery.py`**

```python
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import datetime

import httpx

from jobseeker.db.companies import needs_check, record_company
from jobseeker.pipeline.normalize import normalize_company, normalize_title
from jobseeker.sources.http import get_json

MAX_PER_RUN = 20
BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
    "lever": "https://api.lever.co/v0/postings/{}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
}
GREENHOUSE_BOARD = "https://boards-api.greenhouse.io/v1/boards/{}"


def candidate_slugs(name: str) -> list[str]:
    words = normalize_company(name).split()
    if not words:
        return []
    slugs = ["".join(words), "-".join(words)]
    if len(words) > 1:
        slugs.append(words[0])
    return list(dict.fromkeys(slugs))


def _get(client: httpx.Client, url: str, sleep: Callable[[float], None], params: dict | None = None):
    """The JSON body, or None when there is no board at this URL (404)."""
    try:
        return get_json(client, url, params=params, retries=1, sleep=sleep)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


def _board_titles(ats: str, data) -> list[str]:
    if ats == "lever":
        return [p.get("text", "") for p in data or [] if isinstance(p, dict)]
    return [j.get("title", "") for j in (data or {}).get("jobs", [])]


def _titles_match(board_titles: list[str], seen_titles: set[str]) -> bool:
    for title in board_titles:
        board = normalize_title(title)
        for seen in seen_titles:
            short, long_ = sorted((board, seen), key=len)
            if short and (short == long_ or (len(short.split()) >= 2 and short in long_)):
                return True
    return False


def find_board(client: httpx.Client, name: str, seen_titles: set[str],
               sleep: Callable[[float], None] = time.sleep) -> tuple[str, str] | None:
    norm = normalize_company(name)
    for slug in candidate_slugs(name):
        for ats, url in BOARD_URLS.items():
            data = _get(client, url.format(slug), sleep, {"mode": "json"} if ats == "lever" else None)
            if data is None:
                continue
            if _titles_match(_board_titles(ats, data), seen_titles):
                return ats, slug
            if ats == "greenhouse":
                meta = _get(client, GREENHOUSE_BOARD.format(slug), sleep)
                if meta and normalize_company(meta.get("name", "")) == norm:
                    return ats, slug
    return None


def discover(conn: sqlite3.Connection, client: httpx.Client, seen: dict[str, tuple[str, set[str]]],
             skip: set[str], now: datetime, limit: int = MAX_PER_RUN,
             sleep: Callable[[float], None] = time.sleep) -> int:
    found = checked = 0
    for norm, (display, titles) in seen.items():
        if checked >= limit:
            break
        if not norm or norm in skip or not needs_check(conn, norm, now):
            continue
        checked += 1
        try:
            hit = find_board(client, display, titles, sleep)
        except (httpx.HTTPError, ValueError):
            continue  # transient failure: leave unrecorded so the next run retries
        if hit:
            record_company(conn, norm, display, "active", hit[0], hit[1], now)
            found += 1
        else:
            record_company(conn, norm, display, "none", now=now)
    return found
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_discovery.py`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/pipeline/discovery.py tests/test_discovery.py
git commit -m "feat: automatic Greenhouse/Lever/Ashby board discovery with confirmation"
```

---

### Task 6: Source registry and `companies` command

**Files:**
- Modify: `src/jobseeker/sources/registry.py`, `src/jobseeker/cli.py`
- Test: `tests/test_sources_registry.py`, `tests/test_cli_companies.py`

**Interfaces:**
- Consumes: `JobSpySource` (Task 4), `active_companies`, `list_companies` (Task 2), `SearchConfig` (Task 1)
- Produces: `build_sources(companies, discovered=(), search=None) -> list[Source]` — yaml ATS sources, then discovered ATS sources (each with `discovered_as = <name_norm>`; skipped when the yaml list already has that company or that ats+slug), then one `JobSpySource` per `search.sites`. CLI `jobseeker companies`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sources_registry.py`:
```python
def test_build_sources_with_discovered_and_search(settings):
    from jobseeker.config import Company, SearchConfig

    companies = load_companies(settings.companies_path)
    discovered = [("tracxn", Company(name="Tracxn", ats="lever", slug="tracxn")),
                  ("cred", Company(name="CRED", ats="lever", slug="cred")),
                  ("cred club", Company(name="Cred Club", ats="lever", slug="cred"))]
    sources = build_sources(companies, discovered, SearchConfig(sites=["naukri", "linkedin"]))
    names = [s.name for s in sources]
    assert names[-3:] == ["lever:tracxn", "naukri", "linkedin"]
    assert names.count("lever:cred") == 1
    assert sources[-3].discovered_as == "tracxn"
```

Create `tests/test_cli_companies.py`:
```python
from datetime import UTC, datetime

from typer.testing import CliRunner

from jobseeker.cli import app
from jobseeker.db.companies import record_company
from jobseeker.db.core import connect


def test_companies_command_lists_groups(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    conn = connect(settings.db_path)
    now = datetime(2026, 10, 7, tzinfo=UTC)
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", now)
    record_company(conn, "acme", "Acme", "none", now=now)
    conn.close()
    out = CliRunner().invoke(app, ["companies"]).output
    assert "Boards found (1)" in out and "lever:tracxn" in out
    assert "No board (1)" in out and "Acme" in out


def test_companies_command_empty(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    out = CliRunner().invoke(app, ["companies"]).output
    assert "No companies discovered yet" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_registry.py tests/test_cli_companies.py`
Expected: FAIL (`TypeError: build_sources() takes 1 positional argument`; no `companies` command)

- [ ] **Step 3: Implement**

Replace `src/jobseeker/sources/registry.py`:
```python
from __future__ import annotations

from collections.abc import Iterable

from jobseeker.config import Company, SearchConfig
from jobseeker.pipeline.normalize import normalize_company
from jobseeker.sources.ashby import AshbySource
from jobseeker.sources.base import Source
from jobseeker.sources.greenhouse import GreenhouseSource
from jobseeker.sources.jobspy_source import JobSpySource
from jobseeker.sources.lever import LeverSource

_ATS = {"greenhouse": GreenhouseSource, "lever": LeverSource, "ashby": AshbySource}


def build_sources(companies: list[Company], discovered: Iterable[tuple[str, Company]] = (),
                  search: SearchConfig | None = None) -> list[Source]:
    sources: list[Source] = [_ATS[c.ats](c) for c in companies]
    names = {normalize_company(c.name) for c in companies}
    boards = {(c.ats, c.slug) for c in companies}
    for norm, company in discovered:
        if norm in names or (company.ats, company.slug) in boards:
            continue
        src = _ATS[company.ats](company)
        src.discovered_as = norm  # lets the run mark a vanished board inactive
        sources.append(src)
        names.add(norm)
        boards.add((company.ats, company.slug))
    if search is not None:
        sources += [JobSpySource(site, search) for site in search.sites]
    return sources
```

In `src/jobseeker/cli.py`, in `_run`, replace
`    sources = build_sources(load_companies(settings.companies_path))`
with:
```python
    from jobseeker.db.companies import active_companies

    sources = build_sources(load_companies(settings.companies_path), active_companies(conn), prefs.search)
```
and add a new command after `rescore`:
```python
@app.command()
def companies() -> None:
    """List companies discovered automatically from job-site results."""
    from jobseeker.db.companies import list_companies

    settings, _, _ = _load()
    rows = list_companies(connect(settings.db_path))
    if not rows:
        typer.echo("No companies discovered yet. They appear after `jobseeker run`.")
        return
    labels = {"active": "Boards found", "none": "No board", "inactive": "Board gone"}
    for status, label in labels.items():
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        typer.echo(f"\n{label} ({len(group)})")
        for r in group:
            board = f"{r['ats']}:{r['slug']}" if r["ats"] else "-"
            typer.echo(f"  {r['display_name'][:34]:<35}{board:<30}jobs seen {r['jobs_seen']:<5}"
                       f"checked {r['checked_at'][:10]}")
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/sources/registry.py src/jobseeker/cli.py tests/test_sources_registry.py tests/test_cli_companies.py
git commit -m "feat: registry combines favourites, discovered boards and job sites; companies command"
```

---

### Task 7: Daily run integration

**Files:**
- Modify: `src/jobseeker/pipeline/run.py`
- Test: `tests/test_run_discovery.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6
- Produces: `RunStats` gains `candidates`, `below_cutoff`, `discovered`. `run_daily(..., describe: Callable[[str, str], str] | None = None)` — `describe(source, source_job_id)` returns a description (default `jobspy_source.fetch_description`). Every run ends with `finish_run`, even after an unexpected exception (recorded as `run aborted: …`).

- [ ] **Step 1: Write the failing tests `tests/test_run_discovery.py`**

```python
from datetime import UTC, datetime, timedelta

import httpx
import respx

from jobseeker.db.companies import active_companies, get_company, record_company
from jobseeker.db.core import connect
from jobseeker.db.jobs import get_job
from jobseeker.db.runs import last_run
from jobseeker.llm import LLMQuotaExceeded
from jobseeker.models import RawJob
from jobseeker.pipeline.run import run_daily
from jobseeker.scoring.scorer import LLMScore
from tests.fakes import FakeLLM

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)
SCORE = dict(role_family="product_analyst", required_years=2, role_fit=20, experience_fit=20, skills_match=10,
             company=10, location_pay=5, matches=["SQL"], gaps=[])
DRAFT = dict(contact_role="Lead", contact_reason="r", email_subject="s", email_body="b", li_note="n", li_dm="d")


def handler(schema, prompt):
    return SCORE if schema is LLMScore else DRAFT


class Src:
    def __init__(self, name, jobs=None, error=None, discovers=False, warnings=None, discovered_as=None):
        self.name, self.jobs, self.error = name, jobs or [], error
        self.discovers = discovers
        self.warnings = warnings or []
        if discovered_as:
            self.discovered_as = discovered_as

    def fetch(self, client):
        if self.error:
            raise self.error
        return self.jobs


def raw(**kw):
    base = dict(source="naukri", source_job_id="1", company="Tracxn", title="Product Analyst",
                location="Bengaluru", jd_text="SQL and A/B testing. 2-4 years of experience.",
                apply_url="https://n/1", posted_at=NOW)
    base.update(kw)
    return RawJob(**base)


def run(conn, sources, prefs, rubric, facts, llm=None, **kw):
    kw.setdefault("now", NOW)
    return run_daily(conn, sources=sources, client=kw.pop("client", None), llm=llm or FakeLLM(handler=handler),
                     facts=facts, prefs=prefs, rubric=rubric, **kw)


def scored_titles(conn):
    return [r[0] for r in conn.execute("SELECT j.title FROM scores s JOIN jobs j ON j.id = s.job_id ORDER BY s.id")]


def test_scoring_follows_prescore_order(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.budgets.score_per_run = 1
    weak = raw(source_job_id="w", title="Strategy Manager", jd_text="Plan things.")
    strong = raw(source_job_id="s", title="Product Analyst")
    stats = run(conn, [Src("naukri", [weak, strong])], prefs, rubric, facts)
    assert scored_titles(conn) == ["Product Analyst"] and stats.candidates == 2


def test_low_prescore_set_aside(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.min_prescore = 40
    stats = run(conn, [Src("naukri", [raw(title="Insights Manager", jd_text="Lorem ipsum.", location="")])],
                prefs, rubric, facts)
    assert stats.below_cutoff == 1 and stats.scored == 0
    assert get_job(conn, 1)["filter_reason"] == "low pre-score: 32"


def test_linkedin_description_fetched_before_scoring(prefs, rubric, facts):
    conn = connect(":memory:")
    calls = []

    def describe(source, job_id):
        calls.append((source, job_id))
        return "Own SQL dashboards. 1-3 years of experience."
    stats = run(conn, [Src("linkedin", [raw(source="linkedin", source_job_id="li-7", jd_text="")])],
                prefs, rubric, facts, describe=describe)
    assert calls == [("linkedin", "li-7")] and stats.scored == 1
    assert get_job(conn, 1)["jd_text"].startswith("Own SQL dashboards")


def test_linkedin_description_failure_waits(prefs, rubric, facts):
    conn = connect(":memory:")

    def describe(source, job_id):
        raise RuntimeError("429")
    stats = run(conn, [Src("linkedin", [raw(source="linkedin", source_job_id="li-7", jd_text="")])],
                prefs, rubric, facts, describe=describe)
    assert stats.scored == 0 and get_job(conn, 1)["filter_reason"] is None
    assert any("linkedin descriptions: 1 failed" in e for e in stats.errors)


def test_linkedin_description_cap(prefs, rubric, facts):
    conn = connect(":memory:")
    prefs.search.linkedin_descriptions_per_run = 1
    jobs = [raw(source="linkedin", source_job_id=f"li-{i}", title=f"Product Analyst {i}", jd_text="")
            for i in range(3)]
    calls = []
    run(conn, [Src("linkedin", jobs)], prefs, rubric, facts,
        describe=lambda s, j: calls.append(j) or "SQL. 2 years of experience.")
    assert len(calls) == 1


def test_fetched_description_with_8_plus_years_is_filtered(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = run(conn, [Src("linkedin", [raw(source="linkedin", source_job_id="li-7", jd_text="")])],
                prefs, rubric, facts, describe=lambda s, j: "Needs 10+ years of experience.")
    assert stats.scored == 0 and get_job(conn, 1)["filter_reason"] == "experience: 10+ years"


def test_unscored_jobs_expire(prefs, rubric, facts):
    conn = connect(":memory:")
    quota = FakeLLM(handler=lambda schema, prompt: LLMQuotaExceeded("daily quota"))
    run(conn, [Src("naukri", [raw()])], prefs, rubric, facts, llm=quota)
    run(conn, [], prefs, rubric, facts, now=NOW + timedelta(days=8))
    assert get_job(conn, 1)["filter_reason"] == "stale: never scored"


@respx.mock
def test_discovery_from_job_site_companies(prefs, rubric, facts):
    respx.get("https://api.lever.co/v0/postings/tracxn").respond(json=[{"text": "Product Analyst"}])
    respx.route().respond(404)
    conn = connect(":memory:")
    stats = run(conn, [Src("naukri", [raw()], discovers=True)], prefs, rubric, facts, client=httpx.Client())
    assert stats.discovered == 1
    assert [n for n, _ in active_companies(conn)] == ["tracxn"]
    assert get_company(conn, "tracxn")["jobs_seen"] == 0  # counted from the run after discovery


def test_discovered_board_404_marks_inactive(prefs, rubric, facts):
    conn = connect(":memory:")
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", NOW)
    gone = httpx.HTTPStatusError("404", request=httpx.Request("GET", "https://x"),
                                 response=httpx.Response(404))
    run(conn, [Src("lever:tracxn", error=gone, discovered_as="tracxn")], prefs, rubric, facts)
    assert get_company(conn, "tracxn")["status"] == "inactive"


def test_jobs_seen_counted_for_discovered_company(prefs, rubric, facts):
    conn = connect(":memory:")
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", NOW)
    run(conn, [Src("lever:tracxn", [raw(source="lever")])], prefs, rubric, facts)
    assert get_company(conn, "tracxn")["jobs_seen"] == 1


def test_source_warnings_recorded(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = run(conn, [Src("linkedin", [raw()], warnings=["stopped after 2 of 5 searches"])],
                prefs, rubric, facts)
    assert "linkedin: stopped after 2 of 5 searches" in stats.errors


def test_unexpected_exception_still_finishes_run(prefs, rubric, facts):
    conn = connect(":memory:")
    stats = run(conn, [Src("broken", [None])], prefs, rubric, facts)
    assert any(e.startswith("run aborted:") for e in stats.errors)
    assert last_run(conn)["finished_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_run_discovery.py`
Expected: FAIL (`TypeError: run_daily() got an unexpected keyword argument 'describe'` / missing `RunStats` fields)

- [ ] **Step 3: Implement — replace `src/jobseeker/pipeline/run.py`**

```python
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import httpx

from jobseeker.config import Preferences, Rubric
from jobseeker.db.applications import (
    blocked_companies, ensure_application, get_application, get_status, save_draft, set_suggestion,
    transition, wake_snoozed,
)
from jobseeker.db.companies import bump_jobs_seen, mark_inactive
from jobseeker.db.jobs import (
    expire_unscored, get_job, job_from_row, jobs_missing_prescore, jobs_needing_score, save_score, set_filter_reason,
    set_jd_text, set_prescore, upsert_job,
)
from jobseeker.db.runs import finish_run, start_run
from jobseeker.llm import LLM, LLMError, LLMQuotaExceeded
from jobseeker.outreach.drafter import draft_outreach
from jobseeker.pipeline.discovery import discover
from jobseeker.pipeline.normalize import normalize, normalize_company, normalize_title
from jobseeker.pipeline.prefilter import prefilter
from jobseeker.pipeline.prescore import prescore
from jobseeker.profile.facts import Facts
from jobseeker.scoring.scorer import score_job

Describe = Callable[[str, str], str]


@dataclass
class RunStats:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    filtered: int = 0
    below_cutoff: int = 0
    discovered: int = 0
    candidates: int = 0
    scored: int = 0
    shortlisted: int = 0
    drafted: int = 0
    errors: list[str] = field(default_factory=list)


def draft_application(conn: sqlite3.Connection, app_id: int, llm: LLM, facts: Facts, prefs: Preferences,
                      now: datetime | None = None) -> None:
    app = get_application(conn, app_id)
    job = job_from_row(get_job(conn, app["job_id"]))
    result = draft_outreach(llm, job, facts, prefs, prefs.models.drafting)
    b = result.bundle
    save_draft(conn, app_id, "email", b.email_subject, b.email_body)
    save_draft(conn, app_id, "li_note", "", b.li_note)
    save_draft(conn, app_id, "li_dm", "", b.li_dm)
    set_suggestion(conn, app_id, b.contact_role, b.contact_reason, result.linkedin_search_url, result.warnings)
    if get_status(conn, app_id) in ("new", "shortlisted"):
        transition(conn, app_id, "drafted", {"warnings": len(result.warnings)}, now)


def _apps_needing_drafts(conn: sqlite3.Connection, limit: int) -> list[int]:
    rows = conn.execute(
        """SELECT a.id FROM applications a
           JOIN scores s ON s.id = (SELECT id FROM scores WHERE job_id = a.job_id ORDER BY id DESC LIMIT 1)
           WHERE a.status = 'shortlisted' ORDER BY s.score DESC LIMIT ?""", (limit,)).fetchall()
    return [r["id"] for r in rows]


def _rank(conn: sqlite3.Connection, stats: RunStats, job_id: int, facts: Facts, prefs: Preferences,
          cutoff: bool) -> None:
    """Store the job's pre-score; with cutoff, set aside jobs below min_prescore."""
    row = get_job(conn, job_id)
    if row is None or row["filter_reason"] is not None:
        return
    points = prescore(job_from_row(row), facts, prefs)
    set_prescore(conn, job_id, points)
    if cutoff and points < prefs.min_prescore:
        set_filter_reason(conn, job_id, f"low pre-score: {points}")
        stats.below_cutoff += 1


def _fetch(conn, stats: RunStats, sources, client, facts: Facts, prefs: Preferences, now: datetime) -> None:
    blocked = blocked_companies(conn)
    known = {normalize_company(s.company.name) for s in sources if hasattr(s, "company")}
    seen: dict[str, tuple[str, set[str]]] = {}
    for src in sources:
        try:
            raws = src.fetch(client)
        except Exception as e:  # one broken source must never kill the run
            stats.errors.append(f"{src.name}: {type(e).__name__}: {e}")
            norm = getattr(src, "discovered_as", None)
            if norm and isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                mark_inactive(conn, norm, now)
            continue
        stats.errors += [f"{src.name}: {w}" for w in getattr(src, "warnings", [])]
        stats.fetched += len(raws)
        for raw in raws:
            job = normalize(raw)
            if getattr(src, "discovers", False):
                seen.setdefault(normalize_company(job.company), (job.company, set()))[1].add(
                    normalize_title(job.title))
            job_id, is_new = upsert_job(conn, job, now)
            if is_new:
                stats.new += 1
                reason = prefilter(job, prefs, now, blocked)
                if reason:
                    set_filter_reason(conn, job_id, reason)
                    stats.filtered += 1
                    continue
                bump_jobs_seen(conn, normalize_company(job.company))
            else:
                stats.duplicates += 1
            _rank(conn, stats, job_id, facts, prefs, cutoff=is_new)
    if client is not None and seen:
        stats.discovered = discover(conn, client, seen, known | blocked, now)


def _select(conn, stats: RunStats, rubric: Rubric, facts: Facts, prefs: Preferences, now: datetime,
            force: bool, describe: Describe) -> list[dict]:
    expire_unscored(conn, now, prefs.max_age_days)
    for row in jobs_missing_prescore(conn):  # jobs stored before pre-scores existed
        _rank(conn, stats, row["id"], facts, prefs, cutoff=True)
    budget = prefs.budgets.score_per_run
    cap = prefs.search.linkedin_descriptions_per_run
    stats.candidates = len(jobs_needing_score(conn, rubric.version, -1, force=force))
    blocked = blocked_companies(conn)
    fetched, failures, last_error = 0, 0, ""
    for row in jobs_needing_score(conn, rubric.version, budget + cap, force=force):
        if row["source"] != "linkedin" or row["jd_text"].strip():
            continue
        if fetched >= cap:
            break
        fetched += 1
        try:
            text = describe(row["source"], row["source_job_id"])
        except Exception as e:
            failures, last_error = failures + 1, f"{type(e).__name__}: {e}"
            continue
        if not text:
            continue
        set_jd_text(conn, row["id"], text)
        job = job_from_row(get_job(conn, row["id"]))
        reason = prefilter(job, prefs, now, blocked)  # the description may reveal 8+ years etc.
        if reason:
            set_filter_reason(conn, row["id"], reason)
            stats.filtered += 1
            continue
        _rank(conn, stats, row["id"], facts, prefs, cutoff=False)
    if failures:
        stats.errors.append(f"linkedin descriptions: {failures} failed (last: {last_error})")
    rows = jobs_needing_score(conn, rubric.version, budget + cap, force=force)
    return [r for r in rows if r["jd_text"].strip()][:budget]


def _run(conn, stats: RunStats, *, sources, client, llm: LLM, facts: Facts, prefs: Preferences, rubric: Rubric,
         now: datetime, fetch: bool, force_rescore: bool, describe: Describe) -> None:
    wake_snoozed(conn, now)
    if fetch:
        _fetch(conn, stats, sources, client, facts, prefs, now)

    quota_hit = False
    for row in _select(conn, stats, rubric, facts, prefs, now, force_rescore, describe):
        try:
            result = score_job(llm, job_from_row(row), facts, prefs, rubric, prefs.models.scoring)
        except LLMQuotaExceeded as e:
            stats.errors.append(f"scoring stopped: {e}")
            quota_hit = True
            break
        except LLMError as e:
            stats.errors.append(f"score job {row['id']}: {e}")
            continue
        save_score(conn, row["id"], result, prefs.models.scoring, rubric.version, row["jd_hash"])
        stats.scored += 1
        app_id = ensure_application(conn, row["id"], now)
        if result.recommendation == "apply" and get_status(conn, app_id) == "new":
            transition(conn, app_id, "shortlisted", {"score": result.score}, now)
            stats.shortlisted += 1

    # Scoring and drafting use different models (separate daily quotas); skip drafting only if they share one.
    same_model = prefs.models.drafting == prefs.models.scoring
    drafting_apps = [] if (quota_hit and same_model) else _apps_needing_drafts(conn, prefs.budgets.draft_per_run)
    for app_id in drafting_apps:
        try:
            draft_application(conn, app_id, llm, facts, prefs, now)
            stats.drafted += 1
        except LLMQuotaExceeded as e:
            stats.errors.append(f"drafting stopped: {e}")
            break
        except LLMError as e:
            stats.errors.append(f"draft application {app_id}: {e}")


def run_daily(conn: sqlite3.Connection, *, sources, client, llm: LLM, facts: Facts, prefs: Preferences,
              rubric: Rubric, now: datetime | None = None, fetch: bool = True,
              force_rescore: bool = False,
              clock: Callable[[], datetime] = lambda: datetime.now(UTC),
              describe: Describe | None = None) -> RunStats:
    if describe is None:
        from jobseeker.sources.jobspy_source import fetch_description as describe
    now = now or clock()
    stats = RunStats()
    run_id = start_run(conn, now)
    try:
        _run(conn, stats, sources=sources, client=client, llm=llm, facts=facts, prefs=prefs, rubric=rubric,
             now=now, fetch=fetch, force_rescore=force_rescore, describe=describe)
    except Exception as e:  # the run log must always be closed
        stats.errors.append(f"run aborted: {type(e).__name__}: {e}")
    finally:
        data = asdict(stats)
        errors = data.pop("errors")
        finish_run(conn, run_id, data, errors, clock())
    return stats
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: all passed (including the MVP's `tests/test_run.py`)

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/pipeline/run.py tests/test_run_discovery.py
git commit -m "feat: daily run with job-site sources, discovery, pre-score ranking and LinkedIn descriptions"
```

---

### Task 8: Configuration, docs and live check

**Files:**
- Modify: `profile/preferences.yaml`, `README.md`

**Interfaces:**
- Consumes: the whole feature

- [ ] **Step 1: Add the explicit `search` block to `profile/preferences.yaml`**

Append:
```yaml
min_prescore: 30
# Job-site searches (LinkedIn once per query across India; Naukri/Indeed per query x location)
search:
  queries: [Product Analyst, Associate Product Manager, Product Manager, Founder's Office, Growth Analyst]
  locations: [Bengaluru, Gurgaon, Noida, Pune]
  remote_query: true
  hours_old: 72
  results_per_search: 25
  sites: [linkedin, naukri, indeed]
  linkedin_descriptions_per_run: 15
```

Run: `uv run pytest`
Expected: all passed

- [ ] **Step 2: Update `README.md`**

Replace the `companies.yaml` bullet under **Tuning** with:
```markdown
- `profile/preferences.yaml` → `search:` the roles and cities searched every morning on LinkedIn, Naukri and Indeed India. Companies found there that use Greenhouse, Lever or Ashby are discovered automatically and fetched from their own boards afterwards; see them with `uv run jobseeker companies`.
- `companies.yaml`: optional favourites that are always fetched. Check a slug with `uv run python scripts/verify_companies.py <slug>`.
```
and add under **Cost and limits**:
```markdown
- Job-site scraping is free but unofficial: LinkedIn may rate-limit after a few searches. A blocked site is skipped for the day and listed in the run's errors; everything else continues.
```

- [ ] **Step 3: Live check (needs network and the Groq key)**

1. `uv run jobseeker run`: the JSON stats show `fetched` well above the MVP's ~1,490, `candidates` > 9, `discovered` ≥ 1, `scored` > 0, and no `run aborted` error. Job-site warnings are acceptable.
2. `uv run jobseeker companies`: lists at least one "Boards found" company.
3. `uv run jobseeker serve` and `curl -s http://127.0.0.1:8000/ | grep -c 'data-href'`: the inbox renders rows.

- [ ] **Step 4: Commit**

```bash
git add profile/preferences.yaml README.md
git commit -m "docs: search settings and discovery in README"
```
