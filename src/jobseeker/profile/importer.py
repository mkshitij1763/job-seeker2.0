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
APP_FIELDS = ("min_prescore", "thresholds")  # golden fields that app.yaml owns


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
                     remote_india_ok=prefs.remote_india_ok, where_confirmed=True,
                     drop_if_min_years_at_least=prefs.drop_if_min_years_at_least,
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
    # Global fields come from app.yaml, and an existing app.yaml is the admin's choice, so only per-user ones must match.
    old = {k: v for k, v in golden_fields(prefs).items() if k not in APP_FIELDS}
    new = {k: v for k, v in golden_fields(eff).items() if k not in APP_FIELDS}
    if new != old:
        diff = {k: (old[k], v) for k, v in new.items() if old[k] != v}
        raise MigrationError(f"v2 golden check failed (original, imported): {diff}")
    conn.execute("""INSERT INTO user_prefs (user_id, data, version, onboarding_step, onboarded_at, updated_at)
                    VALUES (?, ?, 1, NULL, ?, ?)
                    ON CONFLICT (user_id) DO UPDATE SET data = excluded.data, onboarding_step = NULL,
                      onboarded_at = excluded.onboarded_at, updated_at = excluded.updated_at""",
                 (user_id, up.model_dump_json(), ts, ts))
    conn.execute("UPDATE users SET name = ? WHERE id = ? AND name = ''", (prefs.name, user_id))
    report.append("imported preferences.yaml")
    dropped = [q for q in prefs.search.queries if q not in eff.search.queries]
    if dropped:  # only one custom role is searched; the rest still count as title words
        report.append("search queries no longer searched (kept as title words): " + ", ".join(dropped))
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
