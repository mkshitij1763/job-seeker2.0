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


def _sshd_block(tmp_path, sshd_ok: bool):
    """Run bootstrap.sh's sshd block with stubs: the drop-in dir is redirected to tmp_path, sshd -t passes or fails."""
    text = (SERVER / "bootstrap.sh").read_text(encoding="utf-8")
    block = text.split("# --- sshd hardening ---", 1)[1].split("# --- end sshd hardening ---", 1)[0]
    d = tmp_path / "sshd_config.d"
    d.mkdir()
    (d / "jobseeker.conf").write_text("old name")
    log = tmp_path / "calls"
    script = f"""set -euo pipefail
put_file() {{ cat > "$1"; }}
render() {{ echo "PasswordAuthentication no"; }}
sshd() {{ echo "sshd $*" >> {log}; return {0 if sshd_ok else 1}; }}
systemctl() {{ echo "systemctl $*" >> {log}; }}
{block.replace("/etc/ssh/sshd_config.d", str(d))}
echo reached-end
"""
    result = sh(["bash", "-c", script])
    return result, d, (log.read_text() if log.exists() else "")


def test_sshd_dropin_sorts_first_and_reloads_when_valid(tmp_path):
    result, d, calls = _sshd_block(tmp_path, sshd_ok=True)
    assert result.returncode == 0 and "reached-end" in result.stdout
    assert sorted(p.name for p in d.iterdir()) == ["00-jobseeker.conf"]  # the pre-review name is gone
    assert "sshd -t" in calls and "systemctl reload ssh" in calls


def test_sshd_dropin_is_removed_and_bootstrap_stops_when_sshd_t_fails(tmp_path):
    result, d, calls = _sshd_block(tmp_path, sshd_ok=False)
    assert result.returncode != 0 and "reached-end" not in result.stdout
    assert list(d.iterdir()) == []
    assert "systemctl" not in calls and "removed" in result.stderr


def _swap_block(tmp_path, active: bool):
    """Run bootstrap.sh's swap block with stubs; /swapfile, /etc/fstab and /etc/sysctl.d are redirected to tmp_path.
    Call it again on the same tmp_path to model a re-run of bootstrap on the same machine."""
    text = (SERVER / "bootstrap.sh").read_text(encoding="utf-8")
    block = text.split("# --- swap ---", 1)[1].split("# --- end swap ---", 1)[0]
    swapfile, fstab, sysctl_d, log = tmp_path / "swapfile", tmp_path / "fstab", tmp_path / "sysctl.d", tmp_path / "calls"
    fstab.touch()
    for path, new in (("/swapfile", swapfile), ("/etc/fstab", fstab), ("/etc/sysctl.d", sysctl_d)):
        block = block.replace(path, str(new))
    script = f"""set -euo pipefail
CHANGED=0
put_file() {{ [[ -f $1 ]] && cmp -s - "$1" && return 1; mkdir -p "$(dirname "$1")"; cat > "$1"; }}
fallocate() {{ echo "fallocate $*" >> {log}; touch "${{@: -1}}"; }}
mkswap() {{ echo "mkswap $*" >> {log}; }}
swapon() {{ if [[ $1 == --show* ]]; then {"echo " + str(swapfile) if active else "true"}; else echo "swapon $*" >> {log}; fi; }}
sysctl() {{ echo "sysctl $*" >> {log}; }}
{block}
echo "CHANGED=$CHANGED"
"""
    result = sh(["bash", "-c", script])
    return result, (log.read_text() if log.exists() else "")


def test_swap_is_made_once_and_persisted(tmp_path):
    result, calls = _swap_block(tmp_path, active=False)
    assert result.returncode == 0, result.stderr
    assert "fallocate -l 2G" in calls and "mkswap" in calls and "swapon " in calls and "sysctl" in calls
    assert oct((tmp_path / "swapfile").stat().st_mode & 0o777) == "0o600"
    assert (tmp_path / "fstab").read_text().count("swapfile none swap sw 0 0") == 1
    assert (tmp_path / "sysctl.d" / "90-jobseeker-swap.conf").read_text().strip() == "vm.swappiness=10"
    assert "CHANGED=1" in result.stdout


def test_swap_rerun_changes_nothing(tmp_path):
    _swap_block(tmp_path, active=False)
    again, calls = _swap_block(tmp_path, active=True)
    assert again.returncode == 0, again.stderr
    assert calls.count("fallocate") == 1 and calls.count("mkswap") == 1 and calls.count("swapon ") == 1
    assert (tmp_path / "fstab").read_text().count("none swap sw 0 0") == 1
    assert "CHANGED=0" in again.stdout
