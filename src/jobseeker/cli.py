from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

import typer

from jobseeker.config import Settings
from jobseeker.db.core import connect

app = typer.Typer(no_args_is_help=True, help="Personal job search and outreach assistant.")


def _ctx(email: str | None = None):
    """Settings, server config, a connection, and one user's context (the owner unless --user names someone)."""
    from jobseeker.config import load_app_config
    from jobseeker.db.profile import load_user_context
    from jobseeker.db.users import OWNER_ID, ensure_owner

    settings = Settings()
    cfg = load_app_config(settings.app_config_path)
    conn = connect(settings.db_path)
    ensure_owner(conn, settings.owner_email)
    if email:
        row = conn.execute("SELECT id FROM users WHERE email = lower(?)", (email.strip(),)).fetchone()
        if row is None:
            typer.echo(f"No user with email {email}", err=True)
            raise typer.Exit(1)
        uid = row[0]
    else:
        uid = OWNER_ID
    prefs, facts = load_user_context(conn, uid, cfg)
    return settings, cfg, conn, uid, prefs, facts


@app.command()
def init() -> None:
    """Create the folders and the database."""
    settings = Settings()
    for d in (settings.data_dir, settings.logs_dir):
        d.mkdir(parents=True, exist_ok=True)
    connect(settings.db_path).close()
    typer.echo(f"Ready in {settings.jobseeker_home}. Run `jobseeker migrate`: it imports profile/ when present and "
               "writes config/app.yaml from config/app.example.yaml if it's missing.")


def _pipeline(settings, cfg):
    """The rubric, companies and LLM run_all needs on the real system. Built only when a run actually starts, so a
    busy tick or a refused `run` never needs GROQ_API_KEY."""
    from jobseeker.config import load_companies, load_rubric
    from jobseeker.llm import build_llm

    return load_rubric(cfg.rubric_path), load_companies(cfg.companies_path), build_llm(settings)


def _runner(settings, conn, now, holder, force_users=frozenset(), fetch=True):
    from jobseeker.config import load_app_config
    from jobseeker.db.locks import heartbeat
    from jobseeker.pipeline.run import run_all
    from jobseeker.sources.http import make_client

    cfg = load_app_config(settings.app_config_path)

    def run(trigger, users, plan_cap):
        rubric, companies, llm = _pipeline(settings, cfg)
        with make_client() as client:
            return run_all(conn, users=users, trigger=trigger, fetch=fetch, plan_cap=plan_cap, client=client, llm=llm,
                           cfg=cfg, rubric=rubric, now=now, companies=companies, force_users=force_users,
                           heartbeat=lambda: heartbeat(conn, "run", holder, datetime.now(UTC)))
    return cfg, run


@app.command()
def tick() -> None:
    """Called every 5 minutes by the host: runs the daily schedule, Fetch now requests and the nightly backup."""
    from jobseeker.db.locks import holder_id
    from jobseeker.pipeline.tick import tick as do_tick

    settings, now = Settings(), datetime.now(UTC)
    conn = connect(settings.db_path)
    holder = holder_id()
    cfg, run = _runner(settings, conn, now, holder)
    typer.echo(do_tick(conn, settings=settings, cfg=cfg, now=now, run=run, holder=holder))


@app.command()
def run(user: str = typer.Option("", "--user", help="Only this user's email (default: everyone active)."),
        no_fetch: bool = typer.Option(False, "--no-fetch", help="Skip the job-site fetch.")) -> None:
    """Run the pipeline now, by hand (takes the same lock as tick)."""
    _manual(user, fetch=not no_fetch, force=False)


@app.command()
def rescore(user: str = typer.Option(..., "--user", help="The user's email.")) -> None:
    """Re-score one user's open jobs now (after editing rubric.yaml)."""
    _manual(user, fetch=False, force=True)


def _manual(email: str, fetch: bool, force: bool) -> None:
    from jobseeker.clock import app_now
    from jobseeker.db.locks import acquire, held_since, holder_id, release
    from jobseeker.pipeline.eligible import active_users

    settings, now = Settings(), datetime.now(UTC)
    conn = connect(settings.db_path)
    holder = holder_id()
    users = [u for u in active_users(conn) if not email or u.email == email.lower()]
    if email and not users:
        typer.echo(f"No active user {email}", err=True)
        raise typer.Exit(1)
    cfg, run_fn = _runner(settings, conn, now, holder, frozenset(u.id for u in users) if force else frozenset(), fetch)
    if not acquire(conn, "run", holder, now, cfg.lock.takeover_after_minutes):
        since = app_now(datetime.fromisoformat(held_since(conn, "run"))).strftime("%H:%M")
        typer.echo(f"A run is in progress since {since}", err=True)
        raise typer.Exit(1)
    try:
        report = run_fn("cli", users, cfg.search.max_searches_per_run)
    finally:
        release(conn, "run", holder)
    typer.echo(json.dumps({"fetch": report.fetch and asdict(report.fetch),
                           "users": {k: asdict(v) for k, v in report.users.items()}, "aborted": report.aborted},
                          indent=2))


@app.command()
def backup() -> None:
    """Write today's backup archive now (and upload it when B2 is configured), even if one exists."""
    from datetime import UTC, datetime

    from jobseeker.backup.nightly import BackupFailed, nightly_backup

    settings = Settings()
    conn = connect(settings.db_path)
    try:
        result = nightly_backup(conn, settings, datetime.now(UTC), force=True)
    except BackupFailed as e:
        typer.echo(f"Backup failed: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Backup written to {result.path}")
    if result.error:
        typer.echo(result.error, err=not result.ok)


@app.command()
def migrate(dry_run: bool = typer.Option(False, "--dry-run", help="Migrate a copy and report; change nothing.")) -> None:
    """Upgrade the database schema (backs up first; stop the web service and the timer before running)."""
    from datetime import UTC, datetime

    from jobseeker.db.migrations import DatabaseBusy, MigrationContext, MigrationError
    from jobseeker.db.migrations import migrate as run_migrate
    from jobseeker.profile.importer import ensure_app_yaml

    settings = Settings()
    ctx = MigrationContext(owner_email=settings.owner_email, now=datetime.now(UTC), home=settings.jobseeker_home)
    try:
        for line in run_migrate(settings.db_path, ctx, settings.data_dir / "backups", dry_run=dry_run):
            typer.echo(line)
    except (DatabaseBusy, MigrationError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    if not dry_run and ensure_app_yaml(settings.jobseeker_home):
        typer.echo("Wrote config/app.yaml from config/app.example.yaml")


@app.command()
def refilter(apply: bool = typer.Option(False, "--apply", help="Write the changes (default: only list them)."),
             user: str = typer.Option("", "--user", help="The user's email (default: the owner).")) -> None:
    """Re-apply the user's preferences to stored jobs, both ways: hide newly filtered ones, bring back loosened ones."""
    from datetime import UTC, datetime

    from jobseeker.pipeline.evaluate import reevaluate

    _, _, conn, uid, prefs, facts = _ctx(user)
    report = reevaluate(conn, uid, prefs, facts, datetime.now(UTC), apply=apply)
    skipped = set(report.skipped_apps)
    apps = {r["job_id"]: r["app_id"] for r in conn.execute(
        "SELECT job_id, id AS app_id FROM applications WHERE user_id = ?", (uid,))}
    for c in report.hidden + [n for n in report.new if n["reason"]]:
        effect = "-> skipped" if apps.get(c["job_id"]) in skipped else ""
        typer.echo(f"  {c['title'][:40]:<41}{c['company'][:24]:<25}{c['reason']:<34}{effect}")
    for c in report.restored:
        typer.echo(f"  {c['title'][:40]:<41}{c['company'][:24]:<25}{'':<34}-> back")
    hidden = len(report.hidden) + sum(1 for n in report.new if n["reason"])
    if apply:
        typer.echo(f"Filtered {hidden} jobs, brought back {len(report.restored)}; "
                   f"skipped {len(skipped)} applications (Undo works on each).")
    else:
        typer.echo(f"{hidden} jobs would be filtered, {len(report.restored)} brought back, {len(skipped)} applications "
                   "skipped. Run again with --apply to do it.")


@app.command()
def companies() -> None:
    """List companies discovered automatically from job-site results."""
    from jobseeker.db.companies import list_companies

    settings = Settings()
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
          host: str = typer.Option("127.0.0.1", help="Address to bind (0.0.0.0 inside a container)."),
          proxy_headers: bool = typer.Option(False, "--proxy-headers/--no-proxy-headers",
                                             help="Trust X-Forwarded-* from the proxies in FORWARDED_ALLOW_IPS "
                                                  "(default 127.0.0.1, i.e. Caddy; Railway sets *).")) -> None:
    """Start the dashboard on http://<host>:<port> (127.0.0.1 unless --host)."""
    import os

    import uvicorn

    from jobseeker.web.app import create_app

    extra = ({"proxy_headers": True, "forwarded_allow_ips": os.environ.get("FORWARDED_ALLOW_IPS") or "127.0.0.1"}
             if proxy_headers else {})
    uvicorn.run(create_app(Settings()), host=host, port=port, **extra)


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


@app.command()
def restore(path: str, to: str = typer.Option("", "--to", help="Empty directory (default ./restore-<date>).")) -> None:
    """Unpack and check a backup (.tar.gz, or .tar.gz.enc from B2). Never touches the live data."""
    from datetime import date
    from pathlib import Path

    from jobseeker.backup.crypto import load_key
    from jobseeker.backup.restore import RestoreError, restore as do_restore

    settings = Settings()
    key = load_key(settings.backup_key) if settings.backup_key else None
    target = Path(to or f"restore-{date.today().isoformat()}")
    try:
        report = do_restore(Path(path), target, key)
    except RestoreError as e:
        typer.echo(f"Restore refused: {e}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Restored into {target}; integrity ok")
    for table, n in sorted(report["restored_counts"].items()):
        typer.echo(f"  {table:<28}{n:>8}  (manifest {report['manifest_counts'].get(table, '-')})")
