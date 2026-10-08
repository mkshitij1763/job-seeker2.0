from __future__ import annotations

import json

import typer

from jobseeker.config import Settings, load_companies, load_preferences, load_rubric
from jobseeker.db.core import connect
from jobseeker.llm import FallbackLLM, build_llm

app = typer.Typer(no_args_is_help=True, help="Personal job search and outreach assistant.")


def _load():
    settings = Settings()
    return settings, load_preferences(settings.preferences_path), load_rubric(settings.rubric_path)


@app.command()
def init() -> None:
    """Create folders and the database, and extract resume facts."""
    from jobseeker.profile.facts import load_or_build_facts

    settings, prefs, _ = _load()
    for d in (settings.data_dir, settings.logs_dir, settings.secrets_dir):
        d.mkdir(parents=True, exist_ok=True)
    connect(settings.db_path).close()
    if not settings.resume_path.exists():
        typer.echo(f"Put your resume at {settings.resume_path} and run `jobseeker init` again.")
        raise typer.Exit(1)
    facts = load_or_build_facts(FallbackLLM(build_llm(settings), prefs.models.fallbacks), settings.resume_path,
                                settings.facts_path, prefs.models.facts)
    typer.echo(f"Facts written to {settings.facts_path}: {len(facts.achievements)} achievements, "
               f"{len(facts.skills)} skills. Review and edit that file if anything is wrong.")


def _run(fetch: bool, force: bool) -> None:
    from jobseeker.db.companies import active_companies
    from jobseeker.pipeline.run import run_daily
    from jobseeker.profile.facts import load_facts
    from jobseeker.sources.http import make_client
    from jobseeker.sources.registry import build_sources

    settings, prefs, rubric = _load()
    conn = connect(settings.db_path)
    facts = load_facts(settings.facts_path)
    sources = build_sources(load_companies(settings.companies_path), active_companies(conn), prefs.search)
    with make_client() as client:
        stats = run_daily(conn, sources=sources, client=client, llm=build_llm(settings),
                          facts=facts, prefs=prefs, rubric=rubric, fetch=fetch, force_rescore=force)
    typer.echo(json.dumps(stats.__dict__, indent=2))


@app.command()
def run() -> None:
    """Fetch, dedup, filter, score and draft (the daily job), then back up the database."""
    _run(fetch=True, force=False)
    try:
        backup()
    except Exception as e:  # a failed backup must not hide the run's own result
        typer.echo(f"Backup failed: {type(e).__name__}: {e}", err=True)


@app.command()
def backup() -> None:
    """Save a gzipped copy of the database and facts.json (keeps the last 7 days)."""
    from datetime import datetime

    from jobseeker.db.backup import backup as write_backup

    settings = Settings()
    out = write_backup(settings.db_path, settings.facts_path, settings.backup_path, datetime.now().astimezone())
    typer.echo(f"Backup written to {out}")


@app.command()
def rescore() -> None:
    """Re-score existing jobs (after editing rubric.yaml or preferences)."""
    _run(fetch=False, force=True)


@app.command()
def refilter(apply: bool = typer.Option(False, "--apply", help="Write the changes (default: only list them).")) -> None:
    """Re-apply preferences.yaml filters to stored jobs (after changing title, city or experience rules)."""
    from datetime import UTC, datetime

    from jobseeker.pipeline.refilter import refilter as run_refilter

    settings, prefs, _ = _load()
    changes = run_refilter(connect(settings.db_path), prefs, datetime.now(UTC), apply=apply)
    for c in changes:
        effect = "-> skipped" if c["skips"] else f"(kept {c['status']})" if c["status"] else ""
        typer.echo(f"  {c['title'][:40]:<41}{c['company'][:24]:<25}{c['reason']:<34}{effect}")
    skipped = sum(c["skips"] for c in changes)
    if apply:
        typer.echo(f"Filtered {len(changes)} jobs; skipped {skipped} applications (Undo works on each).")
    else:
        typer.echo(f"{len(changes)} jobs would be filtered, {skipped} applications skipped. "
                   "Run again with --apply to do it.")


@app.command()
def companies() -> None:
    """List companies discovered automatically from job-site results."""
    from jobseeker.db.companies import list_companies

    settings, _, _ = _load()
    rows = list_companies(connect(settings.db_path))
    if not rows:
        typer.echo("No companies discovered yet. They appear after `jobseeker run`.")
        return
    labels = {"active": "Boards found", "none": "No board", "inactive": "Board gone"}
    for status, label in labels.items():
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        typer.echo(f"\n{label} ({len(group)})")
        for r in group:
            board = f"{r['ats']}:{r['slug']}" if r["ats"] else "-"
            typer.echo(f"  {r['display_name'][:34]:<35}{board:<30}jobs seen {r['jobs_seen']:<5}"
                       f"checked {r['checked_at'][:10]}")


@app.command()
def serve(port: int = 8000,
          proxy_headers: bool = typer.Option(False, "--proxy-headers/--no-proxy-headers",
                                             help="Trust X-Forwarded-* from Caddy on 127.0.0.1 (server only).")) -> None:
    """Start the dashboard on http://127.0.0.1:<port>."""
    import uvicorn

    from jobseeker.web.app import create_app

    extra = {"proxy_headers": True, "forwarded_allow_ips": "127.0.0.1"} if proxy_headers else {}
    uvicorn.run(create_app(Settings()), host="127.0.0.1", port=port, **extra)


@app.command("auth-gmail")
def auth_gmail() -> None:
    """One-time Google sign-in (draft-only permission)."""
    from jobseeker.gmail.client import authorize

    settings = Settings()
    authorize(settings.secrets_dir / "credentials.json", settings.secrets_dir / "token.json")
    typer.echo("Gmail connected (drafts only).")


@app.command("gen-key")
def gen_key() -> None:
    """Print 32 random bytes as base64 (SECRET_KEY, TOKEN_KEY, BACKUP_KEY)."""
    import base64
    import secrets

    typer.echo(base64.b64encode(secrets.token_bytes(32)).decode())


@app.command("vapid-keys")
def vapid_keys() -> None:
    """Print a new VAPID key pair for .env (rotating it invalidates every push subscription)."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    from jobseeker.b64 import urlsafe_encode

    v = Vapid02()
    v.generate_keys()
    private = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    public = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    owner = Settings().model_dump().get("owner_email") or "you@example.com"
    typer.echo(f"VAPID_PRIVATE_KEY={urlsafe_encode(private)}")
    typer.echo(f"VAPID_PUBLIC_KEY={urlsafe_encode(public)}")
    typer.echo(f"VAPID_SUBJECT=mailto:{owner}")
