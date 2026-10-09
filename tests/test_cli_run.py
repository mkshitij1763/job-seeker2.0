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
