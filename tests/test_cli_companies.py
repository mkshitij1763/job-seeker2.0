from datetime import UTC, datetime

from typer.testing import CliRunner

from jobseeker.cli import app
from jobseeker.db.companies import record_company
from jobseeker.db.core import connect


def test_companies_command_lists_groups(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    conn = connect(settings.db_path)
    now = datetime(2026, 10, 7, tzinfo=UTC)
    record_company(conn, "tracxn", "Tracxn", "active", "lever", "tracxn", now)
    record_company(conn, "acme", "Acme", "none", now=now)
    conn.close()
    out = CliRunner().invoke(app, ["companies"]).output
    assert "Boards found (1)" in out and "lever:tracxn" in out
    assert "No board (1)" in out and "Acme" in out


def test_companies_command_empty(settings, monkeypatch):
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    out = CliRunner().invoke(app, ["companies"]).output
    assert "No companies discovered yet" in out
