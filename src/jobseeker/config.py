from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]  # the code checkout (…/src/jobseeker/config.py → repo root)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jobseeker_home: Path = Path(".")
    groq_api_key: str = ""
    tavily_api_key: str = ""
    apify_api_token: str = ""
    hunter_api_key: str = ""
    owner_email: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = ""
    secret_key: str = ""
    cookie_secure: bool = True
    gemini_api_key: str = ""
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    backup_dir: Path | None = None
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = ""
    backup_key: str = ""
    backup_s3_endpoint: str = ""
    backup_s3_region: str = ""
    backup_s3_bucket: str = ""
    backup_s3_key_id: str = ""
    backup_s3_secret: str = ""
    healthcheck_ping_url: str = ""

    @property
    def backup_path(self) -> Path:
        """BACKUP_DIR from .env, else iCloud Drive when it's on (survives losing the Mac), else ~/JobSeeker-backups."""
        if self.backup_dir:
            return self.backup_dir
        icloud = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        return (icloud if icloud.is_dir() else Path.home()) / "JobSeeker-backups"

    @property
    def data_dir(self) -> Path:
        return self.jobseeker_home / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobseeker.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def profile_dir(self) -> Path:
        return self.jobseeker_home / "profile"

    @property
    def app_config_path(self) -> Path:
        return self.jobseeker_home / "config" / "app.yaml"

    @property
    def secrets_dir(self) -> Path:
        return self.jobseeker_home / "secrets"


class Thresholds(BaseModel):
    apply: int = 70
    review: int = 50


class Budgets(BaseModel):
    score_per_run: int = 35
    draft_per_run: int = 10


class Models(BaseModel):
    scoring: str = "openai/gpt-oss-20b"
    drafting: str = "openai/gpt-oss-120b"
    facts: str = "openai/gpt-oss-120b"
    # Used in order once a model's free daily quota is gone (Groq quotas are per model).
    fallbacks: dict[str, list[str]] = {
        # Cloudflare's 20b ignores the JSON schema; its 120b follows it.
        "openai/gpt-oss-20b": ["qwen/qwen3.8-27b", "gemini:gemini-3.5-flash-lite", "cloudflare:@cf/openai/gpt-oss-120b"],
        "openai/gpt-oss-120b": ["gemini:gemini-3.5-flash", "cloudflare:@cf/openai/gpt-oss-120b"],
    }


class SearchConfig(BaseModel):
    queries: list[str] = ["Product Analyst", "Associate Product Manager", "Product Manager",
                          "Founder's Office", "Growth Analyst"]
    locations: list[str] = ["Bengaluru", "Gurgaon", "Noida", "Pune"]
    remote_query: bool = True
    hours_old: int = 72
    results_per_search: int = 25
    sites: list[Literal["linkedin", "naukri", "indeed"]] = ["linkedin", "naukri", "indeed"]
    linkedin_descriptions_per_run: int = 15


class ContactsConfig(BaseModel):
    tavily_monthly_limit: int = 950
    apify_monthly_usd_limit: float = 4.5
    hunter_monthly_limit: int = 45
    smtp_daily_limit: int = 60
    smtp_pause_seconds: float = 2.0
    sender_email: str = ""  # SMTP MAIL FROM only (nothing is sent); defaults to Preferences.email


class Preferences(BaseModel):
    name: str
    email: str
    linkedin: str
    github: str = ""
    experience_summary: str
    target_roles: list[str]
    cities: list[str]
    remote_india_ok: bool = True
    current_ctc_lpa: float | None = None
    target_base_lpa: float | None = None
    must_haves: list[str] = []
    deal_breakers: list[str] = []
    title_deny: list[str] = []
    title_allow: list[str] = []
    drop_if_min_years_at_least: float = 8
    max_age_days: int = 7
    thresholds: Thresholds = Thresholds()
    budgets: Budgets = Budgets()
    models: Models = Models()
    search: SearchConfig = SearchConfig()
    min_prescore: int = 30
    contacts: ContactsConfig = ContactsConfig()


class Company(BaseModel):
    name: str
    ats: Literal["greenhouse", "lever", "ashby"]
    slug: str
    tier: int = 2


class Dimension(BaseModel):
    key: str
    max: int
    guidance: str


class Rubric(BaseModel):
    version: str
    dimensions: list[Dimension]


def _yaml(path: Path | str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_preferences(path: Path | str) -> Preferences:
    return Preferences.model_validate(_yaml(path))


def load_companies(path: Path | str) -> list[Company]:
    return [Company.model_validate(c) for c in _yaml(path).get("companies", [])]


def load_rubric(path: Path | str) -> Rubric:
    rubric = Rubric.model_validate(_yaml(path))
    total = sum(d.max for d in rubric.dimensions)
    if total != 100:
        raise ValueError(f"rubric dimensions must sum to 100, got {total}")
    return rubric

class Role(BaseModel):
    label: str
    query: str
    allow: list[str] = []


class AppBudgets(BaseModel):
    score_per_run: int = 80
    draft_per_run: int = 10
    facts_per_user_per_day: int = 3
    facts_per_day: int = 10
    global_scores_per_day: int = 150  # provisional: set from the spike's Groq quota measurement
    global_drafts_per_day: int = 20  # provisional: as above
    score_batch: int = 5
    draft_batch: int = 2


class AppSearch(BaseModel):
    hours_old: int = 72
    results_per_search: int = 25
    sites: list[Literal["linkedin", "naukri", "indeed"]] = ["linkedin", "naukri", "indeed"]
    linkedin_descriptions_per_run: int = 15
    max_searches_per_run: int = 60  # provisional: set from the hosting spike's first week
    max_searches_fetch_now: int = 30
    max_custom_queries: int = 3


class ScheduleConfig(BaseModel):
    daily_at: str = "11:15"
    max_attempts_per_day: int = 2

    @field_validator("daily_at")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        time.fromisoformat(v)  # raises ValueError on 25:99
        return v

    def daily_time(self) -> time:
        return time.fromisoformat(self.daily_at)


class FetchNowConfig(BaseModel):
    min_hours_between_per_user: float = 2
    max_per_day: int = 6


class LockConfig(BaseModel):
    takeover_after_minutes: int = 15


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
    timezone: str = "Asia/Kolkata"
    schedule: ScheduleConfig = ScheduleConfig()
    fetch_now: FetchNowConfig = FetchNowConfig()
    lock: LockConfig = LockConfig()


def load_app_config(path: Path | str) -> AppConfig:
    return AppConfig.model_validate(_yaml(path))


LIST_MAX, ITEM_MAX = 10, 60


class UserPrefs(BaseModel):
    roles: list[str] = []
    custom_role: str = ""
    cities: list[str] = []
    remote_india_ok: bool = True
    where_confirmed: bool = False  # set when the Where step is saved: remote-only counts only once chosen there
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
        if not (self.cities or (self.where_confirmed and self.remote_india_ok)):
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
