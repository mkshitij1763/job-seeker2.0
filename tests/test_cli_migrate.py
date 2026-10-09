import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from jobseeker.cli import app
from jobseeker.config import REPO_ROOT, Settings
from jobseeker.web.app import create_app

from tests.conftest import AUTH_TEST


def _env(monkeypatch, home):
    monkeypatch.setenv("JOBSEEKER_HOME", str(home))
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")


def test_fresh_home_init_then_migrate_writes_app_yaml_and_the_app_starts(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    init = CliRunner().invoke(app, ["init"])
    assert init.exit_code == 0, init.output
    out = CliRunner().invoke(app, ["migrate"])
    assert out.exit_code == 0, out.output
    path = tmp_path / "config" / "app.yaml"
    assert path.exists() and "config/app.yaml" in out.output
    assert yaml.safe_load(path.read_text()) == yaml.safe_load((REPO_ROOT / "config/app.example.yaml").read_text())
    with TestClient(create_app(Settings(jobseeker_home=tmp_path, groq_api_key="test", **AUTH_TEST))) as c:
        assert c.get("/healthz").status_code == 200


def test_migrate_never_overwrites_an_existing_app_yaml(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    CliRunner().invoke(app, ["init"])
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.yaml").write_text("# mine\n")
    out = CliRunner().invoke(app, ["migrate"])
    assert out.exit_code == 0, out.output
    assert (tmp_path / "config" / "app.yaml").read_text() == "# mine\n"


def test_dry_run_writes_no_app_yaml(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    CliRunner().invoke(app, ["init"])
    assert CliRunner().invoke(app, ["migrate", "--dry-run"]).exit_code == 0
    assert not (tmp_path / "config" / "app.yaml").exists()


def test_init_message_matches_what_migrate_does(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    out = CliRunner().invoke(app, ["init"]).output
    assert "config/app.yaml" in out and "if it's missing" in out
