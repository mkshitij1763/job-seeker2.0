# tests/test_railway.py
"""The Railway image (Dockerfile, .dockerignore). No docker on the Mac, so these are static checks."""
import re
import tomllib
from pathlib import Path

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


def test_base_image_is_python_313_slim():
    assert _args("FROM")[0].startswith("python:3.13-slim")


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
    assert _args("USER") == []


def test_dockerignore_keeps_secrets_and_local_state_out():
    lines = {ln.strip() for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")}
    for entry in (".env", "secrets/", "data/", "profile/resume.pdf", "profile/facts.json", ".venv", ".git"):
        assert entry in lines, entry
    # The image needs these; ignoring them would break the build.
    for needed in ("src", "uv.lock", "companies.yaml", "rubric.yaml", "config", "scripts"):
        assert needed not in lines and f"{needed}/" not in lines, needed
