from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from jobseeker.db.core import connect
from jobseeker.db.profile import save_facts, set_extract_status
from jobseeker.db.usage import Budget, Limit
from jobseeker.llm import LLMError, LLMQuotaExceeded, LLMUnavailable
from jobseeker.profile.facts import extract_facts
from jobseeker.profile.resume import resume_path, validate_pdf

IST = ZoneInfo("Asia/Kolkata")
READ_FAILED = "Couldn't read your resume right now. Enter your skills yourself, or upload it again later."
log = logging.getLogger(__name__)


def facts_limits(cfg) -> dict[str, Limit]:
    return {"groq:facts": Limit("day", cfg.budgets.facts_per_day, cfg.budgets.facts_per_user_per_day)}


def run_extract(db_path, home, user_id: int, sha: str, app_config, llm_factory) -> None:
    conn = connect(db_path)
    try:
        budget = Budget(conn, user_id, facts_limits(app_config), datetime.now(IST))
        if not budget.take("groq:facts"):
            set_extract_status(conn, user_id, "failed",
                               "You can re-read your resume again tomorrow; your current facts stay.")
            return
        data = resume_path(home, user_id).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:  # the file changed since this read was queued
            set_extract_status(conn, user_id, "failed", "Your resume changed while we were reading it. Upload it again.")
            return
        text = validate_pdf(data, "application/pdf")
        try:
            facts = extract_facts(llm_factory(), text, app_config.models.facts)
        except (LLMQuotaExceeded, LLMUnavailable):
            set_extract_status(conn, user_id, "failed", "AI limit reached for today.")
            return
        except LLMError as e:  # a bad key or a malformed reply: log it, never show provider text to the user
            log.warning("fact extraction failed for user %s: %s", user_id, e)
            set_extract_status(conn, user_id, "failed", READ_FAILED)
            return
        save_facts(conn, user_id, sha, facts, edited=False, now=datetime.now(IST))
    except Exception:  # the page must always leave the running state
        log.exception("fact extraction crashed for user %s", user_id)
        set_extract_status(conn, user_id, "failed", READ_FAILED)
    finally:
        conn.close()
