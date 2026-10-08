# tests/test_deploy.py
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB_SSH = """#!/usr/bin/env bash
# Test stub for ssh: run the remote command locally, without sudo. $1 = host, $2 = remote command.
cmd=$2
exec bash -c "${cmd#sudo }"
"""


def deploy(tmp_path, *args, **dry):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "ssh").write_text(STUB_SSH)
    (bin_dir / "ssh").chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "DRY_OLD": "old0000"}
    env.update({k: str(v) for k, v in dry.items()})
    result = subprocess.run(["bash", str(ROOT / "scripts/deploy.sh"), "--dry-run", "--host", "fake", *args],
                            capture_output=True, text=True, env=env, cwd=ROOT, timeout=30)
    commands = [ln[2:] for ln in result.stdout.splitlines() if ln.startswith("+ ")]
    return result, commands


def in_order(commands, *needles):
    pos = 0
    for needle in needles:
        while pos < len(commands) and needle not in commands[pos]:
            pos += 1
        assert pos < len(commands), f"{needle!r} not found in order in {commands}"
        pos += 1


def test_deploy_dry_run_sequence(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234")
    assert result.returncode == 0, result.stderr
    in_order(commands, "systemctl is-active --quiet jobseeker-tick.service", "systemctl stop jobseeker-tick.timer",
             "git checkout -q --detach abc1234", "uv sync --frozen", "systemctl stop jobseeker-web",
             "js migrate", "deploy.log", "systemctl start jobseeker-web", "/healthz",
             "systemctl start jobseeker-tick.timer")
    assert "Deployed abc1234" in result.stdout


def test_deploy_refuses_while_tick_runs(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_TICK_RUNNING=1)
    assert result.returncode == 2 and "A run is in progress" in result.stderr
    assert not any("systemctl stop" in c or "git checkout" in c for c in commands)


def test_failed_health_rolls_code_back(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_FAIL="/healthz")
    assert result.returncode == 1
    in_order(commands, "git checkout -q --detach abc1234", "/healthz", "git checkout -q --detach old0000",
             "uv sync --frozen", "systemctl start jobseeker-web", "systemctl start jobseeker-tick.timer",
             "journalctl -u jobseeker-web")
    assert "rolled back to old0000" in result.stderr


def test_failed_health_after_migration_prints_restore_steps(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_FAIL="/healthz", DRY_UV_BEFORE=4, DRY_UV_AFTER=5)
    assert result.returncode == 1
    assert not any("--detach old0000" in c for c in commands)
    assert "schema changed (user_version 4 -> 5)" in result.stderr and "pre-migrate-v4" in result.stderr


def test_failed_migrate_with_unchanged_schema_restarts_old_code(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_FAIL="js migrate")
    assert result.returncode == 1
    in_order(commands, "js migrate", "git checkout -q --detach old0000", "systemctl start jobseeker-web")


def test_rollback_redeploys_previous_sha(tmp_path):
    result, commands = deploy(tmp_path, "--rollback", DRY_PREV="prev999")
    assert result.returncode == 0, result.stderr
    in_order(commands, "git checkout -q --detach prev999", "systemctl start jobseeker-tick.timer")


def test_rollback_without_log(tmp_path):
    result, commands = deploy(tmp_path, "--rollback", DRY_PREV="")
    assert result.returncode == 1 and "No previous deploy recorded" in result.stderr
    assert not any("systemctl stop" in c for c in commands)


def test_unknown_option(tmp_path):
    result, _ = deploy(tmp_path, "--bogus")
    assert result.returncode == 2 and "Unknown option: --bogus" in result.stderr
