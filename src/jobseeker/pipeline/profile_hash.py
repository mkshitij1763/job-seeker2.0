"""Fingerprint of everything the score prompt reads about the user, so edits re-score jobs best-first."""
from __future__ import annotations

import hashlib
import json

from jobseeker.config import Preferences
from jobseeker.profile.facts import Facts


def profile_hash(prefs: Preferences, facts: Facts) -> str:
    data = {
        "experience_summary": prefs.experience_summary,
        "target_roles": sorted(prefs.target_roles),
        "cities": sorted(prefs.cities),
        "remote_india_ok": prefs.remote_india_ok,
        "current_ctc_lpa": prefs.current_ctc_lpa,
        "target_base_lpa": prefs.target_base_lpa,
        "must_haves": sorted(prefs.must_haves),
        "deal_breakers": sorted(prefs.deal_breakers),
        "facts": facts.model_dump(),
    }
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()
