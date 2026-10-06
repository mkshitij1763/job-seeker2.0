from __future__ import annotations

import json

import typer

from jobseeker.config import Settings, load_companies, load_preferences, load_rubric
from jobseeker.db.core import connect
from jobseeker.llm import GroqLLM

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
    facts = load_or_build_facts(GroqLLM(settings.groq_api_key), settings.resume_path,
                                settings.facts_path, prefs.models.facts)
    typer.echo(f"Facts written to {settings.facts_path}: {len(facts.achievements)} achievements, "
               f"{len(facts.skills)} skills. Review and edit that file if anything is wrong.")


def _run(fetch: bool, force: bool) -> None:
    from jobseeker.pipeline.run import run_daily
    from jobseeker.profile.facts import load_facts
    from jobseeker.sources.http import make_client
    from jobseeker.sources.registry import build_sources

    settings, prefs, rubric = _load()
    conn = connect(settings.db_path)
    facts = load_facts(settings.facts_path)
    from jobseeker.db.companies import active_companies

    sources = build_sources(load_companies(settings.companies_path), active_companies(conn), prefs.search)
    with make_client() as client:
        stats = run_daily(conn, sources=sources, client=client, llm=GroqLLM(settings.groq_api_key),
                          facts=facts, prefs=prefs, rubric=rubric, fetch=fetch, force_rescore=force)
    typer.echo(json.dumps(stats.__dict__, indent=2))


@app.command()
def run() -> None:
    """Fetch, dedup, filter, score and draft (the daily job)."""
    _run(fetch=True, force=False)


@app.command()
def rescore() -> None:
    """Re-score existing jobs (after editing rubric.yaml or preferences)."""
    _run(fetch=False, force=True)


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
def serve(port: int = 8000) -> None:
    """Start the dashboard on http://127.0.0.1:<port>."""
    import uvicorn

    from jobseeker.web.app import create_app

    uvicorn.run(create_app(Settings()), host="127.0.0.1", port=port)


@app.command("auth-gmail")
def auth_gmail() -> None:
    """One-time Google sign-in (draft-only permission)."""
    from jobseeker.gmail.client import authorize

    settings = Settings()
    authorize(settings.secrets_dir / "credentials.json", settings.secrets_dir / "token.json")
    typer.echo("Gmail connected (drafts only).")
