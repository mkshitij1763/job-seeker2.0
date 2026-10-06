from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jobseeker_home: Path = Path(".")
    groq_api_key: str = ""

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
    def resume_path(self) -> Path:
        return self.profile_dir / "resume.pdf"

    @property
    def facts_path(self) -> Path:
        return self.profile_dir / "facts.json"

    @property
    def preferences_path(self) -> Path:
        return self.profile_dir / "preferences.yaml"

    @property
    def companies_path(self) -> Path:
        return self.jobseeker_home / "companies.yaml"

    @property
    def rubric_path(self) -> Path:
        return self.jobseeker_home / "rubric.yaml"

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


class Preferences(BaseModel):
    name: str
    email: str
    linkedin: str
    github: str = ""
    experience_summary: str
    target_roles: list[str]
    cities: list[str]
    remote_india_ok: bool = True
    current_ctc_lpa: float
    target_base_lpa: float
    must_haves: list[str] = []
    deal_breakers: list[str] = []
    title_deny: list[str] = []
    title_allow: list[str] = []
    drop_if_min_years_at_least: int = 8
    max_age_days: int = 7
    thresholds: Thresholds = Thresholds()
    budgets: Budgets = Budgets()
    models: Models = Models()


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
