from __future__ import annotations

import json

import typer

from jobseeker.config import Settings, load_companies, load_rubric
from jobseeker.db.core import connect
from jobseeker.llm import build_llm

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
    for d in (settings.data_dir, settings.logs_dir, settings.secrets_dir):
        d.mkdir(parents=True, exist_ok=True)
    connect(settings.db_path).close()
    typer.echo(f"Ready in {settings.jobseeker_home}. Run `jobseeker migrate` to import profile/ and write config/app.yaml.")


def _run(fetch: bool, force: bool, user: str = "") -> None:
    from jobseeker.db.companies import active_companies
    from jobseeker.pipeline.run import run_daily
    from jobseeker.sources.http import make_client
    from jobseeker.sources.registry import build_sources

    settings, cfg, conn, uid, prefs, facts = _ctx(user)
    if facts is None:
        typer.echo("No resume facts for this user yet", err=True)
        raise typer.Exit(1)
    sources = build_sources(load_companies(cfg.companies_path), active_companies(conn), prefs.search)
    with make_client() as client:
        stats = run_daily(conn, user_id=uid, sources=sources, client=client, llm=build_llm(settings),
                          facts=facts, prefs=prefs, rubric=load_rubric(cfg.rubric_path), fetch=fetch,
                          force_rescore=force)
    typer.echo(json.dumps(stats.__dict__, indent=2))


@app.command()
def run(user: str = typer.Option("", "--user", help="The user's email (default: the owner).")) -> None:
    """Fetch, dedup, filter, score and draft (the daily job), then back up the database."""
    _run(fetch=True, force=False, user=user)
    try:
        backup()
    except Exception as e:  # a failed backup must not hide the run's own result
        typer.echo(f"Backup failed: {type(e).__name__}: {e}", err=True)


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

    settings = Settings()
    ctx = MigrationContext(owner_email=settings.owner_email, now=datetime.now(UTC), home=settings.jobseeker_home)
    try:
        for line in run_migrate(settings.db_path, ctx, settings.data_dir / "backups", dry_run=dry_run):
            typer.echo(line)
    except (DatabaseBusy, MigrationError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)


@app.command()
def rescore(user: str = typer.Option("", "--user", help="The user's email (default: the owner).")) -> None:
    """Re-score existing jobs (after editing rubric.yaml or preferences)."""
    _run(fetch=False, force=True, user=user)


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
