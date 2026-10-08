# tests/test_server_scripts.py
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "server"
REQUIRED = ["SECRET_KEY", "OWNER_EMAIL", "BASE_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_KEY"]


def sh(args, env=None, cwd=ROOT):
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    return subprocess.run(args, capture_output=True, text=True, env={**base, **(env or {})}, cwd=cwd, timeout=30)


@pytest.mark.parametrize("script", ["ready.sh", "js", "bootstrap.sh", "update.sh", "../deploy.sh"])
def test_scripts_parse(script):
    path = SERVER / script
    if not path.exists():
        pytest.skip(f"{script} arrives in a later task")
    assert sh(["bash", "-n", str(path)]).returncode == 0
    if shutil.which("shellcheck"):
        result = sh(["shellcheck", "-S", "warning", str(path)])
        assert result.returncode == 0, result.stdout


def _home(tmp_path, env_text, db=True, app_yaml=True):
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    if db:
        (tmp_path / "data" / "jobseeker.db").write_bytes(b"")
    if app_yaml:
        (tmp_path / "config" / "app.yaml").write_text("{}", encoding="utf-8")
    return tmp_path


def test_ready_when_everything_is_set(tmp_path):
    home = _home(tmp_path, "".join(f"{n}=x\n" for n in REQUIRED))
    result = sh(["bash", str(SERVER / "ready.sh"), str(home)])
    assert result.returncode == 0 and result.stdout == ""


def test_ready_reports_empty_values(tmp_path):
    home = _home(tmp_path, "".join(f"{n}=x\n" for n in REQUIRED if n != "TOKEN_KEY") + "TOKEN_KEY=\n")
    result = sh(["bash", str(SERVER / "ready.sh"), str(home)])
    assert result.returncode == 1 and result.stdout.splitlines() == ["missing: TOKEN_KEY"]


def test_ready_reports_missing_files(tmp_path):
    home = _home(tmp_path, "".join(f"{n}=x\n" for n in REQUIRED), db=False, app_yaml=False)
    result = sh(["bash", str(SERVER / "ready.sh"), str(home)])
    assert result.returncode == 1
    assert result.stdout.splitlines() == ["missing: data/jobseeker.db", "missing: config/app.yaml"]


def test_ready_never_prints_values(tmp_path):
    home = _home(tmp_path, "SECRET_KEY=super-secret-value\n")
    assert "super-secret-value" not in sh(["bash", str(SERVER / "ready.sh"), str(home)]).stdout


@pytest.mark.parametrize("env,message", [
    ({}, "BASE_URL is required"),
    ({"BASE_URL": "http://x.duckdns.org", "OWNER_EMAIL": "a@b.c", "BRANCH": "multi-user"},
     "BASE_URL must start with https://"),
    ({"BASE_URL": "https://x.duckdns.org", "BRANCH": "multi-user"}, "OWNER_EMAIL is required"),
    ({"BASE_URL": "https://x.duckdns.org", "OWNER_EMAIL": "a@b.c"}, "BRANCH is required"),
])
def test_bootstrap_refuses_bad_input_before_doing_anything(env, message):
    result = sh(["bash", str(SERVER / "bootstrap.sh")], env=env)
    assert result.returncode == 1 and message in result.stderr


def test_bootstrap_refuses_non_root():
    if os.geteuid() == 0:
        pytest.skip("running as root")
    env = {"BASE_URL": "https://x.duckdns.org", "OWNER_EMAIL": "a@b.c", "BRANCH": "multi-user"}
    result = sh(["bash", str(SERVER / "bootstrap.sh")], env=env)
    assert result.returncode == 1 and "Run as root" in result.stderr


def test_bootstrap_never_copies_checkout_config_into_home():
    text = (SERVER / "bootstrap.sh").read_text(encoding="utf-8")
    assert "companies.yaml" not in text and "rubric.yaml" not in text
