# tests/test_cli_serve.py
from typer.testing import CliRunner

from jobseeker.cli import app


def _capture(monkeypatch, settings):
    calls = []
    monkeypatch.setenv("JOBSEEKER_HOME", str(settings.jobseeker_home))
    monkeypatch.setattr("uvicorn.run", lambda application, **kw: calls.append(kw))
    monkeypatch.setattr("jobseeker.web.app.create_app", lambda s: "APP")
    return calls


def test_serve_default_is_unchanged(monkeypatch, settings):
    calls = _capture(monkeypatch, settings)
    result = CliRunner().invoke(app, ["serve", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "127.0.0.1", "port": 8123}]


def test_serve_proxy_headers_trusts_only_localhost(monkeypatch, settings):
    calls = _capture(monkeypatch, settings)
    result = CliRunner().invoke(app, ["serve", "--proxy-headers"])
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "127.0.0.1", "port": 8000, "proxy_headers": True,
                      "forwarded_allow_ips": "127.0.0.1"}]
