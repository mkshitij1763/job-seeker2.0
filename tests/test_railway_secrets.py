# tests/test_railway_secrets.py
"""scripts/railway/set-secrets.sh, run under bash with stub `railway` and `jobseeker` on PATH."""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "railway" / "set-secrets.sh"

PROMPTED = ["GOOGLE_CLIENT_SECRET", "BACKUP_S3_KEY_ID", "BACKUP_S3_SECRET", "GROQ_API_KEY", "TAVILY_API_KEY",
            "GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN", "APIFY_API_TOKEN", "HUNTER_API_KEY", "HEALTHCHECK_PING_URL"]
GENERATED = ["SECRET_KEY", "TOKEN_KEY", "BACKUP_KEY", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY"]

RAILWAY_STUB = """#!/bin/bash
echo "$*" >> "$STUB_LOG"
case "$1 $2" in
  "status "*) exit "${STATUS_EXIT:-0}" ;;
  "variable list") cat "$STUB_VARS" ;;
  "variable set") printf '%s=%s\\n' "$3" "$(cat)" >> "$STUB_LOG.values"; exit "${SET_EXIT:-0}" ;;
esac
"""
JOBSEEKER_STUB = """#!/bin/bash
case "$1" in
  gen-key) n=$(( $(cat "$STUB_LOG.n" 2>/dev/null || echo 0) + 1 )); echo $n > "$STUB_LOG.n"; echo "genkey-$n" ;;
  vapid-keys) printf 'VAPID_PRIVATE_KEY=vapid-priv\\nVAPID_PUBLIC_KEY=vapid-pub\\nVAPID_SUBJECT=mailto:x@y\\n' ;;
esac
"""


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("railway", RAILWAY_STUB), ("jobseeker", JOBSEEKER_STUB)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    stub_vars = tmp_path / "vars.json"

    def go(answers=None, existing=None, **env):
        stub_vars.write_text(json.dumps(existing or {"OWNER_EMAIL": "o@x", "RAILWAY_PUBLIC_DOMAIN": "d"}))
        answers = answers or {}
        stdin = "".join(f"{answers.get(k, '')}\n" for k in PROMPTED)
        full = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "STUB_LOG": str(log),
                "STUB_VARS": str(stub_vars), **env}
        p = subprocess.run(["bash", str(SCRIPT)], input=stdin, env=full, capture_output=True, text=True, timeout=20)
        values = log.with_name("calls.log.values")
        got = dict(ln.split("=", 1) for ln in values.read_text().splitlines()) if values.exists() else {}
        return p, log.read_text().splitlines(), got

    return go


def test_set_secrets_parses():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_fresh_service_gets_generated_keys_and_the_answers_without_echoing_them(run):
    p, calls, got = run(answers={"GOOGLE_CLIENT_SECRET": "gcs-123", "BACKUP_S3_KEY_ID": "kid-9",
                                 "BACKUP_S3_SECRET": "b2s-77", "GROQ_API_KEY": "groq-5"})
    assert p.returncode == 0, p.stderr
    assert got == {"SECRET_KEY": "genkey-1", "TOKEN_KEY": "genkey-2", "BACKUP_KEY": "genkey-3",
                   "VAPID_PRIVATE_KEY": "vapid-priv", "VAPID_PUBLIC_KEY": "vapid-pub",
                   "GOOGLE_CLIENT_SECRET": "gcs-123", "BACKUP_S3_KEY_ID": "kid-9", "BACKUP_S3_SECRET": "b2s-77",
                   "GROQ_API_KEY": "groq-5"}
    sets = [c for c in calls if c.startswith("variable set")]
    assert len(sets) == len(got)
    for c in sets:
        # The value goes over stdin, never argv (visible in ps); no deploy per variable.
        assert "--stdin" in c and "--skip-deploys" in c and "--service job-seeker2.0" in c, c
        assert "=" not in c, c
    shown = p.stdout + p.stderr
    for v in got.values():
        assert v not in shown, v
    assert "BACKUP_KEY" in shown and "TOKEN_KEY" in shown and "password manager" in shown


def test_keys_already_on_the_service_are_never_regenerated(run):
    existing = {k: None for k in GENERATED} | {"GROQ_API_KEY": None}
    p, calls, got = run(existing=existing, answers={"TAVILY_API_KEY": "tv-1"})
    assert p.returncode == 0, p.stderr
    # Rotating TOKEN_KEY or BACKUP_KEY would orphan every stored Gmail token and every B2 backup.
    assert got == {"TAVILY_API_KEY": "tv-1"}
    assert "already set" in p.stdout


def test_variable_list_as_a_list_of_names_also_works(run):
    existing = [{"name": k} for k in GENERATED]
    p, _, got = run(existing=existing)
    assert p.returncode == 0, p.stderr
    assert got == {}


def test_half_a_vapid_pair_stops_before_setting_anything(run):
    p, calls, got = run(existing={"VAPID_PUBLIC_KEY": None})
    assert p.returncode == 1
    assert got == {}
    assert "VAPID" in p.stderr


def test_unlinked_directory_stops_with_a_hint(run):
    p, calls, got = run(STATUS_EXIT="1")
    assert p.returncode == 1
    assert "railway link" in p.stderr
    assert got == {} and not any(c.startswith("variable") for c in calls)


def test_a_failed_set_is_reported_and_the_exit_is_nonzero(run):
    p, _, got = run(SET_EXIT="1")
    assert p.returncode == 1
    assert "SECRET_KEY" in p.stderr and "genkey-1" not in p.stderr + p.stdout


def test_service_and_environment_can_be_overridden(run):
    p, calls, _ = run(RAILWAY_SERVICE="other", RAILWAY_ENVIRONMENT="staging")
    assert p.returncode == 0, p.stderr
    sets = [c for c in calls if c.startswith("variable")]
    assert sets and all("--service other" in c and "--environment staging" in c for c in sets)
