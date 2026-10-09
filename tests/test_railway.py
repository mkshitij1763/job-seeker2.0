# tests/test_railway.py
"""The Railway image (Dockerfile, .dockerignore). No docker on the Mac, so these are static checks."""
import json
import os
import re
import signal
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def _instructions():
    """(INSTRUCTION, args) pairs, with backslash continuations joined and comments dropped."""
    text = re.sub(r"\\\n", " ", DOCKERFILE.read_text(encoding="utf-8"))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return [(ln.split(None, 1)[0].upper(), ln.split(None, 1)[1] if " " in ln else "") for ln in lines]


def _args(kind):
    return [a for k, a in _instructions() if k == kind]


def test_base_image_is_python_313_slim_from_a_mirror_without_docker_hub_limits():
    # Docker Hub rate-limits anonymous pulls per IP, and Railway's shared builders hit it (429 on 2026-10-10).
    # AWS's public ECR mirror serves the same official image.
    assert _args("FROM")[0].startswith("public.ecr.aws/docker/library/python:3.13-slim")


def test_railway_json_pins_the_dockerfile_builder():
    # The service setting once flipped back to Railpack, which can't start this app ("No start command detected").
    # Config-as-code in the repo overrides the dashboard.
    cfg = json.loads((ROOT / "railway.json").read_text())
    assert cfg["build"] == {"builder": "DOCKERFILE", "dockerfilePath": "Dockerfile"}


def test_uv_is_pinned_inside_uv_build_range():
    # pyproject's build backend is uv_build>=0.11,<0.12; the image's uv must be an exact 0.11.x.
    build_req = tomllib.loads((ROOT / "pyproject.toml").read_text())["build-system"]["requires"][0]
    assert build_req == "uv_build>=0.11.0,<0.12.0"
    uv_copy = [a for a in _args("COPY") if "astral-sh/uv" in a]
    assert len(uv_copy) == 1
    assert re.search(r"ghcr\.io/astral-sh/uv:0\.11\.\d+ ", uv_copy[0]), uv_copy[0]


def test_sync_is_frozen_and_skips_dev_deps():
    syncs = [a for a in _args("RUN") if "uv sync" in a]
    assert syncs, "no uv sync"
    for a in syncs:
        assert "--frozen" in a and "--no-dev" in a, a
        # REPO_ROOT is parents[2] of src/jobseeker/config.py, so the project must stay an editable install in /app.
        assert "--no-editable" not in a, a


def test_repo_root_files_the_code_reads_are_copied():
    # config.py: REPO_ROOT/companies.yaml, REPO_ROOT/rubric.yaml; importer.py: REPO_ROOT/config/app.example.yaml.
    copied = " ".join(_args("COPY"))
    for path in ("companies.yaml", "rubric.yaml", "config/app.example.yaml", "src", "uv.lock", "pyproject.toml",
                 "README.md", "scripts/railway/start.sh"):
        assert re.search(rf"(^|\s){re.escape(path)}(\s|$)", copied), path
    assert _args("WORKDIR") == ["/app"]


def test_nothing_secret_or_personal_is_copied():
    copied = " ".join(_args("COPY"))
    for bad in (".env", "secrets", "data", "profile", " . "):
        assert bad not in f" {copied} ".replace(".env.example", ""), bad


def test_runtime_env_and_command():
    env = " ".join(_args("ENV"))
    assert "JOBSEEKER_HOME=/data" in env
    assert "/app/.venv/bin" in env
    cmd = _args("CMD")
    assert cmd == ['["/app/scripts/railway/start.sh"]']
    assert "uv run" not in DOCKERFILE.read_text(encoding="utf-8")


def test_app_user_exists_and_the_image_does_not_switch_to_it():
    # Railway mounts the volume root-owned: start.sh starts as root, chowns /data, then drops to `app` with setpriv.
    runs = " ".join(_args("RUN"))
    assert re.search(r"useradd\b.*\bapp\b", runs)
    assert "setpriv --version" in runs and "timeout --version" in runs  # start.sh's tools, checked at build time
    assert _args("USER") == []


def test_dockerignore_keeps_secrets_and_local_state_out():
    lines = {ln.strip() for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")}
    for entry in (".env", "secrets/", "data/", "profile/resume.pdf", "profile/facts.json", ".venv", ".git"):
        assert entry in lines, entry
    # The image needs these; ignoring them would break the build.
    for needed in ("src", "uv.lock", "companies.yaml", "rubric.yaml", "config", "scripts"):
        assert needed not in lines and f"{needed}/" not in lines, needed


# --- scripts/railway/start.sh, run under bash with stub `jobseeker` and `timeout` on PATH (no docker, timeout or
# setpriv on the Mac). The tests run as a normal user, so the root branch (chown + setpriv) is checked statically.
START = ROOT / "scripts" / "railway" / "start.sh"

JOBSEEKER_STUB = """#!/bin/bash
echo "$*" >> "$STUB_LOG"
case "$1" in
  migrate) exit "${MIGRATE_EXIT:-0}" ;;
  tick) echo $$ >> "$STUB_LOG.tickpids"; sleep "${TICK_SLEEP:-0}"; exit "${TICK_EXIT:-0}" ;;
  serve) echo $$ > "$STUB_LOG.servepid"; trap 'exit 0' TERM; sleep "${SERVE_SLEEP:-60}" & wait $!; exit "${SERVE_EXIT:-0}" ;;
esac
"""
TIMEOUT_STUB = """#!/bin/bash
echo "$1" >> "$STUB_LOG.timeouts"
shift
exec "$@"
"""


@pytest.fixture
def railway(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("jobseeker", JOBSEEKER_STUB), ("timeout", TIMEOUT_STUB)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    home = tmp_path / "data"
    home.mkdir()
    log = tmp_path / "calls.log"
    log.touch()
    procs = []

    def start(db=True, **env):
        if db:
            (home / "data").mkdir(exist_ok=True)
            (home / "data" / "jobseeker.db").write_bytes(b"")
        full = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "JOBSEEKER_HOME": str(home),
                "STUB_LOG": str(log), "PORT": "8123", "TICK_INTERVAL": "0.2", **env}
        # Output goes to a file, not a pipe: the stubs' stray `sleep`s would hold a pipe open after the script exits.
        out = open(tmp_path / f"out{len(procs)}.txt", "w+")
        p = subprocess.Popen(["bash", str(START)], env=full, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)
        p.out = out
        procs.append(p)
        return p

    def calls():
        return log.read_text().splitlines()

    yield start, calls, log, home
    for p in procs:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)


def _wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _output(p):
    p.out.seek(0)
    return p.out.read()


def _stop(p, timeout=5):
    p.send_signal(signal.SIGTERM)
    p.wait(timeout=timeout)
    return p.returncode, _output(p)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_start_sh_parses():
    assert subprocess.run(["bash", "-n", str(START)]).returncode == 0


def test_without_a_database_it_waits_instead_of_crash_looping(railway):
    start, calls, _, home = railway
    p = start(db=False, PARK_LOG_INTERVAL="0.2")
    time.sleep(0.9)
    assert p.poll() is None, "exited: Railway would restart it in a loop"
    assert calls() == []
    code, out = _stop(p)
    assert code == 0
    # Repeated, so a parked container is obvious in Railway's logs at any time, not only at boot.
    assert out.count(f"start.sh: PARKED: waiting for restore at {home}") >= 3, out


def test_migrates_then_serves_on_railways_port_and_ticks(railway):
    start, calls, log, _ = railway
    p = start()
    assert _wait_for(lambda: sum(c == "tick" for c in calls()) >= 2), calls()
    assert calls()[0] == "migrate"
    assert "serve --host 0.0.0.0 --port 8123 --proxy-headers" in calls()
    assert set(log.with_name("calls.log.timeouts").read_text().split()) == {"3h"}
    code, _ = _stop(p)
    assert code == 0


def test_backup_dir_defaults_under_the_volume(railway, tmp_path):
    start, calls, _, home = railway
    stub = tmp_path / "bin" / "jobseeker"
    stub.write_text(JOBSEEKER_STUB.replace('echo "$*" >> "$STUB_LOG"', 'echo "$* BACKUP_DIR=$BACKUP_DIR" >> "$STUB_LOG"'))
    p = start()
    assert _wait_for(lambda: any(c.startswith("migrate") for c in calls()))
    assert calls()[0] == f"migrate BACKUP_DIR={home}/backups"
    _stop(p)


def test_a_failing_tick_is_logged_and_the_loop_continues(railway):
    start, calls, _, _ = railway
    p = start(TICK_EXIT="3")
    assert _wait_for(lambda: sum(c == "tick" for c in calls()) >= 3), calls()
    assert p.poll() is None
    _, out = _stop(p)
    assert "tick failed (exit 3)" in out


def test_sigterm_stops_serve_and_a_running_tick(railway):
    start, calls, log, _ = railway
    p = start(TICK_SLEEP="30")
    assert _wait_for(lambda: log.with_name("calls.log.tickpids").exists() and
                     log.with_name("calls.log.servepid").exists())
    tick_pid = int(log.with_name("calls.log.tickpids").read_text().split()[0])
    serve_pid = int(log.with_name("calls.log.servepid").read_text())
    t0 = time.monotonic()
    code, _ = _stop(p)
    assert code == 0 and time.monotonic() - t0 < 4
    assert _wait_for(lambda: not _alive(tick_pid) and not _alive(serve_pid), 3)


def test_if_serve_dies_the_script_exits_nonzero_and_stops_the_loop(railway):
    start, calls, log, _ = railway
    p = start(SERVE_SLEEP="0.5", SERVE_EXIT="1", TICK_SLEEP="30")
    p.wait(timeout=5)
    assert p.returncode != 0
    tick_pid = int(log.with_name("calls.log.tickpids").read_text().split()[0])
    assert _wait_for(lambda: not _alive(tick_pid), 3)


def test_a_failed_migrate_parks_instead_of_serving(railway):
    start, calls, _, _ = railway
    p = start(MIGRATE_EXIT="1", PARK_LOG_INTERVAL="0.2")
    time.sleep(0.9)
    assert p.poll() is None
    assert calls() == ["migrate"]
    code, out = _stop(p)
    assert code == 0
    assert out.count("start.sh: PARKED: migrate failed") >= 3, out


def test_root_branch_chowns_the_volume_and_drops_to_app():
    text = START.read_text(encoding="utf-8")
    root = text[text.index('if [ "$(id -u)" = 0 ]'):]
    root = root[:root.index("\nfi\n")]
    assert 'chown -R app:app "$JOBSEEKER_HOME"' in root
    assert re.search(r'exec setpriv --reuid=app --regid=app --init-groups -- (bash )?"\$0"', root)
    assert "wait -n" not in text  # the Mac's test bash is 3.2
    assert "uv run" not in text
