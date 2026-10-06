import shutil
from pathlib import Path

import pytest

from jobseeker.config import Settings, load_preferences, load_rubric
from jobseeker.profile.facts import Achievement, Facts, Role

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "profile").mkdir()
    shutil.copy(ROOT / "profile" / "preferences.yaml", tmp_path / "profile" / "preferences.yaml")
    shutil.copy(ROOT / "rubric.yaml", tmp_path / "rubric.yaml")
    shutil.copy(ROOT / "companies.yaml", tmp_path / "companies.yaml")
    return tmp_path


@pytest.fixture
def settings(home: Path) -> Settings:
    return Settings(jobseeker_home=home, groq_api_key="test")


@pytest.fixture
def prefs(settings):
    return load_preferences(settings.preferences_path)


@pytest.fixture
def rubric(settings):
    return load_rubric(settings.rubric_path)


@pytest.fixture
def facts() -> Facts:
    return Facts(
        headline="Product Analyst at Inito; IIT Roorkee EE 2025",
        roles=[Role(title="Product Analyst", org="Inito", start="July 2025", end="Present"),
               Role(title="Technology Consultant Intern", org="PwC", start="May 2024", end="July 2024")],
        achievements=[
            Achievement(org="Inito", text="Video-led test instructions cut overdipping errors by 67% across 480K+ tests",
                        metrics=["67%", "480K+"]),
            Achievement(org="Inito", text="LightGBM churn model on 30,000+ users with 84% ROC-AUC",
                        metrics=["30,000+", "84%"]),
            Achievement(org="PwC", text="ERCOT 14-day demand forecast cut MAPE from 7.84% to 6.33%",
                        metrics=["14", "7.84%", "6.33%"]),
        ],
        skills=["SQL", "BigQuery", "Amplitude", "A/B Testing", "Python", "Product Discovery"],
        education=["B.Tech Electrical Engineering, IIT Roorkee, 2021-2025"],
    )
