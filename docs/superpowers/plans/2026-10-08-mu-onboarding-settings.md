# Multi-user onboarding and Settings: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Chosen method for this plan: Native (inline), via superpowers:executing-plans.**

**Goal:** Per-user preferences, resume and facts live in the database. A new user is guided through 4 onboarding steps. Everyone gets a Settings tab: edit preferences with a two-way re-filter preview, replace the resume, download their data, delete their account. Server-wide settings move to `config/app.yaml`.

**Architecture:**
- `UserPrefs` (a JSON blob in `user_prefs`) and `AppConfig` (`config/app.yaml`) are combined by `effective_prefs()` into today's `Preferences`, so prefilter, prescore, scorer and drafter keep their signatures.
- A request-scoped `current_prefs` dependency replaces `app.state.prefs`.
- Facts move to `user_facts`, extracted in a background task under a `groq:facts` budget.
- Migration v2 imports the owner's files from `$JOBSEEKER_HOME/profile/`.
- `reevaluate()` replaces `refilter`, working in both directions.

**Tech Stack:** Python 3.13, FastAPI, Jinja2 + HTMX (`hx-boost`, `hx-trigger="every 3s"`), SQLite, Pydantic v2, PyMuPDF, `python-multipart`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-mu-onboarding-settings-design.md`. It **depends on plan `2026-10-08-mu-accounts-auth.md` being fully built** (users, sessions, guards, `client_as`/`anon_client`/`seeded_two` fixtures, `Budget`/`Limit`, the migrate framework with v1, `OWNER_ID`, `owner_first_name`).

## Global Constraints

- Test commands: `FORCE_COLOR= uv run pytest --color=no` (never `-q`). Node: `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`.
- **Every task ends with the full suite green:** pytest, with the count never falling below plan 2's final count, **and** 19 node tests. The app works for the owner (migrated and onboarded) after every task.
- Migration number **v2** (v3 = extras, v4 = pipeline, v5 = outreach register later). `jobseeker migrate` has **no `--import` flag**: v2 reads `$JOBSEEKER_HOME/profile/`.
- Role catalog seed: Product Analyst, Associate Product Manager, Product Manager, Founder's Office, Growth Analyst, Business Analyst, Data Analyst, Program Manager, Strategy & Ops. **One** custom role per user.
- Resume: PDF only; ≤ 5 MB; ≤ 10 pages; ≥ 300 characters of text; stored at `data/users/<id>/resume.pdf` (dir 700, file 600).
- Facts budget: `groq:facts`, 3 per user per day, plus `facts_per_day: 10` globally. The day is the IST date (`ZoneInfo("Asia/Kolkata")`; spec 4 adds `tzdata`).
- Thresholds and `min_prescore` stay global (in `AppConfig`).
- Settings is the **4th tab**, in both the sidebar and the phone tab bar.
- Delete-confirmation copy: "Type your email to confirm. Shared job listings stay. Backups keep copies for up to 4 weeks."
- No hard-coded owner name. No personal values in test fixtures.
- Commits: one per task on `multi-user`, staging only that task's files. Message trailer:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2
  ```
  Don't push.
- Work in the worktree `/Users/user/Desktop/untitled folder/js-mu-backend`, never in the main checkout (which runs the live app on `main`).

## Review Focus

1. **The owner's existing preferences after v2:** filter and score inputs must be identical (golden test, Task 2). An unmatched `search.queries` entry must not silently disappear: it becomes `custom_role` or `title_allow_extra`.
2. **A partially onboarded user hitting any app URL** (bookmark, back button, HTMX request): they go to their step and never see a 500 or an empty-prefs crash (Task 4).
3. **Uploads that look like PDFs but aren't:** wrong magic bytes, a corrupt file, image-only or scanned, 11 pages, 5.1 MB. Each gets its friendly message, and nothing is stored (Task 6).
4. **Loosening a preference** must bring hidden jobs back, while jobs the user already scored are never hidden by a low pre-score (Task 5).
5. **Delete account** must remove every per-user row in every table, including tables added later, and never touch another user's rows (Task 8, table-walk test).

---

## File structure

| File | Responsibility |
|---|---|
| `config/app.example.yaml` (new, in git) | the documented default `AppConfig`, including the role catalog seed |
| `src/jobseeker/config.py` | `UserPrefs`, `AppConfig`, `Role`, `load_app_config`, `effective_prefs`, `Preferences` (optional CTC); checkout paths |
| `src/jobseeker/db/migrations.py` | `migrate_v2`, registered as v2 |
| `src/jobseeker/profile/importer.py` (new) | `import_profile(conn, user_id, profile_dir, home, now) -> list[str]` (used by v2 and the test fixtures) |
| `src/jobseeker/db/profile.py` (new) | user prefs and facts repository: `get_user_prefs`, `save_user_prefs`, `set_onboarding`, `get_facts`, `save_facts`, `claim_extract`, `set_extract_status`, `facts_state` |
| `src/jobseeker/profile/facts.py` | `extract_facts(llm, text, model)` (pure) |
| `src/jobseeker/profile/resume.py` | `validate_pdf(data: bytes) -> str` (text) or `ResumeRejected`; `resume_path(home, user_id)`; `store_resume` |
| `src/jobseeker/profile/extract.py` (new) | `run_extract(db_path, home, user_id, settings, app_config)` background task |
| `src/jobseeker/pipeline/evaluate.py` (new) | `verdict(...)`, `reevaluate(...) -> Report` (replaces `pipeline/refilter.py`) |
| `src/jobseeker/web/deps.py` | `current_prefs`, `require_onboarded` |
| `src/jobseeker/web/onboarding.py` (new) | `/onboarding/*` |
| `src/jobseeker/web/settings.py` (new) | `/settings*`, export, delete |
| `src/jobseeker/web/templates/onboarding/*.html`, `settings.html`, `_prefs_*.html`, `_facts_form.html`, `_resume_status.html` (new) | the UI |
| `tests/fixtures/preferences.yaml`, `tests/fixtures/facts.json` (new) | non-personal owner fixtures |

---

### Task 1: `UserPrefs`, `AppConfig`, `effective_prefs`, non-personal fixtures

**Files:**
- Create: `config/app.example.yaml`, `tests/fixtures/preferences.yaml`
- Modify: `src/jobseeker/config.py` (new models; `Preferences.current_ctc_lpa`/`target_base_lpa` become optional; `Settings` gains `app_config_path`)
- Modify: `src/jobseeker/scoring/scorer.py:36` ("not given")
- Modify: `tests/conftest.py:16-22` (`home` copies the fixture instead of the real file), plus the 4 tests that asserted personal values: `tests/test_drafter.py:36`, `tests/test_web_redesign.py:61, 73`, `tests/test_web_application.py:175`
- Test: `tests/test_config.py` (append)

**Interfaces:**
- Produces:
  - `Role(label: str, query: str, allow: list[str])`;
  - `UserPrefs` (fields exactly as spec 3 §4.1, plus `notify_new_matches: bool = True`), with `.complete() -> list[str]` (missing-step names, in step order);
  - `AppConfig` (with `.roles`, `.cities`, `.default_title_deny`, `.models`, `.thresholds`, `.min_prescore`, `.search`, `.contacts`, `.budgets: AppBudgets`, `.companies_path`, `.rubric_path`), and `AppBudgets(score_per_run, draft_per_run, facts_per_user_per_day=3, facts_per_day=10)`;
  - `load_app_config(path: Path) -> AppConfig`, `REPO_ROOT: Path`;
  - `effective_prefs(up: UserPrefs, cfg: AppConfig, name: str, email: str) -> Preferences`.

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/preferences.yaml`: today's `profile/preferences.yaml` with every personal value replaced:
- `name: Asha Owner`, `email: owner@example.com`, `linkedin: https://www.linkedin.com/in/asha-owner/`, `github: ""`;
- `experience_summary: ~1.3 years as a Product Analyst plus a 3-month consulting internship. B.Tech EE (2025).`;
- `current_ctc_lpa: 20`, `target_base_lpa: 25`.

Everything else (roles, cities, title lists, thresholds, budgets, `search:`, `contacts:` minus `sender_email`) is copied verbatim.

`config/app.example.yaml`:
```yaml
# Server-wide settings. Copy to $JOBSEEKER_HOME/config/app.yaml (migration v2 writes it for you on first run).
models: {scoring: openai/gpt-oss-20b, drafting: openai/gpt-oss-120b, facts: openai/gpt-oss-120b}
thresholds: {apply: 70, review: 50}
min_prescore: 30
budgets: {score_per_run: 80, draft_per_run: 10, facts_per_user_per_day: 3, facts_per_day: 10}
search: {hours_old: 72, results_per_search: 25, sites: [linkedin, naukri, indeed], linkedin_descriptions_per_run: 15}
contacts: {tavily_monthly_limit: 950, apify_monthly_usd_limit: 4.5, hunter_monthly_limit: 45, smtp_daily_limit: 60}
default_title_deny: [sales, sde, software engineer, intern, internship, director, head of, vp, vice president,
                     account executive, recruiter]
cities: [Bengaluru, Gurgaon, Noida, Pune, Mumbai, Hyderabad, Chennai, Delhi]
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
```
(`default_title_deny` must be the exact list in today's `profile/preferences.yaml:22-24`; copy it from there when implementing.)

- [ ] **Step 2: Write the failing tests** (append to `tests/test_config.py`):

```python
from jobseeker.config import REPO_ROOT, AppConfig, UserPrefs, effective_prefs, load_app_config


def _cfg():
    return load_app_config(REPO_ROOT / "config" / "app.example.yaml")


def test_app_config_loads_catalog_and_checkout_paths():
    cfg = _cfg()
    assert [r.label for r in cfg.roles][:2] == ["Product Analyst", "Associate Product Manager"]
    assert len(cfg.roles) == 9
    assert cfg.companies_path == REPO_ROOT / "companies.yaml" and cfg.rubric_path == REPO_ROOT / "rubric.yaml"


def test_effective_prefs_maps_roles_and_defaults():
    up = UserPrefs(roles=["Product Analyst", "Founder's Office"], custom_role="Chief of Staff", cities=["Pune"],
                   experience_years=1.3, drop_if_min_years_at_least=2.5, experience_summary="x")
    p = effective_prefs(up, _cfg(), name="A B", email="a@example.com")
    assert p.target_roles == ["Product Analyst", "Founder's Office", "Chief of Staff"]
    assert set(p.title_allow) >= {"product", "analyst", "founder", "chief of staff"}
    assert p.search.queries == ["Product Analyst", "Founder's Office", "Chief of Staff"]
    assert p.title_deny == _cfg().default_title_deny
    assert p.current_ctc_lpa is None and p.min_prescore == 30 and p.name == "A B"


def test_complete_lists_missing_steps_in_order():
    assert UserPrefs().complete() == ["roles", "where", "experience"]
    up = UserPrefs(roles=["Product Analyst"], remote_india_ok=True, drop_if_min_years_at_least=2.5,
                   experience_summary="x")
    assert up.complete() == []
    assert UserPrefs(roles=["x"], experience_years=3, drop_if_min_years_at_least=2.5,
                     experience_summary="x").complete() == ["experience"]  # threshold must exceed years


def test_scorer_prompt_says_not_given_for_missing_ctc(facts, rubric, prefs):
    from jobseeker.scoring.scorer import _system
    text = _system(facts, prefs.model_copy(update={"current_ctc_lpa": None, "target_base_lpa": None}), rubric)
    assert "CTC not given" in text
```

- [ ] **Step 3: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_config.py` → FAIL (ImportError: `REPO_ROOT`).

- [ ] **Step 4: Implement** (`src/jobseeker/config.py`):

```python
REPO_ROOT = Path(__file__).resolve().parents[2]  # the code checkout (…/src/jobseeker/config.py → repo root)


class Role(BaseModel):
    label: str
    query: str
    allow: list[str] = []


class AppBudgets(BaseModel):
    score_per_run: int = 80
    draft_per_run: int = 10
    facts_per_user_per_day: int = 3
    facts_per_day: int = 10


class AppSearch(BaseModel):
    hours_old: int = 72
    results_per_search: int = 25
    sites: list[Literal["linkedin", "naukri", "indeed"]] = ["linkedin", "naukri", "indeed"]
    linkedin_descriptions_per_run: int = 15


class AppConfig(BaseModel):
    models: Models = Models()
    thresholds: Thresholds = Thresholds()
    min_prescore: int = 30
    budgets: AppBudgets = AppBudgets()
    search: AppSearch = AppSearch()
    contacts: ContactsConfig = ContactsConfig()
    default_title_deny: list[str] = []
    cities: list[str] = []
    roles: list[Role] = []
    companies_path: Path = REPO_ROOT / "companies.yaml"
    rubric_path: Path = REPO_ROOT / "rubric.yaml"


def load_app_config(path: Path | str) -> AppConfig:
    return AppConfig.model_validate(_yaml(path))


LIST_MAX, ITEM_MAX = 10, 60


class UserPrefs(BaseModel):
    roles: list[str] = []
    custom_role: str = ""
    cities: list[str] = []
    remote_india_ok: bool = True
    experience_years: float | None = None
    drop_if_min_years_at_least: float | None = None
    max_age_days: int = 7
    current_ctc_lpa: float | None = None
    target_base_lpa: float | None = None
    must_haves: list[str] = []
    deal_breakers: list[str] = []
    title_deny: list[str] | None = None
    title_allow_extra: list[str] = []
    experience_summary: str = ""
    linkedin: str = ""
    github: str = ""
    notify_new_matches: bool = True
    target_roles_text: list[str] = []  # how the scorer describes the target roles; empty = the role picks (import keeps the owner's prose)

    def complete(self) -> list[str]:
        """The onboarding steps still missing something, in step order (an empty list means complete)."""
        missing = []
        if not (self.roles or self.custom_role.strip()):
            missing.append("roles")
        if not (self.cities or self.remote_india_ok):
            missing.append("where")
        t = self.drop_if_min_years_at_least
        if t is None or (self.experience_years is not None and t <= self.experience_years) \
                or not self.experience_summary.strip():
            missing.append("experience")
        return missing


def effective_prefs(up: UserPrefs, cfg: AppConfig, name: str, email: str) -> Preferences:
    by_label = {r.label: r for r in cfg.roles}
    roles = [by_label[x] for x in up.roles if x in by_label]
    custom = up.custom_role.strip()
    if up.title_allow_extra:  # explicit list (the migrated owner): used as is, so their matches never widen
        allow = up.title_allow_extra + ([custom.lower()] if custom else [])
    else:
        allow = [w for r in roles for w in r.allow] + ([custom.lower()] if custom else [])
    return Preferences(
        name=name, email=email, linkedin=up.linkedin, github=up.github,
        experience_summary=up.experience_summary,
        target_roles=up.target_roles_text or [r.label for r in roles] + ([custom] if custom else []),
        cities=up.cities, remote_india_ok=up.remote_india_ok,
        current_ctc_lpa=up.current_ctc_lpa, target_base_lpa=up.target_base_lpa,
        must_haves=up.must_haves, deal_breakers=up.deal_breakers,
        title_deny=up.title_deny if up.title_deny is not None else cfg.default_title_deny,
        title_allow=list(dict.fromkeys(allow)),
        drop_if_min_years_at_least=up.drop_if_min_years_at_least or 8, max_age_days=up.max_age_days,
        thresholds=cfg.thresholds, min_prescore=cfg.min_prescore, models=cfg.models,
        budgets=Budgets(score_per_run=cfg.budgets.score_per_run, draft_per_run=cfg.budgets.draft_per_run),
        search=SearchConfig(queries=[r.query for r in roles] + ([custom] if custom else []),
                            locations=up.cities, remote_query=up.remote_india_ok, hours_old=cfg.search.hours_old,
                            results_per_search=cfg.search.results_per_search, sites=cfg.search.sites,
                            linkedin_descriptions_per_run=cfg.search.linkedin_descriptions_per_run),
        contacts=cfg.contacts.model_copy(update={"sender_email": email}),
    )
```
`Preferences.current_ctc_lpa: float | None = None` and `target_base_lpa: float | None = None` (`config.py:124-125`). `Settings` gains `app_config_path` as a property: `self.jobseeker_home / "config" / "app.yaml"`.

`src/jobseeker/scoring/scorer.py:36`:
```python
- {"CTC not given" if prefs.current_ctc_lpa is None else f"Current CTC {prefs.current_ctc_lpa} LPA"}; {"target base not given" if prefs.target_base_lpa is None else f"target base {prefs.target_base_lpa} LPA"}
```
(For the owner with both values set, the line renders exactly as before: `Current CTC 20.7 LPA; target base 25 LPA`.)

`tests/conftest.py:19`: `shutil.copy(ROOT / "tests" / "fixtures" / "preferences.yaml", tmp_path / "profile" / "preferences.yaml")`.

Personal-value tests:
- `tests/test_drafter.py:36` → `.endswith("https://www.linkedin.com/in/asha-owner/")`;
- `tests/test_web_redesign.py:61, 73` → `Asha`;
- `tests/test_web_application.py:175` → `"Asha Owner"`.

Also run `grep -rn "Kshitij\|mkshitij\|kshitijmeshram" tests/*.py` and fix any other hit that reads the prefs fixture. Hits inside literal draft texts (`test_drafter.py:7-8`, `test_web_contacts.py:111-114`, `test_profile.py:10`, `test_gmail.py:19-23`) are test data, not prefs; leave them.

- [ ] **Step 5: Run the suites** (pytest all pass; node 19)

- [ ] **Step 6: Commit**

```bash
git add config/app.example.yaml tests/fixtures/preferences.yaml src/jobseeker/config.py src/jobseeker/scoring/scorer.py \
        tests/conftest.py tests/test_config.py tests/test_drafter.py tests/test_web_redesign.py tests/test_web_application.py
git commit -m "feat(config): UserPrefs, AppConfig with role catalog, effective_prefs; non-personal fixtures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 2: Migration v2 and the profile importer

**Files:**
- Create: `src/jobseeker/profile/importer.py`, `tests/fixtures/facts.json`. Generate it from the conftest fixture: copy the `Facts(...)` literal from `tests/conftest.py:42-56` into a one-off `uv run python -c` that writes `json.dumps({"resume_sha256": "fixture", "facts": Facts(...).model_dump()}, indent=2)`.
- Modify: `src/jobseeker/db/migrations.py` (`V2_DDL`, `migrate_v2`, register v2)
- Modify: `src/jobseeker/db/schema.sql` (add `user_prefs`, `user_facts`)
- Modify: `src/jobseeker/db/core.py` (`_seed_fresh` also inserts `user_prefs(1)`)
- Modify: `src/jobseeker/db/users.py:resolve_sign_in` (a new user gets a `user_prefs` row)
- Modify: `tests/conftest.py` (`settings` imports the fixture profile for user 1)
- Test: `tests/test_migrations.py` (append), `tests/test_importer.py` (new)

**Interfaces:**
- Consumes: `UserPrefs`, `AppConfig`, `load_preferences`, `effective_prefs` (Task 1); the migrate framework (plan 2).
- Produces:
  - `import_profile(conn, user_id: int, profile_dir: Path, home: Path, now: datetime) -> list[str]` (report lines; raises `MigrationError` on the golden mismatch);
  - `golden_fields(p: Preferences) -> dict`;
  - `migrate_v2(conn, ctx)`;
  - `USER_PREFS_VERSION = 1`.

- [ ] **Step 1: Write the failing tests** (`tests/test_importer.py`):

```python
import json
import shutil
from datetime import UTC, datetime

from jobseeker.config import UserPrefs, load_preferences
from jobseeker.db.core import connect
from jobseeker.profile.importer import golden_fields, import_profile

ROOT_FIX = __import__("pathlib").Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _profile(tmp_path, with_resume=True):
    prof = tmp_path / "profile"
    prof.mkdir()
    shutil.copy(ROOT_FIX / "preferences.yaml", prof / "preferences.yaml")
    shutil.copy(ROOT_FIX / "facts.json", prof / "facts.json")
    if with_resume:
        (prof / "resume.pdf").write_bytes(b"%PDF-1.4 fixture")
    return prof


def test_import_owner_is_golden_and_onboarded(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    report = import_profile(conn, 1, _profile(tmp_path), tmp_path, NOW)
    row = conn.execute("SELECT * FROM user_prefs WHERE user_id = 1").fetchone()
    assert row["onboarded_at"] and json.loads(row["data"])["roles"]
    assert conn.execute("SELECT name FROM users WHERE id = 1").fetchone()[0] == "Asha Owner"
    assert conn.execute("SELECT edited FROM user_facts WHERE user_id = 1").fetchone()[0] == 1
    resume = tmp_path / "data" / "users" / "1" / "resume.pdf"
    assert resume.read_bytes().startswith(b"%PDF") and oct(resume.stat().st_mode)[-3:] == "600"
    assert (tmp_path / "config" / "app.yaml").exists()
    assert any("imported" in line for line in report)


def test_golden_fields_match_original(tmp_path):
    from jobseeker.db.profile import get_user_prefs
    conn = connect(tmp_path / "db.sqlite")
    import_profile(conn, 1, _profile(tmp_path), tmp_path, NOW)
    from jobseeker.config import effective_prefs, load_app_config
    eff = effective_prefs(get_user_prefs(conn, 1), load_app_config(tmp_path / "config" / "app.yaml"),
                          "Asha Owner", "owner@example.com")
    assert golden_fields(eff) == golden_fields(load_preferences(ROOT_FIX / "preferences.yaml"))


def test_existing_app_yaml_is_not_overwritten(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.yaml").write_text("min_prescore: 99\n")
    import_profile(connect(tmp_path / "db.sqlite"), 1, _profile(tmp_path), tmp_path, NOW)
    assert (tmp_path / "config" / "app.yaml").read_text() == "min_prescore: 99\n"


def test_unmatched_query_becomes_custom_role(tmp_path):
    prof = _profile(tmp_path)
    text = (prof / "preferences.yaml").read_text().replace("queries: [", "queries: [Chief of Staff, ")
    (prof / "preferences.yaml").write_text(text)
    conn = connect(tmp_path / "db.sqlite")
    import_profile(conn, 1, prof, tmp_path, NOW)
    from jobseeker.db.profile import get_user_prefs
    assert get_user_prefs(conn, 1).custom_role == "Chief of Staff"
```
Append to `tests/test_migrations.py`:
```python
def test_v2_imports_profile_and_reruns_as_noop(tmp_path):
    import shutil
    db = live_like_v0(tmp_path / "db.sqlite")
    prof = tmp_path / "profile"
    prof.mkdir()
    shutil.copy("tests/fixtures/preferences.yaml", prof / "preferences.yaml")
    shutil.copy("tests/fixtures/facts.json", prof / "facts.json")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk")
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] >= 2
    assert c.execute("SELECT onboarded_at IS NOT NULL FROM user_prefs WHERE user_id = 1").fetchone()[0] == 1
    assert m.migrate(db, _ctx(tmp_path), tmp_path / "bk")[0].startswith("Already at")


def test_v2_without_profile_leaves_owner_unonboarded(tmp_path):
    db = live_like_v0(tmp_path / "db.sqlite")
    m.migrate(db, _ctx(tmp_path), tmp_path / "bk")
    c = sqlite3.connect(db)
    assert c.execute("SELECT onboarded_at, onboarding_step FROM user_prefs WHERE user_id = 1").fetchone() == (None, "roles")
    assert (tmp_path / "config" / "app.yaml").exists()
```
- [ ] **Step 2: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_importer.py tests/test_migrations.py` → FAIL (ImportError).

- [ ] **Step 3: Implement**

`V2_DDL` (in `migrations.py`; also appended, with `IF NOT EXISTS`, to `schema.sql`):
```sql
CREATE TABLE user_prefs (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  data TEXT NOT NULL,
  version INTEGER NOT NULL,
  onboarding_step TEXT,
  onboarded_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE user_facts (
  user_id INTEGER PRIMARY KEY REFERENCES users (id),
  resume_sha256 TEXT,
  facts TEXT,
  edited INTEGER NOT NULL DEFAULT 0,
  extract_status TEXT NOT NULL DEFAULT 'idle' CHECK (extract_status IN ('idle', 'running', 'done', 'failed')),
  extract_error TEXT NOT NULL DEFAULT '',
  extract_started_at TEXT,
  resume_uploaded_at TEXT,
  updated_at TEXT NOT NULL
);
```

`src/jobseeker/profile/importer.py`:
```python
"""Owner import for migration v2 (and the test fixtures): preferences.yaml, facts.json, resume.pdf → the DB."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

from jobseeker.config import REPO_ROOT, Preferences, UserPrefs, effective_prefs, load_app_config, load_preferences
from jobseeker.db.core import iso
from jobseeker.db.migrations import MigrationError

GLOBAL_KEYS = ("models", "thresholds", "min_prescore", "contacts")


def golden_fields(p: Preferences) -> dict:
    """Every field prefilter, prescore and score_job read."""
    return {"title_allow": sorted(x.lower() for x in p.title_allow), "title_deny": sorted(p.title_deny),
            "cities": sorted(p.cities), "remote": p.remote_india_ok, "years": p.drop_if_min_years_at_least,
            "max_age": p.max_age_days, "summary": p.experience_summary, "roles": sorted(p.target_roles),
            "ctc": (p.current_ctc_lpa, p.target_base_lpa), "must": p.must_haves, "deal": p.deal_breakers,
            "min_prescore": p.min_prescore, "thresholds": p.thresholds.model_dump()}


def _write_app_yaml(home: Path, prefs: Preferences | None) -> Path:
    path = home / "config" / "app.yaml"
    if path.exists():
        return path
    data = yaml.safe_load((REPO_ROOT / "config" / "app.example.yaml").read_text(encoding="utf-8"))
    if prefs is not None:
        data.update({k: getattr(prefs, k).model_dump() if hasattr(getattr(prefs, k), "model_dump") else getattr(prefs, k)
                     for k in GLOBAL_KEYS})
        data["contacts"].pop("sender_email", None)
        data["budgets"].update({"score_per_run": prefs.budgets.score_per_run, "draft_per_run": prefs.budgets.draft_per_run})
        data["search"].update({k: getattr(prefs.search, k) for k in ("hours_old", "results_per_search", "sites",
                                                                     "linkedin_descriptions_per_run")})
        data["default_title_deny"] = prefs.title_deny
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _user_prefs_from(prefs: Preferences, labels_by_query: dict[str, str]) -> UserPrefs:
    roles, unmatched = [], []
    for q in prefs.search.queries:
        (roles.append(labels_by_query[q]) if q in labels_by_query else unmatched.append(q))
    return UserPrefs(roles=roles, custom_role=unmatched[0] if unmatched else "", cities=prefs.cities,
                     remote_india_ok=prefs.remote_india_ok, drop_if_min_years_at_least=prefs.drop_if_min_years_at_least,
                     max_age_days=prefs.max_age_days, current_ctc_lpa=prefs.current_ctc_lpa,
                     target_base_lpa=prefs.target_base_lpa, must_haves=prefs.must_haves,
                     deal_breakers=prefs.deal_breakers, title_deny=prefs.title_deny,
                     title_allow_extra=prefs.title_allow + [w.lower() for w in unmatched[1:]],
                     target_roles_text=prefs.target_roles,
                     experience_summary=prefs.experience_summary, linkedin=prefs.linkedin, github=prefs.github)


def import_profile(conn: sqlite3.Connection, user_id: int, profile_dir: Path, home: Path, now: datetime) -> list[str]:
    ts = iso(now)
    pref_file = profile_dir / "preferences.yaml"
    prefs = load_preferences(pref_file) if pref_file.exists() else None
    cfg = load_app_config(_write_app_yaml(home, prefs))
    report = []
    if prefs is None:
        conn.execute("""INSERT OR IGNORE INTO user_prefs (user_id, data, version, onboarding_step, updated_at)
                        VALUES (?, '{}', 1, 'roles', ?)""", (user_id, ts))
        return ["no profile/preferences.yaml: the owner will onboard like anyone else"]
    up = _user_prefs_from(prefs, {r.query: r.label for r in cfg.roles})
    eff = effective_prefs(up, cfg, prefs.name, prefs.email)
    if golden_fields(eff) != golden_fields(prefs):
        diff = {k: (golden_fields(prefs)[k], v) for k, v in golden_fields(eff).items() if golden_fields(prefs)[k] != v}
        raise MigrationError(f"v2 golden check failed (original, imported): {diff}")
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (?, ?, 1, NULL, ?, ?)
                    ON CONFLICT (user_id) DO UPDATE SET data = excluded.data, onboarding_step = NULL,
                      onboarded_at = excluded.onboarded_at, updated_at = excluded.updated_at""",
                 (user_id, up.model_dump_json(), ts, ts))
    conn.execute("UPDATE users SET name = ? WHERE id = ? AND name = ''", (prefs.name, user_id))
    report.append("imported preferences.yaml")
    facts_file = profile_dir / "facts.json"
    if facts_file.exists():
        data = json.loads(facts_file.read_text(encoding="utf-8"))
        conn.execute("""INSERT OR REPLACE INTO user_facts (user_id, resume_sha256, facts, edited, extract_status,
                        updated_at) VALUES (?, ?, ?, 1, 'done', ?)""",
                     (user_id, data.get("resume_sha256"), json.dumps(data["facts"]), ts))
        report.append("imported facts.json")
    resume = profile_dir / "resume.pdf"
    if resume.exists():
        dest_dir = home / "data" / "users" / str(user_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(dest_dir, 0o700)
        shutil.copyfile(resume, dest_dir / "resume.pdf")
        os.chmod(dest_dir / "resume.pdf", 0o600)
        conn.execute("UPDATE user_facts SET resume_uploaded_at = ? WHERE user_id = ?", (ts, user_id))
        report.append("imported resume.pdf")
    return report
```
**Golden check note:** the owner's `title_allow` survives verbatim through `title_allow_extra` (Task 1's rule: an explicit list is used as is), and `target_roles` through `target_roles_text`. `golden_fields` therefore compares equal without special cases. Add a test in `tests/test_config.py`: an owner-style `UserPrefs(title_allow_extra=["product"], roles=["Data Analyst"])` gives `title_allow == ["product"]`.

`migrate_v2(conn, ctx)`: execute `V2_DDL`, then `import_profile(conn, 1, ctx.home / "profile", ctx.home, ctx.now)`, and register `Migration(2, "preferences, facts and resume", migrate_v2)` after v1.

`core._seed_fresh` adds:
```python
conn.execute("INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (1, '{}', 1, 'roles', ?)",
             (utcnow(),))
```
`users.resolve_sign_in`: after inserting a new user, `INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (?, '{}', 1, 'roles', ?)` in the same transaction.

`tests/conftest.py`, `settings` fixture:
```python
@pytest.fixture
def settings(home: Path) -> Settings:
    from datetime import UTC, datetime

    from jobseeker.profile.importer import import_profile
    s = Settings(jobseeker_home=home, groq_api_key="test", **AUTH_TEST)
    shutil.copy(ROOT / "tests" / "fixtures" / "facts.json", home / "profile" / "facts.json")
    conn = connect(s.db_path)
    import_profile(conn, 1, home / "profile", home, datetime.now(UTC))
    conn.commit()
    conn.close()
    return s
```
`seeded_two` (plan 2) also inserts `user_prefs` for user 2, with `onboarded_at` set and `data` = `UserPrefs(roles=["Growth Analyst"], cities=["Pune"], drop_if_min_years_at_least=5, experience_summary="x").model_dump_json()`.

- [ ] **Step 4: Run the suites** (pytest all pass; node 19). Then repeat plan 2 Task 11 Step 3's live-copy migrate with a copied `profile/` in `/tmp/jsacc/profile/`, and check that the golden check passes on the **real** owner preferences.

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/profile/importer.py src/jobseeker/db/migrations.py src/jobseeker/db/schema.sql src/jobseeker/db/core.py \
  src/jobseeker/db/users.py src/jobseeker/config.py tests/fixtures/facts.json tests/conftest.py tests/test_importer.py \
  tests/test_migrations.py tests/test_config.py
git commit -m "feat(db): migration v2 imports the owner's preferences, facts and resume (golden-checked)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018oboXgS38zr1eKtnKy4WF2"
```

---

### Task 3: Request-scoped preferences; facts read from the DB

**Files:**
- Create: `src/jobseeker/db/profile.py`
- Modify: `src/jobseeker/profile/facts.py` (keep `Facts`, `FACTS_SYSTEM`; add `extract_facts`; delete `load_facts`, `load_or_build_facts`)
- Modify: `src/jobseeker/web/deps.py` (`current_prefs`, `current_facts`)
- Modify: `src/jobseeker/web/app.py:54-60` (`app.state.app_config`; remove `app.state.prefs`; `llm_factory` fallbacks from `app_config`; `rubric_path` from `app_config`)
- Modify: `src/jobseeker/web/application.py:45, 115-116, 190-196`, `src/jobseeker/web/contacts.py:33, 50`
- Modify: `src/jobseeker/cli.py` (`load_user_context`; `init` no longer builds facts; `--user` on `run`/`rescore`/`refilter`)
- Modify: `src/jobseeker/config.py` (remove `Settings.resume_path`, `facts_path`, `preferences_path`, `companies_path`, `rubric_path`)
- Modify tests: `tests/test_profile.py`, `tests/test_config.py:31` (`test_settings_paths`), `tests/conftest.py` (`prefs`/`rubric` fixtures load from the fixture file and `app_config.rubric_path`), plus every `settings.facts_path`/`resume_path` use (`grep -rn "facts_path\|resume_path\|preferences_path" tests src`)
- Test: `tests/test_profile_repo.py` (new)

**Interfaces:**
- Consumes: `import_profile`, `UserPrefs`, `AppConfig`, `effective_prefs` (Tasks 1-2).
- Produces:
  - `get_user_prefs(conn, user_id) -> UserPrefs`, `save_user_prefs(conn, user_id, up: UserPrefs, now)`;
  - `get_onboarding(conn, user_id) -> tuple[str | None, str | None]` (step, onboarded_at), `set_onboarding(conn, user_id, step: str | None, onboarded_at: str | None, now)`;
  - `get_facts(conn, user_id) -> Facts | None`, `save_facts(conn, user_id, sha: str | None, facts: Facts, edited: bool, now)`, `facts_row(conn, user_id) -> dict | None`;
  - `claim_extract(conn, user_id, now) -> bool`, `set_extract_status(conn, user_id, status, note="")`;
  - `load_user_context(conn, user_id, app_config) -> tuple[Preferences, Facts | None]` (in `db/profile.py`);
  - `current_prefs(request, user, conn) -> Preferences`, `current_facts(user, conn) -> Facts | None`;
  - `extract_facts(llm, text, model) -> Facts`;
  - `resume_path(home: Path, user_id: int) -> Path` (in `profile/resume.py`).

- [ ] **Step 1: Write the failing tests** (`tests/test_profile_repo.py`):

```python
from datetime import UTC, datetime

from jobseeker.config import UserPrefs
from jobseeker.db.core import connect
from jobseeker.db.profile import (claim_extract, get_facts, get_user_prefs, load_user_context, save_facts,
                                  save_user_prefs)
from jobseeker.profile.facts import extract_facts
from tests.fakes import FakeLLM

T = datetime(2026, 10, 8, tzinfo=UTC)


def test_prefs_roundtrip(settings):
    conn = connect(settings.db_path)
    save_user_prefs(conn, 1, UserPrefs(roles=["Data Analyst"], cities=["Pune"]), T)
    assert get_user_prefs(conn, 1).roles == ["Data Analyst"]


def test_facts_roundtrip_and_claim(settings, facts):
    conn = connect(settings.db_path)
    save_facts(conn, 1, "sha", facts, edited=False, now=T)
    assert get_facts(conn, 1) == facts
    assert claim_extract(conn, 1, T) is True
    assert claim_extract(conn, 1, T) is False          # already running
    assert claim_extract(conn, 1, T.replace(hour=1)) is True  # 20-min stale claim taken over


def test_load_user_context_builds_effective_prefs(settings, app_config):
    prefs, facts = load_user_context(connect(settings.db_path), 1, app_config)
    assert prefs.name == "Asha Owner" and facts is not None


def test_extract_facts_is_pure(facts):
    llm = FakeLLM([facts])
    assert extract_facts(llm, "resume text 67%", "m") == facts
    assert "resume text 67%" in llm.calls[0]["prompt"]


def test_current_prefs_reads_fresh_each_request(settings, app_config):
    from types import SimpleNamespace

    from jobseeker.db.users import user_by_id
    from jobseeker.web.deps import current_prefs
    conn = connect(settings.db_path)
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_config=app_config)))
    up = get_user_prefs(conn, 1)
    save_user_prefs(conn, 1, up.model_copy(update={"linkedin": "https://www.linkedin.com/in/changed/"}), T)
    assert current_prefs(req, user_by_id(conn, 1), conn).linkedin == "https://www.linkedin.com/in/changed/"
```
Add an `app_config` fixture to `tests/conftest.py`: `load_app_config(settings.app_config_path)`.

- [ ] **Step 2: Run them and watch them fail**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_profile_repo.py` → FAIL (ImportError).

- [ ] **Step 3: Implement**

`src/jobseeker/db/profile.py`:
```python
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from jobseeker.config import AppConfig, Preferences, UserPrefs, effective_prefs
from jobseeker.db.core import iso
from jobseeker.profile.facts import Facts

STALE_EXTRACT = timedelta(minutes=20)


def get_user_prefs(conn: sqlite3.Connection, user_id: int) -> UserPrefs:
    row = conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return UserPrefs.model_validate_json(row["data"]) if row else UserPrefs()


def save_user_prefs(conn: sqlite3.Connection, user_id: int, up: UserPrefs, now: datetime) -> None:
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (?, ?, 1, 'roles', ?)
                    ON CONFLICT (user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",
                 (user_id, up.model_dump_json(), iso(now)))
    conn.commit()


def get_onboarding(conn, user_id: int) -> tuple[str | None, str | None]:
    row = conn.execute("SELECT onboarding_step, onboarded_at FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    return (row["onboarding_step"], row["onboarded_at"]) if row else ("roles", None)


def set_onboarding(conn, user_id: int, step: str | None, onboarded_at: str | None, now: datetime) -> None:
    conn.execute("UPDATE user_prefs SET onboarding_step = ?, onboarded_at = ?, updated_at = ? WHERE user_id = ?",
                 (step, onboarded_at, iso(now), user_id))
    conn.commit()


def facts_row(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM user_facts WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_facts(conn, user_id: int) -> Facts | None:
    row = facts_row(conn, user_id)
    return Facts.model_validate(json.loads(row["facts"])) if row and row["facts"] else None


def save_facts(conn, user_id: int, sha: str | None, facts: Facts, edited: bool, now: datetime) -> None:
    conn.execute("""INSERT INTO user_facts (user_id, resume_sha256, facts, edited, extract_status, updated_at)
                    VALUES (?, ?, ?, ?, 'done', ?)
                    ON CONFLICT (user_id) DO UPDATE SET resume_sha256 = excluded.resume_sha256, facts = excluded.facts,
                      edited = excluded.edited, extract_status = 'done', extract_error = '', updated_at = excluded.updated_at""",
                 (user_id, sha, facts.model_dump_json(), int(edited), iso(now)))
    conn.commit()


def claim_extract(conn, user_id: int, now: datetime) -> bool:
    conn.execute("INSERT OR IGNORE INTO user_facts (user_id, updated_at) VALUES (?, ?)", (user_id, iso(now)))
    cur = conn.execute("""UPDATE user_facts SET extract_status = 'running', extract_error = '', extract_started_at = ?
                          WHERE user_id = ? AND (extract_status != 'running' OR extract_started_at < ?)""",
                       (iso(now), user_id, iso(now - STALE_EXTRACT)))
    conn.commit()
    return cur.rowcount == 1


def set_extract_status(conn, user_id: int, status: str, note: str = "") -> None:
    conn.execute("UPDATE user_facts SET extract_status = ?, extract_error = ? WHERE user_id = ?", (status, note, user_id))
    conn.commit()


def load_user_context(conn, user_id: int, cfg: AppConfig) -> tuple[Preferences, Facts | None]:
    user = conn.execute("SELECT name, email FROM users WHERE id = ?", (user_id,)).fetchone()
    return effective_prefs(get_user_prefs(conn, user_id), cfg, user["name"], user["email"]), get_facts(conn, user_id)
```

`src/jobseeker/profile/facts.py`: keep `Role`, `Achievement`, `Facts`, `FACTS_SYSTEM`; replace `_sha`/`load_facts`/`load_or_build_facts` with:
```python
def extract_facts(llm: LLM, text: str, model: str) -> Facts:
    return llm.json(model=model, system=FACTS_SYSTEM, prompt=f"<resume>\n{text}\n</resume>", schema=Facts,
                    effort="medium")
```

`src/jobseeker/profile/resume.py`: add `def resume_path(home: Path, user_id: int) -> Path: return home / "data" / "users" / str(user_id) / "resume.pdf"`.

`src/jobseeker/web/deps.py`:
```python
def current_prefs(request: Request, user: User = Depends(current_user), conn=Depends(get_conn)):
    from jobseeker.db.profile import load_user_context
    return load_user_context(conn, user.id, request.app.state.app_config)[0]


def current_facts(user: User = Depends(current_user), conn=Depends(get_conn)):
    from jobseeker.db.profile import get_facts
    return get_facts(conn, user.id)
```

`src/jobseeker/web/app.py`:
- `app.state.app_config = load_app_config(settings.app_config_path)` (a missing file → `RuntimeError("Run `jobseeker migrate` (with the owner's files in $JOBSEEKER_HOME/profile/), or copy config/app.example.yaml to config/app.yaml")`);
- `app.state.rubric = load_rubric(app.state.app_config.rubric_path)`;
- `llm_factory` uses `app.state.app_config.models.fallbacks`;
- delete `app.state.prefs`.

Routes:
- `web/application.py`:
  - `detail` takes `facts=Depends(current_facts)` and sets `terms = facts.skills if facts else []`;
  - `draft_now` takes `prefs=Depends(current_prefs), facts=Depends(current_facts)`; if `facts is None`, it returns `_back(app_id, err="No resume facts yet. Add your resume in Settings")`; otherwise it calls `draft_application(conn, app_id, state.llm_factory(), facts, prefs)`;
  - `_approve`/`_approve_single`/`_raw_for` take `prefs` and `user_id` arguments, threaded from the route: `approve(request, app_id, prefs=Depends(current_prefs), user=Depends(current_user), …)`. The attachment is `resume_path(state.settings.jobseeker_home, user_id)` if it exists.
- `web/contacts.py`: `card_context(request, conn, app_id, prefs)`, with `prefs` from `current_prefs` in each route that renders the card; `find` passes `prefs` to `run_find`. Update the `card_context` call in `web/application.py:detail` to pass `prefs` (add `prefs=Depends(current_prefs)` to `detail`).

`src/jobseeker/cli.py`:
- replace `_load()` with:
  ```python
  def _ctx(email: str | None):
      from jobseeker.config import load_app_config
      from jobseeker.db.profile import load_user_context
      from jobseeker.db.users import OWNER_ID, ensure_owner
      settings = Settings()
      cfg = load_app_config(settings.app_config_path)
      conn = connect(settings.db_path)
      ensure_owner(conn, settings.owner_email)
      uid = OWNER_ID if not email else conn.execute("SELECT id FROM users WHERE email = lower(?)", (email,)).fetchone()[0]
      prefs, facts = load_user_context(conn, uid, cfg)
      return settings, cfg, conn, uid, prefs, facts
  ```
- `run`, `rescore` and `refilter` take `user: str = typer.Option("", "--user")`. `_run` uses `load_companies(cfg.companies_path)`, `load_rubric(cfg.rubric_path)` and `run_daily(conn, user_id=uid, …)`; facts `None` exits 1 with "No resume facts for this user yet";
- `init` keeps only the folders and the DB.

`tests/test_profile.py`: delete the two `load_or_build_facts` tests (their behaviour moves to Task 6's extraction tests). Keep `test_extract_text`.

`tests/test_config.py:31` (`test_settings_paths`): assert `settings.app_config_path == home / "config" / "app.yaml"` and `settings.db_path == home / "data" / "jobseeker.db"`.

`tests/conftest.py`:
- `prefs` = `load_preferences(ROOT / "tests" / "fixtures" / "preferences.yaml")`;
- `rubric` = `load_rubric(REPO_ROOT / "rubric.yaml")`;
- every test that used `settings.companies_path`/`settings.rubric_path` uses `REPO_ROOT / …` (`grep -rn "companies_path\|rubric_path" tests`).

- [ ] **Step 4: Run the suites**, then `grep -rn "preferences_path\|facts_path\|resume_path\|load_facts\|app.state.prefs" src tests`. Expected: only `profile/resume.py:resume_path` and its callers.

- [ ] **Step 5: Commit** (the edited files by name; message `feat(profile): per-request preferences and DB facts replace app.state.prefs and profile files`, plus the trailer).

---

### Task 4: `require_onboarded` and onboarding steps 1-3

**Files:**
- Create: `src/jobseeker/web/onboarding.py`, `src/jobseeker/web/templates/onboarding/base_step.html`, `roles.html`, `where.html`, `experience.html`
- Create: `src/jobseeker/web/templates/_prefs_roles.html`, `_prefs_where.html`, `_prefs_experience.html` (field partials shared with Settings)
- Modify: `src/jobseeker/web/deps.py` (`require_onboarded`, `NotOnboarded`)
- Modify: `src/jobseeker/web/app.py` (include `onboarding.router`; add `require_onboarded` to the app routers; the `NotOnboarded` handler)
- Modify: `tests/test_web_guards.py` (the onboarding assertions)
- Test: `tests/test_onboarding.py` (new)

**Interfaces:**
- Consumes: `get_user_prefs`, `save_user_prefs`, `get_onboarding`, `set_onboarding` (Task 3); `UserPrefs` (Task 1).
- Produces:
  - `STEPS = ["roles", "where", "experience", "resume"]`, `parse_step(step, form, app_config) -> tuple[dict, dict[str, str]]` (fields, errors);
  - `require_onboarded(user=Depends(current_user), conn=Depends(get_conn)) -> User`;
  - the routes `GET/POST /onboarding/{step}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_onboarding.py`):

```python
import pytest

from jobseeker.db.core import connect
from jobseeker.db.profile import get_onboarding, get_user_prefs


@pytest.fixture
def newbie(settings):
    conn = connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, name, created_at) VALUES (3, 'new@example.com', 'New Person', 't')")
    conn.execute("INSERT INTO user_prefs (user_id, data, version, onboarding_step, updated_at) VALUES (3, '{}', 1, 'roles', 't')")
    conn.commit()
    return 3


def test_unonboarded_user_is_sent_to_their_step(newbie, client_as, seeded):
    web = client_as(newbie, follow_redirects=False)
    for path in ("/", "/today", "/pipeline", f"/applications/{seeded[0]}"):
        r = web.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/onboarding/roles", path
    hx = web.get("/today", headers={"HX-Request": "true"})
    assert hx.status_code == 401 and hx.headers["HX-Redirect"] == "/onboarding/roles"


def test_roles_step_validates_and_saves(newbie, client_as, settings):
    web = client_as(newbie, follow_redirects=False)
    bad = web.post("/onboarding/roles", data={})
    assert bad.status_code == 422 and "Pick at least one role" in bad.text
    assert web.post("/onboarding/roles", data={"roles": ["Data Analyst"], "custom_role": ""}).headers["location"] == "/onboarding/where"
    conn = connect(settings.db_path)
    assert get_user_prefs(conn, newbie).roles == ["Data Analyst"]
    assert get_onboarding(conn, newbie)[0] == "where"


def test_resume_after_quitting(newbie, client_as):
    web = client_as(newbie, follow_redirects=False)
    web.post("/onboarding/roles", data={"roles": ["Data Analyst"]})
    web.post("/onboarding/where", data={"cities": ["Pune"], "remote_india_ok": "on"})
    again = client_as(newbie, follow_redirects=False)       # a new session
    assert again.get("/").headers["location"] == "/onboarding/experience"
    page = again.get("/onboarding/where").text               # Back keeps data
    assert 'value="Pune" checked' in page


@pytest.mark.parametrize("form,msg", [
    ({"experience_years": "40", "drop_if_min_years_at_least": "41", "experience_summary": "x"}, "between 0 and 30"),
    ({"experience_years": "3", "drop_if_min_years_at_least": "2", "experience_summary": "x"}, "more than your"),
    ({"experience_years": "1", "drop_if_min_years_at_least": "2", "experience_summary": "x", "current_ctc_lpa": "900"}, "0 and 500"),
])
def test_experience_step_rules(newbie, client_as, form, msg):
    r = client_as(newbie).post("/onboarding/experience", data=form)
    assert r.status_code == 422 and msg in r.text


def test_onboarded_owner_never_sees_onboarding(client_as):
    assert client_as(1, follow_redirects=False).get("/onboarding/roles").status_code == 303
```
In `tests/test_web_guards.py::test_every_route_is_guarded`, add: every non-PUBLIC route **except** paths starting with `/onboarding`, `/logout`, `/settings/delete` and `/settings/export` must include `require_onboarded`; paths starting with `/onboarding` must **not**.

- [ ] **Step 2: Run them and watch them fail** (404 from `/onboarding/roles`; no redirect from `/`).

- [ ] **Step 3: Implement**

`src/jobseeker/web/deps.py`:
```python
class NotOnboarded(Exception):
    def __init__(self, step: str):
        self.step = step


def require_onboarded(user: User = Depends(current_user), conn=Depends(get_conn)) -> User:
    from jobseeker.db.profile import get_onboarding
    step, done = get_onboarding(conn, user.id)
    if not done:
        raise NotOnboarded(step or "roles")
    return user
```
`app.py`: a handler for `NotOnboarded`, mirroring the `NotAuthenticated` one: 303 to `/onboarding/<step>`, or 401 with `HX-Redirect`. Routers: `inbox`'s `/` calls `require_onboarded(user, conn)` itself after the anonymous check; `application`, `contacts`, `pipeline` and `admin` get `Depends(require_onboarded)` added to their `dependencies=[…]`.

`src/jobseeker/web/onboarding.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from jobseeker.config import ITEM_MAX, LIST_MAX
from jobseeker.db.profile import get_onboarding, get_user_prefs, save_user_prefs, set_onboarding
from jobseeker.web.deps import current_user, get_conn

router = APIRouter(prefix="/onboarding")
STEPS = ["roles", "where", "experience", "resume"]


def _list(form, key) -> list[str]:
    vals = [v.strip() for v in form.getlist(key) if v.strip()]
    vals += [v.strip() for v in (form.get(f"{key}_text") or "").split(",") if v.strip()]
    return list(dict.fromkeys(vals))


def _num(raw, errors, key, lo, hi, msg):
    if raw in (None, ""):
        return None
    try:
        v = float(raw)
    except ValueError:
        errors[key] = msg
        return None
    if not lo <= v <= hi:
        errors[key] = msg
    return v


def parse_step(step: str, form, cfg) -> tuple[dict, dict[str, str]]:
    errors: dict[str, str] = {}
    if step == "roles":
        labels = {r.label for r in cfg.roles}
        roles = [r for r in form.getlist("roles") if r in labels]
        custom = (form.get("custom_role") or "").strip()
        if len(custom) > ITEM_MAX:
            errors["custom_role"] = f"Keep it under {ITEM_MAX} characters"
        if not roles and not custom:
            errors["roles"] = "Pick at least one role"
        return {"roles": roles, "custom_role": custom}, errors
    if step == "where":
        cities = _list(form, "cities")
        remote = form.get("remote_india_ok") == "on"
        if not cities and not remote:
            errors["cities"] = "Pick a city or allow remote"
        if len(cities) > LIST_MAX:
            errors["cities"] = f"Up to {LIST_MAX} cities"
        return {"cities": cities, "remote_india_ok": remote}, errors
    if step == "experience":
        years = _num(form.get("experience_years"), errors, "experience_years", 0, 30, "Enter a number between 0 and 30")
        if years is None and "experience_years" not in errors:
            errors["experience_years"] = "Enter your years of experience"
        hide = _num(form.get("drop_if_min_years_at_least"), errors, "drop_if_min_years_at_least", 0, 40, "Enter a number")
        if hide is not None and years is not None and hide <= years:
            errors["drop_if_min_years_at_least"] = "Must be more than your years of experience"
        ctc = _num(form.get("current_ctc_lpa"), errors, "current_ctc_lpa", 0, 500, "Enter a number between 0 and 500")
        target = _num(form.get("target_base_lpa"), errors, "target_base_lpa", 0, 500, "Enter a number between 0 and 500")
        lists = {k: _list(form, k) for k in ("must_haves", "deal_breakers", "title_deny")}
        for k, v in lists.items():
            if len(v) > LIST_MAX or any(len(x) > ITEM_MAX for x in v):
                errors[k] = f"Up to {LIST_MAX} items of {ITEM_MAX} characters"
        summary = (form.get("experience_summary") or "").strip()
        fields = {"experience_years": years, "drop_if_min_years_at_least": hide, "current_ctc_lpa": ctc,
                  "target_base_lpa": target, "experience_summary": summary, **lists}
        if not summary:
            fields.pop("experience_summary")  # drafted from the facts at the resume step if still empty
        return fields, errors
    raise HTTPException(404)


def _render(request, step, up, errors=None, status=200):
    cfg = request.app.state.app_config
    return request.app.state.templates.TemplateResponse(
        request, f"onboarding/{step}.html",
        {"up": up, "cfg": cfg, "errors": errors or {}, "step_no": STEPS.index(step) + 1, "steps": len(STEPS)},
        status_code=status)


@router.get("/{step}")
def show(request: Request, step: str, user=Depends(current_user), conn=Depends(get_conn)):
    if step not in STEPS[:3]:
        raise HTTPException(404)  # the resume step lives in Task 6's routes
    if get_onboarding(conn, user.id)[1]:
        return RedirectResponse("/", 303)
    return _render(request, step, get_user_prefs(conn, user.id))


@router.post("/{step}")
async def save(request: Request, step: str, user=Depends(current_user), conn=Depends(get_conn)):
    if step not in STEPS[:3]:
        raise HTTPException(404)
    form = await request.form()
    fields, errors = parse_step(step, form, request.app.state.app_config)
    up = get_user_prefs(conn, user.id).model_copy(update=fields)
    if errors:
        return _render(request, step, up, errors, 422)
    now = datetime.now(UTC)
    save_user_prefs(conn, user.id, up, now)
    nxt = STEPS[STEPS.index(step) + 1]
    set_onboarding(conn, user.id, nxt, None, now)
    return RedirectResponse(f"/onboarding/{nxt}", 303)
```
(Starlette's `request.form()` is async, so this route is `async`. The DB calls are quick primary-key operations.)

Templates. `onboarding/base_step.html` extends `bare.html`:
```html
{% extends "bare.html" %}
{% block content %}
<div class="card block onboarding">
  <p class="muted mono">Step {{ step_no }} of {{ steps }}</p>
  <form method="post" action="/onboarding/{% block step %}{% endblock %}">
    {% block fields %}{% endblock %}
    <div class="sticky-actions"><button class="btn btn-primary" type="submit">Continue</button>
      {% if step_no > 1 %}<a class="btn-ghost" href="/onboarding/{{ ['roles','where','experience','resume'][step_no-2] }}">Back</a>{% endif %}</div>
  </form>
</div>
{% endblock %}
```
- `roles.html` contains `{% include "_prefs_roles.html" %}`, and likewise `where.html` and `experience.html`.
- `_prefs_roles.html`: one `<label class="chip"><input type="checkbox" name="roles" value="{{ r.label }}"{{ " checked" if r.label in up.roles }}> {{ r.label }}</label>` per `cfg.roles`; a text input `custom_role` with a maxlength of 60; and `{% if errors.roles %}<p class="field-err">{{ errors.roles }}</p>{% endif %}`.
- `_prefs_where.html`: city checkboxes exactly as `value="{{ c }}"{{ " checked" if c in up.cities }}` (the test checks for `value="Pune" checked`); a `cities_text` input for other cities; the `remote_india_ok` checkbox; the error line.
- `_prefs_experience.html`: number inputs `experience_years`, `drop_if_min_years_at_least` (pre-filled with `((up.experience_years + 1) * 2)|round(0, 'ceil') / 2` when the threshold is empty and years is set), `current_ctc_lpa` and `target_base_lpa`; the `must_haves_text`, `deal_breakers_text` and `title_deny_text` inputs (comma-separated, pre-filled with `(up.title_deny or cfg.default_title_deny)|join(", ")`); the `experience_summary` textarea; an error line per field.

Add CSS to `static/ui.css`, using the existing tokens:
```css
.chip { display: inline-flex; gap: .4rem; padding: .35rem .7rem; border: 1px solid var(--line); border-radius: 999px; margin: .2rem; }
.chip:has(input:checked) { background: var(--accent-wash); border-color: var(--accent); }
.field-err { color: var(--weak-fg); font-size: .9rem; }
@media (max-width: 640px) { .onboarding .sticky-actions { position: sticky; bottom: 0; background: var(--surface); padding: .75rem 0; } }
```

- [ ] **Step 4: Run the suites** (all pass; node 19)

- [ ] **Step 5: Commit** (`feat(onboarding): steps 1-3 with save-and-continue, and require_onboarded on the app`, plus the trailer)

---

### Task 5: Two-way `reevaluate` (replaces `refilter`)

**Files:**
- Create: `src/jobseeker/pipeline/evaluate.py`
- Delete: `src/jobseeker/pipeline/refilter.py`
- Modify: `src/jobseeker/cli.py:82-99` (`refilter` command wraps `reevaluate`)
- Move/modify: `tests/test_refilter.py` → `tests/test_evaluate.py` (the same scenarios, plus restore cases)

**Interfaces:**
- Consumes: `prefilter`, `prescore`, `blocked_companies(conn, user_id)`, `set_filter_reason`/`set_prescore`/`get_user_job` (plan 2).
- Produces:
  - `verdict(job: Job, prefs, facts, now, blocked) -> tuple[str | None, int]` (filter reason, or `None`; prescore);
  - `Report(hidden: list[dict], restored: list[dict], new: list[dict], skipped_apps: list[int], kept_apps: list[int])`;
  - `reevaluate(conn, user_id, prefs, facts, now, apply: bool) -> Report`.

  Spec 4's `evaluate` reuses `verdict`.

- [ ] **Step 1: Write the failing tests** (`tests/test_evaluate.py`; keep `tests/test_refilter.py`'s fixtures and data setup, adapted to `user_id=1`):

```python
from datetime import UTC, datetime

from jobseeker.db.applications import ensure_application, get_status, transition
from jobseeker.db.core import connect
from jobseeker.db.jobs import get_user_job, set_filter_reason, upsert_job
from jobseeker.pipeline.evaluate import reevaluate
from tests.factories import make_job

NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _db(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    pune, _ = upsert_job(conn, make_job(source_job_id="p", fingerprint="fp", location="Pune", location_city="pune",
                                        posted_at=NOW))
    blr, _ = upsert_job(conn, make_job(source_job_id="b", fingerprint="fb", posted_at=NOW))
    return conn, pune, blr


def test_loosening_restores_and_tightening_hides(tmp_path, prefs, facts):
    conn, pune, blr = _db(tmp_path)
    only_blr = prefs.model_copy(update={"cities": ["Bengaluru"], "remote_india_ok": False, "min_prescore": 0})
    reevaluate(conn, 1, only_blr, facts, NOW, apply=True)
    assert get_user_job(conn, 1, pune)["filter_reason"].startswith("location")
    both = only_blr.model_copy(update={"cities": ["Bengaluru", "Pune"]})
    report = reevaluate(conn, 1, both, facts, NOW, apply=True)
    assert [r["job_id"] for r in report.restored] == [pune]
    assert get_user_job(conn, 1, pune)["filter_reason"] is None


def test_preview_matches_apply_and_skips_only_pre_outreach(tmp_path, prefs, facts):
    conn, pune, blr = _db(tmp_path)
    base = prefs.model_copy(update={"min_prescore": 0})
    reevaluate(conn, 1, base, facts, NOW, apply=True)          # both jobs visible to start with
    a = ensure_application(conn, 1, pune, NOW)
    transition(conn, a, "shortlisted")
    tight = base.model_copy(update={"cities": ["Bengaluru"], "remote_india_ok": False})
    preview = reevaluate(conn, 1, tight, facts, NOW, apply=False)
    assert get_user_job(conn, 1, pune)["filter_reason"] is None   # a preview writes nothing
    applied = reevaluate(conn, 1, tight, facts, NOW, apply=True)
    assert [r["job_id"] for r in preview.hidden] == [r["job_id"] for r in applied.hidden] == [pune]
    assert preview.skipped_apps == applied.skipped_apps == [a] and get_status(conn, a) == "skipped"


def test_scored_job_never_hidden_by_low_prescore(tmp_path, prefs, facts):
    from jobseeker.db.jobs import save_score
    from jobseeker.models import ScoreResult
    conn, pune, blr = _db(tmp_path)
    save_score(conn, 1, blr, ScoreResult(score=80, breakdown={}, matches=[], gaps=[], recommendation="apply",
                                         role_family="pa"), "m", "v1", "h")
    strict = prefs.model_copy(update={"min_prescore": 1000})
    reevaluate(conn, 1, strict, facts, NOW, apply=True)
    assert get_user_job(conn, 1, blr)["filter_reason"] is None


def test_other_user_untouched(tmp_path, prefs, facts):
    conn, pune, blr = _db(tmp_path)
    conn.execute("INSERT INTO users (id, email, created_at) VALUES (2, 'b@example.com', 't')")
    set_filter_reason(conn, 2, pune, "title: x")
    reevaluate(conn, 1, prefs, facts, NOW, apply=True)
    assert get_user_job(conn, 2, pune)["filter_reason"] == "title: x"


def test_5000_jobs_under_two_seconds(tmp_path, prefs, facts):
    import time
    conn = connect(tmp_path / "db.sqlite")
    for i in range(5000):
        upsert_job(conn, make_job(source_job_id=str(i), fingerprint=f"f{i}", posted_at=NOW))
    t = time.perf_counter()
    reevaluate(conn, 1, prefs, facts, NOW, apply=True)
    assert time.perf_counter() - t < 2.0
```
If `upsert_job` committing per row makes the 5,000-row setup slow, build the rows with one `executemany` insert into `jobs` in that test instead. The timing applies to `reevaluate` only.

- [ ] **Step 2: Run them and watch them fail** (ImportError: `jobseeker.pipeline.evaluate`)

- [ ] **Step 3: Implement** (`src/jobseeker/pipeline/evaluate.py`):

```python
"""Per-user job verdicts (filter reason + pre-score), re-applied after a preference change in both directions."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from jobseeker.config import Preferences
from jobseeker.db.applications import blocked_companies, get_status, transition
from jobseeker.db.core import iso
from jobseeker.db.jobs import job_from_row
from jobseeker.pipeline.prefilter import prefilter
from jobseeker.pipeline.prescore import prescore
from jobseeker.profile.facts import Facts

BEFORE_OUTREACH = {"new", "shortlisted", "drafted"}  # from "approved" on, a Gmail draft exists


@dataclass
class Report:
    hidden: list[dict] = field(default_factory=list)
    restored: list[dict] = field(default_factory=list)
    new: list[dict] = field(default_factory=list)
    skipped_apps: list[int] = field(default_factory=list)
    kept_apps: list[int] = field(default_factory=list)


def verdict(job, prefs: Preferences, facts: Facts | None, now: datetime, blocked: set[str],
            scored: bool) -> tuple[str | None, int]:
    points = prescore(job, facts, prefs) if facts is not None else 0
    reason = prefilter(job, prefs, now, blocked)
    if reason and reason.startswith("stale:"):
        reason = None  # age isn't re-judged here; old jobs expire on their own
    if reason is None and not scored and points < prefs.min_prescore:
        reason = f"low pre-score: {points}"
    return reason, points


def reevaluate(conn: sqlite3.Connection, user_id: int, prefs: Preferences, facts: Facts | None, now: datetime,
               apply: bool) -> Report:
    blocked = blocked_companies(conn, user_id)
    cutoff = iso(now - timedelta(days=prefs.max_age_days))
    rows = conn.execute(
        """SELECT j.*, uj.filter_reason AS old_reason, uj.job_id AS has_row, a.id AS app_id, a.status AS app_status,
                  EXISTS (SELECT 1 FROM scores s WHERE s.user_id = :u AND s.job_id = j.id) AS scored
           FROM jobs j LEFT JOIN user_jobs uj ON uj.job_id = j.id AND uj.user_id = :u
           LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = :u
           WHERE COALESCE(j.posted_at, j.first_seen_at) >= :cutoff
           AND (uj.filter_reason IS NULL OR uj.filter_reason NOT LIKE 'stale:%')""",
        {"u": user_id, "cutoff": cutoff}).fetchall()
    report, writes = Report(), []
    for r in rows:
        r = dict(r)
        reason, points = verdict(job_from_row(r), prefs, facts, now, blocked, bool(r["scored"]))
        info = {"job_id": r["id"], "title": r["title"], "company": r["company"], "reason": reason}
        if r["has_row"] is None:
            report.new.append(info)
        elif r["old_reason"] is None and reason is not None:
            report.hidden.append(info)
            if r["app_id"]:
                (report.skipped_apps if r["app_status"] in BEFORE_OUTREACH else report.kept_apps).append(r["app_id"])
        elif r["old_reason"] is not None and reason is None:
            report.restored.append(info)
        writes.append((user_id, r["id"], reason, points, r["jd_hash"], iso(now)))
    if apply:
        conn.executemany(
            """INSERT INTO user_jobs (user_id, job_id, filter_reason, prescore, jd_hash, evaluated_at) VALUES (?,?,?,?,?,?)
               ON CONFLICT (user_id, job_id) DO UPDATE SET filter_reason = excluded.filter_reason,
                 prescore = excluded.prescore, jd_hash = excluded.jd_hash, evaluated_at = excluded.evaluated_at""", writes)
        conn.commit()
        for app_id in report.skipped_apps:
            if get_status(conn, app_id) in BEFORE_OUTREACH:
                transition(conn, app_id, "skipped", {"reason": "settings: preferences changed"}, now)
    return report
```
Check `prescore`'s signature with `facts=None`: today's `prescore(job, facts, prefs)` reads `facts.skills`. The guard `if facts is not None else 0` covers a user still in onboarding.

`src/jobseeker/cli.py` `refilter`: `report = reevaluate(conn, uid, prefs, facts, datetime.now(UTC), apply=apply)`. It prints the hidden, restored and skipped counts and each hidden row as before (`title`, `company`, `reason`, and "-> skipped" for skipped apps). The old `refilter` echo text is kept; `restored` is listed with "-> back".

Delete `src/jobseeker/pipeline/refilter.py` and `tests/test_refilter.py` (their scenarios now live in `test_evaluate.py`). `grep -rn "pipeline.refilter\|run_refilter" src tests` must be empty.

- [ ] **Step 4: Run the suites** (all pass; node 19)

- [ ] **Step 5: Commit** (`feat(pipeline): two-way reevaluate replaces refilter`, plus the trailer)

---

### Task 6: Resume upload, fact extraction, review, Finish

**Files:**
- Modify: `src/jobseeker/profile/resume.py` (`ResumeRejected`, `validate_pdf`, `store_resume`)
- Create: `src/jobseeker/profile/extract.py` (`run_extract`)
- Modify: `src/jobseeker/web/onboarding.py` (`GET/POST /onboarding/resume`, `/onboarding/resume/status`, `/onboarding/facts`, `/onboarding/facts/manual`, `/onboarding/finish`, `/onboarding/done`, `/onboarding/done/status`)
- Create: `src/jobseeker/web/templates/onboarding/resume.html`, `done.html`, `_resume_status.html`, `_facts_form.html`
- Test: `tests/test_resume.py` (new); append to `tests/test_onboarding.py`

**Interfaces:**
- Consumes: `extract_facts`, `claim_extract`, `set_extract_status`, `save_facts`, `facts_row`, `get_facts` (Task 3); `Budget`, `Limit` (plan 2); `reevaluate` (Task 5); `load_user_context` (Task 3).
- Produces:
  - `MAX_BYTES = 5 * 1024 * 1024`, `MAX_PAGES = 10`, `MIN_CHARS = 300`;
  - `validate_pdf(data: bytes, content_type: str) -> str` (raises `ResumeRejected(message)`);
  - `store_resume(home, user_id, data) -> tuple[Path, str]` (path, sha256);
  - `facts_limits(cfg) -> dict[str, Limit]`;
  - `run_extract(db_path, home, user_id, settings, app_config, llm_factory) -> None`;
  - `parse_facts_form(form) -> tuple[Facts | None, dict[str, str]]`;
  - `first_evaluation(db_path, user_id, app_config) -> None` (the background task).

- [ ] **Step 1: Write the failing tests**

`tests/test_resume.py`:
```python
import fitz
import pytest

from jobseeker.profile.resume import MAX_BYTES, ResumeRejected, store_resume, validate_pdf

GOOD = "Asha Owner — Product Analyst. " * 20


def pdf_bytes(text=GOOD, pages=1):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), text[:200])
        doc[-1].insert_text((72, 100), text[200:400])
    return doc.tobytes()


def test_good_pdf_returns_text():
    assert "Product Analyst" in validate_pdf(pdf_bytes(), "application/pdf")


@pytest.mark.parametrize("data,ctype,msg", [
    (b"\x89PNG....", "application/pdf", "as a PDF"),
    (pdf_bytes(), "image/png", "as a PDF"),
    (b"%PDF-1.4 broken", "application/pdf", "couldn't be read"),
    (pdf_bytes(pages=11), "application/pdf", "over 10 pages"),
    (pdf_bytes(text="hi"), "application/pdf", "scanned PDF"),
    (b"%PDF-" + b"0" * MAX_BYTES, "application/pdf", "over 5 MB"),
])
def test_rejections(data, ctype, msg):
    with pytest.raises(ResumeRejected, match=msg):
        validate_pdf(data, ctype)


def test_store_resume_modes_and_atomic(tmp_path):
    path, sha = store_resume(tmp_path, 7, pdf_bytes())
    assert path == tmp_path / "data" / "users" / "7" / "resume.pdf" and len(sha) == 64
    assert oct(path.stat().st_mode)[-3:] == "600" and oct(path.parent.stat().st_mode)[-3:] == "700"
    assert not (path.parent / "resume.pdf.tmp").exists()
```
Append to `tests/test_onboarding.py`:
```python
from tests.test_resume import GOOD, pdf_bytes


def _to_resume_step(web):
    web.post("/onboarding/roles", data={"roles": ["Data Analyst"]})
    web.post("/onboarding/where", data={"cities": ["Pune"]})
    web.post("/onboarding/experience", data={"experience_years": "1", "drop_if_min_years_at_least": "2.5",
                                             "experience_summary": "One year in analytics."})


def test_upload_extracts_once_per_sha(newbie, client_as, settings, monkeypatch, facts):
    calls = []
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", lambda llm, text, model: calls.append(1) or facts)
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    files = {"resume": ("cv.pdf", pdf_bytes(), "application/pdf")}
    assert web.post("/onboarding/resume", files=files).status_code == 303
    assert web.post("/onboarding/resume", files=files).status_code == 303   # same file: cached
    assert calls == [1]
    assert "Check what we read" in web.get("/onboarding/resume/status").text


def test_fourth_extraction_today_refused(newbie, client_as, settings, monkeypatch, facts):
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", lambda llm, text, model: facts)
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    for i in range(3):
        web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes(f"v{i} " + GOOD), "application/pdf")})
    web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes("v9 " + GOOD), "application/pdf")})
    assert "re-read your resume again tomorrow" in web.get("/onboarding/resume/status").text


def test_manual_skills_when_quota_gone_then_finish(newbie, client_as, settings, monkeypatch):
    from jobseeker.llm import LLMQuotaExceeded

    def gone(llm, text, model):
        raise LLMQuotaExceeded("used up")
    monkeypatch.setattr("jobseeker.profile.extract.extract_facts", gone)
    queued = []
    monkeypatch.setattr("jobseeker.web.onboarding.first_evaluation", lambda *a: queued.append(a))
    web = client_as(newbie, follow_redirects=False)
    _to_resume_step(web)
    web.post("/onboarding/resume", files={"resume": ("cv.pdf", pdf_bytes(), "application/pdf")})
    assert "Enter my skills myself" in web.get("/onboarding/resume/status").text
    r = web.post("/onboarding/facts/manual", data={"headline": "Analyst", "skills_text": "SQL, Excel",
                                                   "achievement": ["Built a dashboard used by 40 people"]})
    assert r.status_code == 303
    assert web.post("/onboarding/finish").headers["location"] == "/onboarding/done"
    assert queued and client_as(newbie, follow_redirects=False).get("/").status_code == 200


def test_finish_with_gap_sends_back(newbie, client_as):
    web = client_as(newbie, follow_redirects=False)
    web.post("/onboarding/roles", data={"roles": ["Data Analyst"]})
    assert web.post("/onboarding/finish").headers["location"].startswith("/onboarding/where")
```
- [ ] **Step 2: Run them and watch them fail** (ImportError / 404)

- [ ] **Step 3: Implement**

`src/jobseeker/profile/resume.py`, appended:
```python
import hashlib
import os

MAX_BYTES, MAX_PAGES, MIN_CHARS = 5 * 1024 * 1024, 10, 300


class ResumeRejected(ValueError):
    pass


def validate_pdf(data: bytes, content_type: str) -> str:
    if len(data) > MAX_BYTES:
        raise ResumeRejected("That file is over 5 MB. Export a smaller PDF.")
    if content_type != "application/pdf" or not data.startswith(b"%PDF-"):
        raise ResumeRejected("Please upload your resume as a PDF.")
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.page_count == 0:
                raise ResumeRejected("That PDF couldn't be read. Try exporting it again.")
            if doc.page_count > MAX_PAGES:
                raise ResumeRejected("Resumes over 10 pages aren't supported.")
            text = "\n".join(p.get_text() for p in doc).strip()
    except ResumeRejected:
        raise
    except Exception as e:  # PyMuPDF raises its own error types for broken files
        raise ResumeRejected("That PDF couldn't be read. Try exporting it again.") from e
    if len(text) < MIN_CHARS:
        raise ResumeRejected("This looks like a scanned PDF. Export a text PDF from Word or Google Docs.")
    return text


def store_resume(home: Path, user_id: int, data: bytes) -> tuple[Path, str]:
    path = resume_path(home, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path, hashlib.sha256(data).hexdigest()
```
The route reads at most `MAX_BYTES + 1` bytes (`await upload.read(MAX_BYTES + 1)`), so an oversized upload is never held in full.

`src/jobseeker/profile/extract.py`:
```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jobseeker.db.core import connect
from jobseeker.db.profile import facts_row, save_facts, set_extract_status
from jobseeker.db.usage import Budget, Limit
from jobseeker.llm import LLMQuotaExceeded, LLMUnavailable
from jobseeker.profile.facts import extract_facts
from jobseeker.profile.resume import resume_path, validate_pdf

IST = ZoneInfo("Asia/Kolkata")


def facts_limits(cfg) -> dict[str, Limit]:
    return {"groq:facts": Limit("day", cfg.budgets.facts_per_day, cfg.budgets.facts_per_user_per_day)}


def run_extract(db_path, home, user_id: int, sha: str, app_config, llm_factory) -> None:
    conn = connect(db_path)
    try:
        budget = Budget(conn, user_id, facts_limits(app_config), datetime.now(IST))
        if not budget.can("groq:facts"):
            set_extract_status(conn, user_id, "failed",
                               "You can re-read your resume again tomorrow; your current facts stay.")
            return
        budget.spend("groq:facts")
        text = validate_pdf(resume_path(home, user_id).read_bytes(), "application/pdf")
        try:
            facts = extract_facts(llm_factory(), text, app_config.models.facts)
        except (LLMQuotaExceeded, LLMUnavailable):
            set_extract_status(conn, user_id, "failed", "AI limit reached for today.")
            return
        save_facts(conn, user_id, sha, facts, edited=False, now=datetime.now(IST))
    except Exception as e:  # the page must always leave the running state
        set_extract_status(conn, user_id, "failed", f"{type(e).__name__}: {e}")
    finally:
        conn.close()
```
(Pass `sha` from the route. `facts_row` is imported for the route's cache check, so keep the import there, not here.)

Routes in `src/jobseeker/web/onboarding.py`, defined **before** the generic `/{step}` routes so FastAPI matches them first:
- `GET /onboarding/resume`: renders `onboarding/resume.html` (an upload form with `enctype="multipart/form-data"` and `accept="application/pdf"`, plus `{% include "_resume_status.html" %}`, which polls `hx-get="/onboarding/resume/status" hx-trigger="every 3s"` while the status is `running`).
- `POST /onboarding/resume`:
  - `upload: UploadFile = File(...)`, `data = await upload.read(MAX_BYTES + 1)`;
  - `validate_pdf(data, upload.content_type)` (on `ResumeRejected` → 422, re-render with the message);
  - `store_resume`, then set `user_facts.resume_uploaded_at`;
  - if `facts_row(...)["resume_sha256"] == sha` and facts exist, redirect without extracting;
  - otherwise, if `claim_extract(conn, user.id, now)`, `background.add_task(run_extract, settings.db_path, settings.jobseeker_home, user.id, sha, app_config, state.llm_factory)`;
  - a new sha with `edited=1` before it sets the flash "Your earlier edits were replaced by the new resume.";
  - redirect 303 to `/onboarding/resume`.
- `GET /onboarding/resume/status`: renders `_resume_status.html`:
  - `running` → "Reading your resume…" (keeps polling);
  - `failed` → the `extract_error`, plus a manual-entry form (`_facts_form.html` posting to `/onboarding/facts/manual`, with the button "Enter my skills myself") when there are no facts;
  - `done` → the review form (`_facts_form.html` posting to `/onboarding/facts`, heading "Check what we read"), and the Finish button `<form method="post" action="/onboarding/finish">`.
- `parse_facts_form(form)`: `headline` (required); `skills_text` (comma-separated, ≥ 1); `achievement` (repeated textareas, empty ones dropped, at most 6 for manual entry); `role_title`/`role_org`/`role_start`/`role_end` (parallel lists, rows with an empty title dropped). Metrics come from `re.findall(r"[\d][\d,.]*\s?(?:%|K\+?|M\+?|\+)?", text)`. It returns errors for an empty headline or no skills.
- `POST /onboarding/facts` and `POST /onboarding/facts/manual`: `save_facts(conn, user.id, sha_or_existing, facts, edited=True, now)`; manual saves use the current resume sha if any. If `experience_summary` is empty in the prefs, draft it: `"; ".join(f"{r.title} at {r.org} ({r.start}–{r.end})" for r in facts.roles)` or the headline. Redirect to `/onboarding/resume`.
- `POST /onboarding/finish`:
  - `missing = get_user_prefs(...).complete()`;
  - if `missing`, redirect to `/onboarding/{missing[0]}?err=Please+finish+this+step`;
  - if there are no facts, redirect to `/onboarding/resume?err=Add+your+resume+or+skills+first`;
  - otherwise `set_onboarding(conn, user.id, None, iso(now), now)`, `background.add_task(first_evaluation, settings.db_path, user.id, app_config)`, and redirect to `/onboarding/done`.
- `first_evaluation(db_path, user_id, app_config)`: opens its own connection, then `prefs, facts = load_user_context(conn, user_id, app_config)` and `reevaluate(conn, user_id, prefs, facts, datetime.now(UTC), apply=True)`.
- `GET /onboarding/done` (`done.html`: "You're set." with a progress fragment polling `/onboarding/done/status` every 3 s and a "Go to Jobs" button) and `GET /onboarding/done/status` ("Checked {n} jobs; {m} match your filters", from `SELECT COUNT(*), SUM(filter_reason IS NULL) FROM user_jobs WHERE user_id = ?`, then "Your first scores arrive with the next run"). Both routes need `current_user` and must work after `onboarded_at` is set, so they're exempt from the `/` redirect in `show`.

- [ ] **Step 4: Run the suites** (all pass; node 19)

- [ ] **Step 5: Commit** (`feat(onboarding): resume upload, budgeted fact extraction, review or manual entry, Finish`, plus the trailer)

---

### Task 7: The Settings page

**Files:**
- Create: `src/jobseeker/web/settings.py`, `src/jobseeker/web/templates/settings.html`
- Modify: `src/jobseeker/web/templates/base.html:22-23` (4th nav item), `:46-49` (drop the sidebar and top-bar Sign out added in plan 2; Settings owns it now; keep the Admin link)
- Modify: `src/jobseeker/web/templates/_icons.html` (a `gear` icon)
- Modify: `src/jobseeker/web/app.py` (include `settings.router` with `current_user` + `require_onboarded`, except delete/export, Task 8)
- Test: `tests/test_settings.py` (new); update `tests/test_web_mobile.py` and `tests/test_web_redesign.py` tab-count assertions (`grep -n "tabbar\|nav-item" tests/test_web_mobile.py tests/test_web_redesign.py`)

**Interfaces:**
- Consumes: `parse_step`, the `_prefs_*.html` partials (Task 4); `reevaluate` (Task 5); `store_resume`/`run_extract`/`parse_facts_form` (Task 6); `get_user_prefs`/`save_user_prefs`/`load_user_context` (Task 3).
- Produces: `GET /settings`; `POST /settings/profile`; `POST /settings/prefs/{section}` (with `confirm=1` to apply after a preview); `POST /settings/resume`; `GET /settings/resume/status`; `POST /settings/facts`. `FILTER_FIELDS = {"roles", "custom_role", "cities", "remote_india_ok", "drop_if_min_years_at_least", "title_deny"}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_settings.py`):

```python
from jobseeker.db.core import connect
from jobseeker.db.jobs import get_user_job
from jobseeker.db.profile import get_user_prefs


def test_settings_is_fourth_tab(client_as):
    html = client_as(1).get("/settings").text
    tabbar = html.split('class="tabbar"')[1]
    assert tabbar.count("nav-item") == 4 and "/settings" in tabbar


def test_filter_change_previews_then_applies(client_as, settings, seeded):
    web = client_as(1, follow_redirects=False)
    preview = web.post("/settings/prefs/where", data={"cities": ["Hyderabad"]})
    assert preview.status_code == 200 and "This hides" in preview.text
    assert get_user_prefs(connect(settings.db_path), 1).cities != ["Hyderabad"]   # not saved yet
    done = web.post("/settings/prefs/where", data={"cities": ["Hyderabad"], "confirm": "1"})
    assert done.status_code == 303
    assert get_user_prefs(connect(settings.db_path), 1).cities == ["Hyderabad"]


def test_scoring_only_change_saves_without_preview(client_as, settings, monkeypatch):
    called = []
    monkeypatch.setattr("jobseeker.web.settings.reevaluate", lambda *a, **k: called.append(1))
    r = client_as(1, follow_redirects=False).post("/settings/prefs/experience", data={
        "experience_years": "1.3", "drop_if_min_years_at_least": "2.5",
        "experience_summary": "Changed summary", "current_ctc_lpa": "21",
        "title_deny_text": ", ".join(get_user_prefs(connect(settings.db_path), 1).title_deny or [])})
    assert r.status_code == 303 and called == []
    assert "Scores refresh over the next runs" in r.headers["location"].replace("+", " ").replace("%20", " ")


def test_roommate_settings_never_touch_owner(seeded_two, client_as, settings):
    before = get_user_job(connect(settings.db_path), 1, seeded_two["j1"])
    client_as(2, follow_redirects=False).post("/settings/prefs/where", data={"cities": ["Chennai"], "confirm": "1"})
    assert get_user_job(connect(settings.db_path), 1, seeded_two["j1"]) == before
```

- [ ] **Step 2: Run them and watch them fail** (404)

- [ ] **Step 3: Implement** (`src/jobseeker/web/settings.py`):

```python
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from jobseeker.db.profile import facts_row, get_user_prefs, load_user_context, save_user_prefs
from jobseeker.pipeline.evaluate import reevaluate
from jobseeker.web.deps import current_user, get_conn, render
from jobseeker.web.onboarding import parse_step

router = APIRouter(prefix="/settings")
FILTER_FIELDS = {"roles", "custom_role", "cities", "remote_india_ok", "drop_if_min_years_at_least", "title_deny"}
SECTIONS = {"roles", "where", "experience"}


def _back(msg="", err=""):
    q = f"?msg={quote(msg)}" if msg else (f"?err={quote(err)}" if err else "")
    return RedirectResponse(f"/settings{q}", 303)


@router.get("")
def page(request: Request, user=Depends(current_user), conn=Depends(get_conn)):
    return render(request, conn, "settings.html", up=get_user_prefs(conn, user.id), cfg=request.app.state.app_config,
                  facts_info=facts_row(conn, user.id), errors={})


@router.post("/prefs/{section}")
async def save_prefs(request: Request, section: str, user=Depends(current_user), conn=Depends(get_conn)):
    if section not in SECTIONS:
        return _back(err="Unknown section")
    form = await request.form()
    cfg = request.app.state.app_config
    fields, errors = parse_step(section, form, cfg)
    old = get_user_prefs(conn, user.id)
    new = old.model_copy(update=fields)
    if errors:
        return render(request, conn, "settings.html", up=new, cfg=cfg, facts_info=facts_row(conn, user.id),
                      errors=errors, open_section=section)
    now = datetime.now(UTC)
    filter_changed = any(getattr(old, f) != getattr(new, f) for f in FILTER_FIELDS)
    if not filter_changed:
        save_user_prefs(conn, user.id, new, now)
        return _back(msg="Saved. Scores refresh over the next runs")
    prefs, facts = load_user_context(conn, user.id, cfg)
    from jobseeker.config import effective_prefs
    candidate = effective_prefs(new, cfg, prefs.name, prefs.email)
    if form.get("confirm") != "1":
        report = await run_in_threadpool(reevaluate, conn, user.id, candidate, facts, now, False)
        return render(request, conn, "settings.html", up=new, cfg=cfg, facts_info=facts_row(conn, user.id),
                      errors={}, open_section=section, preview=report, preview_form=list(form.multi_items()))
    save_user_prefs(conn, user.id, new, now)
    report = await run_in_threadpool(reevaluate, conn, user.id, candidate, facts, now, True)
    return _back(msg=f"Saved: {len(report.hidden)} hidden, {len(report.restored)} back, "
                     f"{len(report.skipped_apps)} skipped (Undo works on each)")
```
The resume and facts routes reuse Task 6's handlers. Factor `POST /onboarding/resume`'s body into `handle_resume_upload(request, background, upload, user, conn, back_url)` and the facts save into `handle_facts_save(..., back_url)` inside `onboarding.py`. Settings calls them with `back_url="/settings"`. `GET /settings/resume/status` renders the same `_resume_status.html`, with the Finish button hidden (`show_finish=False`).

`templates/settings.html` extends `base.html`, with 4 cards:
1. **Profile:** name and email as text; a form posting to `/settings/profile` with `linkedin` and `github`.
2. **What I'm looking for:** three `<details>` blocks (Roles, Where, Experience and pay), each a form posting to `/settings/prefs/<section>` and including the matching `_prefs_*.html` partial; `open` when `open_section == section`. When `preview` is set, a preview card shows above the section: "This hides {{ preview.hidden|length }} jobs, brings back {{ preview.restored|length }} and skips {{ preview.skipped_apps|length }} drafted applications." It has a **Save** form that re-posts every `preview_form` pair as hidden inputs plus `confirm=1`, and a **Cancel** link to `/settings`.
3. **Resume and facts:** the file name `resume.pdf` and `facts_info.resume_uploaded_at|age`; a Replace upload form posting to `/settings/resume`; and the `_resume_status.html` include.
4. **Account:** "Download my data" (`/settings/export`); "Sign out" (POST `/logout`); "Sign out everywhere" (POST `/logout/all`); "Delete my account" (a link to `/settings/delete`). Sub-project 5 adds a Gmail card and sub-project 6 a "Daily match alerts" card here.

`POST /settings/profile`: validate that each URL is empty or starts with `https://`, then save `linkedin`/`github` into `UserPrefs`.

`base.html:22-23`, the items list:
```jinja
{% set items = [("today", "/today", "Today", nav.today if nav else 0), ("jobs", "/", "Jobs", nav.jobs if nav else 0),
                ("pipeline", "/pipeline", "Pipeline", nav.pipeline if nav else 0), ("gear", "/settings", "Settings", 0)] %}
```
`_icons.html`: `{%- elif name == "gear" -%}<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>`.

In `base.html`'s sidebar foot, remove the plan 2 Sign out form and the top-bar `topbar-signout` form. Keep the Admin link.

- [ ] **Step 4: Run the suites** (all pass; fix the tab-count assertions in the mobile and redesign tests from 3 to 4; node 19)

- [ ] **Step 5: Commit** (`feat(settings): Settings tab with previewed two-way preference edits, resume and facts`, plus the trailer)

---

### Task 8: Download my data, and delete my account

**Files:**
- Modify: `src/jobseeker/web/settings.py` (`GET /settings/export`, `GET/POST /settings/delete`; these two routes sit on a second router `account_router`, with only `current_user`, not `require_onboarded`)
- Create: `src/jobseeker/web/templates/settings_delete.html`
- Create: `src/jobseeker/db/account.py` (`export_zip`, `delete_account`, `USER_TABLES`)
- Test: `tests/test_account.py` (new)

**Interfaces:**
- Consumes: `seeded_two` (plan 2), `resume_path` (Task 3).
- Produces:
  - `export_zip(conn, home, user_id) -> bytes`;
  - `delete_account(conn, home, user_id) -> None` (raises `LastAdmin`);
  - `user_scoped_tables(conn) -> list[tuple[str, str]]`: (table, how), where `how` is `"user_id"`, `"owner_user_id"` or `"application_id"`. This is the delete test's oracle, and later sub-projects' tables are picked up automatically.

- [ ] **Step 1: Write the failing tests** (`tests/test_account.py`):

```python
import io
import json
import zipfile

import pytest

from jobseeker.db.account import delete_account, export_zip, user_scoped_tables
from jobseeker.db.core import connect
from jobseeker.db.users import LastAdmin


def test_export_contains_only_own_data(seeded_two, settings):
    z = zipfile.ZipFile(io.BytesIO(export_zip(connect(settings.db_path), settings.jobseeker_home, 1)))
    assert {"profile.json", "applications.json", "job_verdicts.csv"} <= set(z.namelist())
    apps = json.loads(z.read("applications.json"))
    assert seeded_two["roommate_app"] not in [a["id"] for a in apps]
    assert "growth_analyst" not in z.read("applications.json").decode()


def test_delete_removes_every_user_row_and_keeps_others(seeded_two, settings):
    conn = connect(settings.db_path)
    owner_before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t, _ in user_scoped_tables(conn)}
    (settings.jobseeker_home / "data" / "users" / "2").mkdir(parents=True, exist_ok=True)
    roommate_counts = _counts(conn, 2)
    delete_account(conn, settings.jobseeker_home, 2)
    assert all(n == 0 for n in _counts(conn, 2).values())
    for t, _ in user_scoped_tables(conn):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == owner_before[t] - roommate_counts[t], t
    assert not (settings.jobseeker_home / "data" / "users" / "2").exists()
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = 2").fetchone()[0] == 0


def _counts(conn, uid):
    out = {}
    for t, how in user_scoped_tables(conn):
        if how == "application_id":
            sql = f"SELECT COUNT(*) FROM {t} WHERE application_id IN (SELECT id FROM applications WHERE user_id = ?)"
        else:
            sql = f"SELECT COUNT(*) FROM {t} WHERE {how} = ?"
        out[t] = conn.execute(sql, (uid,)).fetchone()[0]
    return out


def test_last_admin_cannot_delete(settings):
    with pytest.raises(LastAdmin):
        delete_account(connect(settings.db_path), settings.jobseeker_home, 1)


def test_delete_route_needs_typed_email(seeded_two, client_as, settings):
    web = client_as(2, follow_redirects=False)
    assert "4 weeks" in web.get("/settings/delete").text
    assert web.post("/settings/delete", data={"email": "wrong@example.com"}).status_code == 422
    r = web.post("/settings/delete", data={"email": "roomie@example.com"})
    assert r.status_code == 303 and r.headers["location"] == "/login"
```

- [ ] **Step 2: Run them and watch them fail** (ImportError)

- [ ] **Step 3: Implement** (`src/jobseeker/db/account.py`):

```python
from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

from jobseeker.db.users import LastAdmin

SHARED = {"users", "jobs", "contacts", "company_domains", "discovered_companies", "people_searches", "app_state",
          "locks"}


def user_scoped_tables(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every table holding per-user rows, found from the schema (later sub-projects' tables are included
    automatically). `users` itself is handled last."""
    out = []
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if t in SHARED:
            if t == "contacts" and "owner_user_id" in {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}:
                out.append((t, "owner_user_id"))
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        if "user_id" in cols:
            out.append((t, "user_id"))
        elif "application_id" in cols:
            out.append((t, "application_id"))
    return out


def delete_account(conn: sqlite3.Connection, home: Path, user_id: int) -> None:
    row = conn.execute("SELECT is_admin, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if row["is_admin"] and not conn.execute(
            "SELECT 1 FROM users WHERE is_admin = 1 AND disabled_at IS NULL AND id != ?", (user_id,)).fetchone():
        raise LastAdmin("You're the only admin")
    tables = user_scoped_tables(conn)
    with conn:
        for t, how in [x for x in tables if x[1] == "application_id"]:
            conn.execute(f"DELETE FROM {t} WHERE application_id IN (SELECT id FROM applications WHERE user_id = ?)",
                         (user_id,))
        # contacts.owner_user_id rows go after application_contacts (above), before applications/users
        for t, how in [x for x in tables if x[1] != "application_id" and x[0] != "applications"]:
            conn.execute(f"DELETE FROM {t} WHERE {how} = ?", (user_id,))
        conn.execute("DELETE FROM applications WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM invites WHERE email = ?", (row["email"],))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    shutil.rmtree(home / "data" / "users" / str(user_id), ignore_errors=True)
```
**Order caveat:** `scores`, `user_jobs`, `usage`, `blocklist`, `sessions`, `user_prefs`, `user_facts` and `runs` reference only `users`, so any order before deleting `users` works. `applications` must go after its children and before `users`. `runs.user_id` is nullable: delete the user's runs rather than nulling them. `invites` has no `user_id` (it's keyed by email), so it isn't in `user_scoped_tables`, and it's deleted explicitly above. If `PRAGMA foreign_key_check` after the deletion is non-empty in the test, add the missing table to the right group.

`export_zip(conn, home, user_id)`:
- `profile.json` = `{"user": {email, name, created_at}, "prefs": json.loads(user_prefs.data), "facts": json.loads(user_facts.facts or "null")}`;
- `resume.pdf` if `resume_path(home, user_id)` exists;
- `applications.json` = for each of the user's applications: `{"id", "status", "job": {title, company, location, apply_url}, "score": latest_score(conn, user_id, job_id) as {score, recommendation, role_family}, "drafts": get_drafts(...), "events": get_events(...), "people": people(conn, app_id) as {name, role, linkedin_url, email, email_status}}`;
- `job_verdicts.csv` with the header `job_id,title,company,filter_reason,prescore` from `user_jobs JOIN jobs WHERE user_id = ?`.

It's written with `zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)`.

Routes (`account_router = APIRouter(prefix="/settings")`, included with only `Depends(current_user)`):
- `GET /settings/export` → `Response(export_zip(...), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="jobseeker-{email}-{date}.zip"'})`.
- `GET /settings/delete` → `settings_delete.html`: "Type your email to confirm. Shared job listings stay. Backups keep copies for up to 4 weeks." The form has `email`, plus a red "Delete my account" button, which is disabled with "You're the only admin" for the last admin.
- `POST /settings/delete`:
  - email mismatch → 422 "The email doesn't match";
  - `LastAdmin` → 403;
  - otherwise `delete_account`, expire the session cookie, and redirect 303 to `/login`.

Add `/settings/export` and `/settings/delete` to the route walk's onboarding exemptions (Task 4's guard-test edit already lists them).

- [ ] **Step 4: Run the suites** (all pass; node 19)

- [ ] **Step 5: Commit** (`feat(settings): download my data and delete my account (table-walk tested)`, plus the trailer)

---

### Task 9: No runtime reads of profile files; acceptance; handoff

**Files:**
- Test: `tests/test_safety.py` (append)
- Modify: `HANDOFF.md`

- [ ] **Step 1: The guard test** (append to `tests/test_safety.py`):

```python
def test_no_runtime_reads_of_profile_files():
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "jobseeker"
    offenders = [str(p) for p in src.rglob("*.py") if p.name != "importer.py"
                 for line in p.read_text().splitlines()
                 if any(s in line for s in ('"preferences.yaml"', '"facts.json"', "profile_dir /", "app.state.prefs"))]
    assert offenders == []
```

- [ ] **Step 2: Run the suites**: pytest all pass; node 19.

- [ ] **Step 3: Acceptance checks** (manual, in the worktree):
1. `/tmp/jsacc`: copy the live DB with `.backup` and the Mac's `profile/` into `/tmp/jsacc/profile/`, then `JOBSEEKER_HOME=/tmp/jsacc OWNER_EMAIL=mkshitij1763@gmail.com uv run jobseeker migrate`. Expected: v1 and v2 applied, "imported preferences.yaml/facts.json/resume.pdf", and **the golden check passes on the real preferences**.
2. `JOBSEEKER_HOME=/tmp/jsacc uv run jobseeker refilter` (dry run) lists 0 hidden and 0 restored for the owner. Their verdicts are unchanged by the move.
3. Start `uv run jobseeker serve --port 8010` with `/tmp/jsacc` (test OAuth values in a throwaway `.env` there). Using a `client_as`-style session inserted by a one-off script, check on an iPhone-sized viewport (Chrome DevTools, 390×844):
   - onboarding for a new invited user completes in under 3 minutes;
   - leaving at step 3 resumes at step 3;
   - Settings is the 4th tab.
4. The real Google sign-in is checked at deploy time (it needs the Web client).

- [ ] **Step 4: `HANDOFF.md`**: add "Sub-project 3 built", with:
- `config/app.yaml` (copy from `config/app.example.yaml`; v2 writes it);
- the owner's files go in `$JOBSEEKER_HOME/profile/` before `jobseeker migrate`;
- `jobseeker refilter --user`;
- the new test count.

- [ ] **Step 5: Commit** (`test(profile): no runtime profile-file reads; handoff for sub-project 3`, plus the trailer). Then the Native method's final whole-branch review.

---

## Spec coverage (self-review)

| Spec 3 section | Task |
|---|---|
| §3 decisions (blob, `AppConfig`, catalog, 1 custom role, resume rules, facts budget, 4th tab, two-way, export/delete) | 1, 2, 4-8 |
| §4.1 `UserPrefs`/`AppConfig`/`effective_prefs`, optional CTC, checkout paths | 1 |
| §4.2 request-scoped prefs, background tasks take `user_id`, CLI `--user` | 3 |
| §4.3 onboarding steps, `require_onboarded`, Finish, Done polling | 4, 6 |
| §4.4 resume storage/validation, `user_facts`, extraction, budget, manual entry, review | 3, 6 |
| §4.5 Settings sections, nav | 7 |
| §4.6 `reevaluate` (two-way), preview, performance, the refilter CLI | 5, 7 |
| §4.7 export, delete, later-table coverage | 8 |
| §4.8 migration v2 and the golden check | 2 |
| §5 data model | 2 |
| §6 errors | 4, 6, 8 |
| §7 testing | every task |
| §8 acceptance | 9 |

**Clarifications this plan adds** (for the coordinator):
1. **Golden-check detail:** when `title_allow_extra` is set (as the migrated owner's is), it alone is the title allow-list. Catalog `allow` words only apply to users who haven't set explicit extras. Without this rule the owner's matches would widen after migration.
   `UserPrefs` also gains `target_roles_text` (not in spec 3). The owner's target-role prose ("Analytics roles with a product focus", …) isn't the catalog labels, and the scorer prompt prints it. The importer fills `target_roles_text` so the prompt stays byte-identical; new users leave it empty.
2. **Names come from users:** the importer sets `users.name` from `preferences.yaml` when it's empty. `effective_prefs` takes name and email from `users`, so the greeting and signature work before the owner's first Google sign-in.
3. **Spec 2's leftover fixture item lands here:** the "stop copying the real `preferences.yaml`" item from spec 2 §7 is done in Task 1, which uses non-personal fixtures. Four tests asserted personal values and are updated.
4. **No low pre-score cutoff on scored jobs:** `reevaluate` never applies the cutoff to a job the user already has a score for, so a Settings edit can't hide scored jobs that way.
5. **Sign out moves into Settings:** plan 2's interim sidebar and top-bar Sign out are removed; Account in Settings has it.
6. **IST date without `tzdata` yet:** the facts budget day uses `ZoneInfo("Asia/Kolkata")` directly, which works on the Mac's system tz database. Spec 4 adds `tzdata` for Linux.
