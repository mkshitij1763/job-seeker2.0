import shutil
from pathlib import Path

import pytest

from jobseeker.config import Settings, load_preferences, load_rubric

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
