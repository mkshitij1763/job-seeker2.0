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


def test_serve_host_flag(monkeypatch, settings):
    calls = _capture(monkeypatch, settings)
    result = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--port", "8080"])
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "0.0.0.0", "port": 8080}]


def test_serve_forwarded_allow_ips_from_env(monkeypatch, settings):
    calls = _capture(monkeypatch, settings)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    result = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--proxy-headers"])
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "0.0.0.0", "port": 8000, "proxy_headers": True, "forwarded_allow_ips": "*"}]


def _scheme_seen(kw, client):
    """Run one request through uvicorn's own app wrapping (ProxyHeadersMiddleware when proxy_headers is set) with the
    kwargs serve passed, from `client`, carrying X-Forwarded-Proto: https. Returns the scheme the app saw."""
    import asyncio

    import uvicorn

    seen = {}

    async def inner(scope, receive, send):
        seen["scheme"] = scope["scheme"]

    config = uvicorn.Config(inner, **kw)
    config.load()
    scope = {"type": "http", "scheme": "http", "client": client, "server": ("10.0.0.9", 8000), "path": "/",
             "headers": [(b"x-forwarded-proto", b"https"), (b"x-forwarded-for", b"203.0.113.7")]}
    asyncio.run(config.loaded_app(scope, None, None))
    return seen["scheme"]


def test_forwarded_proto_trusted_from_any_proxy_when_env_is_star(monkeypatch, settings):
    calls = _capture(monkeypatch, settings)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--proxy-headers"])
    assert _scheme_seen(calls[0], ("100.64.0.5", 41234)) == "https"


def test_forwarded_proto_ignored_from_non_local_client_by_default(monkeypatch, settings):
    calls = _capture(monkeypatch, settings)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    CliRunner().invoke(app, ["serve", "--proxy-headers"])
    assert _scheme_seen(calls[0], ("100.64.0.5", 41234)) == "http"
    assert _scheme_seen(calls[0], ("127.0.0.1", 41234)) == "https"
