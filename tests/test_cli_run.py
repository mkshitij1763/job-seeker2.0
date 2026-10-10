from datetime import UTC, datetime

from typer.testing import CliRunner

from jobseeker.cli import app
from jobseeker.db.core import connect
from jobseeker.db.locks import acquire


def test_cli_run_refuses_when_locked(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    conn = connect(settings.db_path)
    acquire(conn, "run", "other:2", datetime.now(UTC), 15)
    result = CliRunner().invoke(app, ["run"])
    assert result.exit_code == 1 and "A run is in progress since" in result.output


def test_tick_command_exits_zero_when_busy(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    acquire(connect(settings.db_path), "run", "other:2", datetime.now(UTC), 15)
    result = CliRunner().invoke(app, ["tick"])
    assert result.exit_code == 0 and "busy" in result.output


def test_runner_never_fetches_for_an_onboarding_run(settings, monkeypatch):
    from contextlib import nullcontext

    import jobseeker.cli as cli
    seen = []
    monkeypatch.setattr(cli, "_pipeline", lambda s, c: (None, [], None))
    monkeypatch.setattr("jobseeker.sources.http.make_client", lambda: nullcontext(None))
    monkeypatch.setattr("jobseeker.pipeline.run.run_all", lambda conn, **kw: seen.append((kw["trigger"], kw["fetch"])))
    _, run = cli._runner(settings, connect(settings.db_path), datetime.now(UTC), "me:1")
    run("onboarding", [], 30)
    run("fetch_now", [], 30)
    assert seen == [("onboarding", False), ("fetch_now", True)]
