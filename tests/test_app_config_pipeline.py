from datetime import time

import pytest
from pydantic import ValidationError

from jobseeker.config import AppConfig


def test_defaults():
    cfg = AppConfig()
    assert cfg.timezone == "Asia/Kolkata" and cfg.schedule.daily_time() == time(11, 15)
    assert cfg.schedule.max_attempts_per_day == 2
    assert (cfg.search.max_searches_per_run, cfg.search.max_searches_fetch_now, cfg.search.max_custom_queries) == (60, 30, 3)
    b = cfg.budgets
    assert (b.global_scores_per_day, b.global_drafts_per_day, b.score_per_run, b.draft_per_run,
            b.score_batch, b.draft_batch) == (150, 20, 80, 10, 5, 2)
    assert (cfg.fetch_now.min_hours_between_per_user, cfg.fetch_now.max_per_day) == (2, 6)
    assert cfg.lock.takeover_after_minutes == 15


def test_bad_daily_at_is_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"schedule": {"daily_at": "25:99"}})
