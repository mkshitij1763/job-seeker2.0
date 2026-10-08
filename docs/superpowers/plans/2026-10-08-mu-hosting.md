# Multi-user Hosting and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Execution method chosen by the user: Native (inline), via superpowers:executing-plans.**

**Goal:** Everything needed to run Job Seeker on one Oracle Always Free ARM VM: a `--proxy-headers` flag on `serve`, systemd/Caddy/DuckDNS templates, an idempotent `bootstrap.sh`, a one-command `deploy.sh` with automatic code rollback, and the manual provisioning and cutover checklist.

**Architecture:** Almost all of this is shell and config under `scripts/server/`, plus `scripts/deploy.sh` on the Mac. The only Python change is the `serve` flag. Scripts are tested with pytest:
- templates are rendered and inspected;
- every script passes `bash -n`;
- `bootstrap.sh` input checks run on the Mac (they exit before touching anything);
- `deploy.sh` runs end to end in a **dry-run mode**, with `ssh` replaced by a stub.

The real proof is Task 5 on the VM.

**Tech Stack:** bash, systemd, Caddy 2, iptables/netfilter-persistent, uv, Typer, uvicorn; pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-mu-hosting-design.md`

## Dependencies on other sub-projects

| Task | Buildable now? | Needs |
|---|---|---|
| 1 `serve --proxy-headers` | **Yes** | nothing |
| 2 templates + `env.example` | **Yes** | nothing (it names `jobseeker tick`, but only as text) |
| 3 `ready.sh`, `js`, `bootstrap.sh` | **Yes** | nothing to build or test. To *run* it for real: spec 2 (`create_app` env checks) and spec 3 (`config/app.yaml`) |
| 4 `update.sh` + `deploy.sh` | **Yes** (dry-run tested) | to *run* for real: spec 2 `jobseeker migrate`, spec 6 `GET /healthz`, spec 4 `jobseeker tick` |
| 5 provisioning and cutover | **No** | specs 2, 3, 4, 5 and 6 merged on the deployed branch, plus the user at the keyboard |

## Global Constraints

- **Test commands** (the session sets `FORCE_COLOR=3`): `FORCE_COLOR= uv run pytest --color=no` and `NO_COLOR=1 FORCE_COLOR= node --test tests/js/*.test.mjs`. **Never pass `-q`**, because `addopts` already has it and `-qq` hides the summary.
- **Baseline:** 400 pytest + 19 node tests pass before Task 1. Every task ends with the full suite green: 400 + this plan's new tests, and 19 node.
- **Tests never touch the network** (`pytest-socket`). Scripts under test must exit before any network or system call.
- **Layout:** `/srv/jobseeker/{app,data,config,profile,.env,.ssh}`. The service user is `jobseeker` (`/usr/sbin/nologin`). `JOBSEEKER_HOME=/srv/jobseeker`.
- `companies.yaml` and `rubric.yaml` stay in the checkout (`/srv/jobseeker/app`) and are **never copied** into `/srv/jobseeker`.
- The web service listens on `127.0.0.1:8000` only. Caddy proxies `${DOMAIN}` to it with `request_body max_size 6MB`.
- The tick timer: `OnCalendar=*:0/5`, `Persistent=true`, `AccuracySec=30s`. The tick service: `Type=oneshot`, `TimeoutStartSec=3h`.
- Template variables are **only** `${DOMAIN}`, `${OWNER_EMAIL}` and `${HOME_DIR}`, rendered with `envsubst '${DOMAIN} ${OWNER_EMAIL} ${HOME_DIR}'`. `${DUCKDNS_DOMAIN}`/`${DUCKDNS_TOKEN}` inside `duckdns.service` are systemd's own expansions and must survive rendering.
- **The `.env` names** are exactly spec §6, in this order: `GROQ_API_KEY GEMINI_API_KEY CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID TAVILY_API_KEY APIFY_API_TOKEN HUNTER_API_KEY BACKUP_DIR GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET SECRET_KEY OWNER_EMAIL BASE_URL COOKIE_SECURE TOKEN_KEY VAPID_PRIVATE_KEY VAPID_PUBLIC_KEY VAPID_SUBJECT BACKUP_KEY BACKUP_S3_ENDPOINT BACKUP_S3_REGION BACKUP_S3_BUCKET BACKUP_S3_KEY_ID BACKUP_S3_SECRET HEALTHCHECK_PING_URL`.
- **Services are enabled only when** `.env` has non-empty `SECRET_KEY OWNER_EMAIL BASE_URL GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET TOKEN_KEY`, and `data/jobseeker.db` and `config/app.yaml` exist.
- **Secrets never go** in git, in command-line arguments, or in this plan. Never `git push` or merge to `main` (the coordinator merges).
- **Spec deviation, recorded:** the spec's `read -s` for the DuckDNS token can't work under `ssh … bash -s`, because stdin is the script itself. `bootstrap.sh` instead writes `/etc/duckdns.env` (root, 600) with an empty `DUCKDNS_TOKEN=`. It asks the user to fill it with `sudo nano /etc/duckdns.env` and enables `duckdns.timer` only once the token is non-empty. Also, `deploy.log` gets one line per deploy (after `migrate`), instead of a line plus an append.

## Review Focus

1. **A deploy while a run is in progress.** Expected: refused before anything changes (no `systemctl stop`, no checkout). Test: Task 4 `test_deploy_refuses_while_tick_runs`.
2. **The health check fails after a deploy that didn't change the schema.** Expected: the old SHA is checked out and synced, and the web service and timer are started again. Test: Task 4 `test_failed_health_rolls_code_back`.
3. **The health check fails after a migration changed `user_version`.** Expected: no automatic restart on the old code; restore instructions are printed. Test: Task 4 `test_failed_health_after_migration_prints_restore_steps`.
4. **A `.env` key that's present but empty** (`TOKEN_KEY=`). Expected: reported missing, so the services stay disabled. Test: Task 3 `test_ready_reports_empty_values`.
5. **`--rollback` with no `deploy.log`** (first deploy, or the log was deleted). Expected: a clear "No previous deploy recorded" and exit 1, nothing changed. Test: Task 4 `test_rollback_without_log`.

---

### Task 1: `serve --proxy-headers`

**Files:**
- Modify: `src/jobseeker/cli.py:124-131`
- Test: `tests/test_cli_serve.py` (new)

**Interfaces:**
- Produces: `jobseeker serve [--port N] [--proxy-headers/--no-proxy-headers]`. With the flag: `uvicorn.run(app, host="127.0.0.1", port=N, proxy_headers=True, forwarded_allow_ips="127.0.0.1")`. Without it: `uvicorn.run(app, host="127.0.0.1", port=N)`, exactly as today.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it and check it fails**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_cli_serve.py`
Expected: `test_serve_proxy_headers_trusts_only_localhost` FAILS with "No such option: --proxy-headers".

- [ ] **Step 3: Implement**

Replace `serve` in `src/jobseeker/cli.py`:

```python
@app.command()
def serve(port: int = 8000,
          proxy_headers: bool = typer.Option(False, "--proxy-headers/--no-proxy-headers",
                                             help="Trust X-Forwarded-* from Caddy on 127.0.0.1 (server only).")) -> None:
    """Start the dashboard on http://127.0.0.1:<port>."""
    import uvicorn

    from jobseeker.web.app import create_app

    extra = {"proxy_headers": True, "forwarded_allow_ips": "127.0.0.1"} if proxy_headers else {}
    uvicorn.run(create_app(Settings()), host="127.0.0.1", port=port, **extra)
```

- [ ] **Step 4: Run the tests**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_cli_serve.py`, then the full suite `FORCE_COLOR= uv run pytest --color=no`.
Expected: both new tests pass; full suite 402 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jobseeker/cli.py tests/test_cli_serve.py
git commit -m "feat(cli): serve --proxy-headers for running behind Caddy"
```

---

### Task 2: Server templates and `env.example`

**Files:**
- Create:
  - `scripts/server/templates/jobseeker-web.service`
  - `scripts/server/templates/jobseeker-tick.service`
  - `scripts/server/templates/jobseeker-tick.timer`
  - `scripts/server/templates/duckdns.service`
  - `scripts/server/templates/duckdns.timer`
  - `scripts/server/templates/Caddyfile`
  - `scripts/server/templates/52jobseeker-upgrades`
  - `scripts/server/templates/journald-jobseeker.conf`
  - `scripts/server/templates/sshd-jobseeker.conf`
  - `scripts/server/env.example`
- Test: `tests/test_server_templates.py` (new)

**Interfaces:**
- Produces: the template files above, consumed by Task 3's `bootstrap.sh` (rendered with `envsubst '${DOMAIN} ${OWNER_EMAIL} ${HOME_DIR}'`), and `env.example`, copied to `/srv/jobseeker/.env` by Task 3.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_templates.py
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "scripts" / "server" / "templates"
VALUES = {"DOMAIN": "js-test.duckdns.org", "OWNER_EMAIL": "owner@example.com", "HOME_DIR": "/srv/jobseeker"}
SYSTEMD_OWN = {"DUCKDNS_DOMAIN", "DUCKDNS_TOKEN"}  # expanded by systemd at runtime, never by envsubst
ENV_NAMES = ["GROQ_API_KEY", "GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "TAVILY_API_KEY",
             "APIFY_API_TOKEN", "HUNTER_API_KEY", "BACKUP_DIR", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
             "SECRET_KEY", "OWNER_EMAIL", "BASE_URL", "COOKIE_SECURE", "TOKEN_KEY", "VAPID_PRIVATE_KEY",
             "VAPID_PUBLIC_KEY", "VAPID_SUBJECT", "BACKUP_KEY", "BACKUP_S3_ENDPOINT", "BACKUP_S3_REGION",
             "BACKUP_S3_BUCKET", "BACKUP_S3_KEY_ID", "BACKUP_S3_SECRET", "HEALTHCHECK_PING_URL"]  # spec §6
SECRET_PATTERNS = [r"gsk_[A-Za-z0-9]{10}", r"tvly-[A-Za-z0-9]{6}", r"apify_api_[A-Za-z0-9]{6}",
                   r"(?<![A-Za-z0-9+/])(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{40,}={0,2}", r"BEGIN [A-Z ]*PRIVATE KEY"]


def render(text: str) -> str:
    """What `envsubst '${DOMAIN} ${OWNER_EMAIL} ${HOME_DIR}'` does: only those three names are replaced."""
    for name, value in VALUES.items():
        text = text.replace("${" + name + "}", value)
    return text


def rendered(name: str) -> str:
    return render((TEMPLATES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", sorted(TEMPLATES.iterdir()), ids=lambda p: p.name)
def test_rendering_leaves_only_systemd_variables(path):
    left = set(re.findall(r"\$\{([A-Z_]+)\}", render(path.read_text(encoding="utf-8"))))
    assert left <= SYSTEMD_OWN, f"{path.name} still has {left - SYSTEMD_OWN}"


def test_web_unit():
    unit = rendered("jobseeker-web.service")
    for needle in ("User=jobseeker", "EnvironmentFile=/srv/jobseeker/.env", "Environment=JOBSEEKER_HOME=/srv/jobseeker",
                   "--frozen --no-sync jobseeker serve --port 8000 --proxy-headers", "Restart=always",
                   "ProtectSystem=strict", "ReadWritePaths=/srv/jobseeker/data /srv/jobseeker/config"):
        assert needle in unit


def test_tick_units():
    service, timer = rendered("jobseeker-tick.service"), rendered("jobseeker-tick.timer")
    assert "Type=oneshot" in service and "TimeoutStartSec=3h" in service
    assert "--frozen --no-sync jobseeker tick" in service and "--proxy-headers" not in service
    assert "User=jobseeker" in service and "EnvironmentFile=/srv/jobseeker/.env" in service
    for needle in ("OnCalendar=*:0/5", "Persistent=true", "AccuracySec=30s"):
        assert needle in timer


def test_caddyfile_proxies_to_localhost_with_body_cap():
    caddy = rendered("Caddyfile")
    assert "js-test.duckdns.org {" in caddy and "email owner@example.com" in caddy
    assert "reverse_proxy 127.0.0.1:8000" in caddy and "max_size 6MB" in caddy
    assert "encode" not in caddy  # the app already gzips


def test_duckdns_unit_fails_on_ko():
    unit = rendered("duckdns.service")
    assert "EnvironmentFile=/etc/duckdns.env" in unit
    assert "domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=" in unit
    assert "grep -qx OK /run/duckdns.out" in unit
    assert "OnUnitActiveSec=15min" in rendered("duckdns.timer")


def test_upgrades_reboot_at_0300_ist():
    text = rendered("52jobseeker-upgrades")
    assert 'Automatic-Reboot "true"' in text and 'Automatic-Reboot-Time "21:30"' in text


def test_env_example_lists_exactly_the_spec_names_with_empty_values():
    lines = [ln for ln in (ROOT / "scripts/server/env.example").read_text(encoding="utf-8").splitlines()
             if ln and not ln.startswith("#")]
    assert [ln.split("=", 1)[0] for ln in lines] == ENV_NAMES
    values = dict(ln.split("=", 1) for ln in lines)
    assert all(v == "" for k, v in values.items() if k not in {"BACKUP_DIR", "COOKIE_SECURE"})
    assert values["BACKUP_DIR"] == "/srv/jobseeker/data/backups" and values["COOKIE_SECURE"] == "true"


def test_no_secrets_in_server_files():
    files = [p for p in (ROOT / "scripts" / "server").rglob("*") if p.is_file()] + [ROOT / "scripts" / "deploy.sh"]
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            assert not re.search(pattern, text), f"{path.name} matches secret pattern {pattern}"
```

- [ ] **Step 2: Run it and check it fails**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_server_templates.py`
Expected: errors or failures. `TEMPLATES` doesn't exist, so the parametrize collection fails with `FileNotFoundError`.

- [ ] **Step 3: Create the templates**

`scripts/server/templates/jobseeker-web.service`:
```ini
[Unit]
Description=Job Seeker web
After=network-online.target
Wants=network-online.target

[Service]
User=jobseeker
WorkingDirectory=${HOME_DIR}/app
EnvironmentFile=${HOME_DIR}/.env
Environment=JOBSEEKER_HOME=${HOME_DIR}
ExecStart=${HOME_DIR}/.local/bin/uv run --frozen --no-sync jobseeker serve --port 8000 --proxy-headers
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=${HOME_DIR}/data ${HOME_DIR}/config

[Install]
WantedBy=multi-user.target
```

`scripts/server/templates/jobseeker-tick.service`:
```ini
[Unit]
Description=Job Seeker tick (daily run, Fetch now, backups)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=jobseeker
WorkingDirectory=${HOME_DIR}/app
EnvironmentFile=${HOME_DIR}/.env
Environment=JOBSEEKER_HOME=${HOME_DIR}
ExecStart=${HOME_DIR}/.local/bin/uv run --frozen --no-sync jobseeker tick
TimeoutStartSec=3h
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=${HOME_DIR}/data ${HOME_DIR}/config
```

`scripts/server/templates/jobseeker-tick.timer`:
```ini
[Unit]
Description=Run the Job Seeker tick every 5 minutes

[Timer]
OnCalendar=*:0/5
Persistent=true
AccuracySec=30s

[Install]
WantedBy=timers.target
```

`scripts/server/templates/duckdns.service`:
```ini
[Unit]
Description=Update the DuckDNS record
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/duckdns.env
ExecStart=/usr/bin/curl -fsS -o /run/duckdns.out "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip="
ExecStartPost=/usr/bin/grep -qx OK /run/duckdns.out
```

`scripts/server/templates/duckdns.timer`:
```ini
[Unit]
Description=Keep the DuckDNS record fresh

[Timer]
OnBootSec=1min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
```

`scripts/server/templates/Caddyfile`:
```
{
	email ${OWNER_EMAIL}
}
${DOMAIN} {
	request_body {
		max_size 6MB
	}
	reverse_proxy 127.0.0.1:8000
	header Strict-Transport-Security "max-age=31536000"
	log {
		output file /var/log/caddy/access.log {
			roll_size 10MiB
			roll_keep 5
		}
	}
}
```

`scripts/server/templates/52jobseeker-upgrades`:
```
// Installed by bootstrap.sh. Reboot when needed at 21:30 UTC = 03:00 IST, outside the 11:00-23:59 use window.
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "21:30";
```

`scripts/server/templates/journald-jobseeker.conf`:
```ini
[Journal]
SystemMaxUse=500M
```

`scripts/server/templates/sshd-jobseeker.conf`:
```
# Installed by bootstrap.sh: keys only, no root login.
PermitRootLogin no
PasswordAuthentication no
```

`scripts/server/env.example`:
```
# Copied to /srv/jobseeker/.env (mode 600) by bootstrap.sh. Fill values on the server only; never commit them.
# Keys: `js gen-key` prints 32 random bytes as base64 (SECRET_KEY, TOKEN_KEY, BACKUP_KEY).
GROQ_API_KEY=
GEMINI_API_KEY=
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
TAVILY_API_KEY=
APIFY_API_TOKEN=
HUNTER_API_KEY=
BACKUP_DIR=/srv/jobseeker/data/backups
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
SECRET_KEY=
OWNER_EMAIL=
BASE_URL=
COOKIE_SECURE=true
TOKEN_KEY=
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=
VAPID_SUBJECT=
BACKUP_KEY=
BACKUP_S3_ENDPOINT=
BACKUP_S3_REGION=
BACKUP_S3_BUCKET=
BACKUP_S3_KEY_ID=
BACKUP_S3_SECRET=
HEALTHCHECK_PING_URL=
```

- [ ] **Step 4: Run the tests**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_server_templates.py`, then the full suite.
Expected: all pass (9 template files parametrised, plus 7 tests). Full suite green.

- [ ] **Step 5: Commit**

```bash
git add scripts/server/templates scripts/server/env.example tests/test_server_templates.py
git commit -m "feat(server): systemd, Caddy, DuckDNS and upgrade templates plus env.example"
```

---

### Task 3: `ready.sh`, the `js` wrapper and `bootstrap.sh`

**Files:**
- Create: `scripts/server/ready.sh`, `scripts/server/js`, `scripts/server/bootstrap.sh` (all `chmod +x`)
- Test: `tests/test_server_scripts.py` (new)

**Interfaces:**
- Consumes: Task 2's templates and `env.example`.
- Produces:
  - `scripts/server/ready.sh <HOME_DIR>`: prints one `missing: <name>` line per unmet requirement; exits 0 when ready, 1 otherwise.
  - `scripts/server/js <jobseeker args…>`: runs the CLI as `jobseeker` with `.env` loaded.
  - `scripts/server/bootstrap.sh`: env `BASE_URL`, `OWNER_EMAIL`, `BRANCH`, optional `REPO` (default `git@github.com:mkshitij1763/job-seeker2.0.git`), optional `HOME_DIR` (default `/srv/jobseeker`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_scripts.py
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "server"
REQUIRED = ["SECRET_KEY", "OWNER_EMAIL", "BASE_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_KEY"]


def sh(args, env=None, cwd=ROOT):
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    return subprocess.run(args, capture_output=True, text=True, env={**base, **(env or {})}, cwd=cwd, timeout=30)


@pytest.mark.parametrize("script", ["ready.sh", "js", "bootstrap.sh", "update.sh", "../deploy.sh"])
def test_scripts_parse(script):
    path = SERVER / script
    if not path.exists():
        pytest.skip(f"{script} arrives in a later task")
    assert sh(["bash", "-n", str(path)]).returncode == 0
    if shutil.which("shellcheck"):
        result = sh(["shellcheck", "-S", "warning", str(path)])
        assert result.returncode == 0, result.stdout


def _home(tmp_path, env_text, db=True, app_yaml=True):
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    if db:
        (tmp_path / "data" / "jobseeker.db").write_bytes(b"")
    if app_yaml:
        (tmp_path / "config" / "app.yaml").write_text("{}", encoding="utf-8")
    return tmp_path


def test_ready_when_everything_is_set(tmp_path):
    home = _home(tmp_path, "".join(f"{n}=x\n" for n in REQUIRED))
    result = sh(["bash", str(SERVER / "ready.sh"), str(home)])
    assert result.returncode == 0 and result.stdout == ""


def test_ready_reports_empty_values(tmp_path):
    home = _home(tmp_path, "".join(f"{n}=x\n" for n in REQUIRED if n != "TOKEN_KEY") + "TOKEN_KEY=\n")
    result = sh(["bash", str(SERVER / "ready.sh"), str(home)])
    assert result.returncode == 1 and result.stdout.splitlines() == ["missing: TOKEN_KEY"]


def test_ready_reports_missing_files(tmp_path):
    home = _home(tmp_path, "".join(f"{n}=x\n" for n in REQUIRED), db=False, app_yaml=False)
    result = sh(["bash", str(SERVER / "ready.sh"), str(home)])
    assert result.returncode == 1
    assert result.stdout.splitlines() == ["missing: data/jobseeker.db", "missing: config/app.yaml"]


def test_ready_never_prints_values(tmp_path):
    home = _home(tmp_path, "SECRET_KEY=super-secret-value\n")
    assert "super-secret-value" not in sh(["bash", str(SERVER / "ready.sh"), str(home)]).stdout


@pytest.mark.parametrize("env,message", [
    ({}, "BASE_URL is required"),
    ({"BASE_URL": "http://x.duckdns.org", "OWNER_EMAIL": "a@b.c", "BRANCH": "multi-user"},
     "BASE_URL must start with https://"),
    ({"BASE_URL": "https://x.duckdns.org", "BRANCH": "multi-user"}, "OWNER_EMAIL is required"),
    ({"BASE_URL": "https://x.duckdns.org", "OWNER_EMAIL": "a@b.c"}, "BRANCH is required"),
])
def test_bootstrap_refuses_bad_input_before_doing_anything(env, message):
    result = sh(["bash", str(SERVER / "bootstrap.sh")], env=env)
    assert result.returncode == 1 and message in result.stderr


def test_bootstrap_refuses_non_root():
    if os.geteuid() == 0:
        pytest.skip("running as root")
    env = {"BASE_URL": "https://x.duckdns.org", "OWNER_EMAIL": "a@b.c", "BRANCH": "multi-user"}
    result = sh(["bash", str(SERVER / "bootstrap.sh")], env=env)
    assert result.returncode == 1 and "Run as root" in result.stderr


def test_bootstrap_never_copies_checkout_config_into_home():
    text = (SERVER / "bootstrap.sh").read_text(encoding="utf-8")
    assert "companies.yaml" not in text and "rubric.yaml" not in text
```

- [ ] **Step 2: Run it and check it fails**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_server_scripts.py`
Expected: FAIL. `ready.sh`/`bootstrap.sh` don't exist, so the subprocess returns 127, or reading the file raises.

- [ ] **Step 3: Write `scripts/server/ready.sh`**

```bash
#!/usr/bin/env bash
# Prints what is still missing before jobseeker-web and the tick timer may be enabled. Never prints values.
# Usage: ready.sh /srv/jobseeker   (exit 0 = ready)
set -euo pipefail
home=${1:?usage: ready.sh HOME_DIR}
missing=0
for name in SECRET_KEY OWNER_EMAIL BASE_URL GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET TOKEN_KEY; do
  if ! grep -Eq "^${name}=.+" "$home/.env" 2>/dev/null; then
    echo "missing: $name"
    missing=1
  fi
done
for file in data/jobseeker.db config/app.yaml; do
  if [[ ! -f $home/$file ]]; then
    echo "missing: $file"
    missing=1
  fi
done
exit "$missing"
```

- [ ] **Step 4: Write `scripts/server/js`**

```bash
#!/usr/bin/env bash
# Run the jobseeker CLI on the server as the service user with .env loaded: js migrate --dry-run, js tick, ...
set -euo pipefail
HOME_DIR=${HOME_DIR:-/srv/jobseeker}
exec sudo -u jobseeker -H env JOBSEEKER_HOME="$HOME_DIR" bash -c \
  'set -a; . "$JOBSEEKER_HOME/.env"; set +a; cd "$JOBSEEKER_HOME/app" && exec ~/.local/bin/uv run --frozen --no-sync jobseeker "$@"' \
  _ "$@"
```

- [ ] **Step 5: Write `scripts/server/bootstrap.sh`**

```bash
#!/usr/bin/env bash
# One-time, idempotent server setup for Ubuntu 24.04 (aarch64). Run as root from the Mac:
#   ssh jobseeker 'sudo BASE_URL=https://<sub>.duckdns.org OWNER_EMAIL=<email> BRANCH=multi-user bash -s' \
#     < scripts/server/bootstrap.sh
# Re-run it after adding the deploy key, after filling /etc/duckdns.env and .env, and after the data move.
set -euo pipefail

[[ -n ${BASE_URL:-} ]] || { echo "BASE_URL is required (https://<sub>.duckdns.org)" >&2; exit 1; }
[[ -n ${OWNER_EMAIL:-} ]] || { echo "OWNER_EMAIL is required" >&2; exit 1; }
[[ -n ${BRANCH:-} ]] || { echo "BRANCH is required (the branch to deploy, e.g. multi-user)" >&2; exit 1; }
[[ $BASE_URL == https://* ]] || { echo "BASE_URL must start with https://" >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)" >&2; exit 1; }

REPO=${REPO:-git@github.com:mkshitij1763/job-seeker2.0.git}
HOME_DIR=${HOME_DIR:-/srv/jobseeker}
DOMAIN=${BASE_URL#https://}
DOMAIN=${DOMAIN%%/*}
export DOMAIN OWNER_EMAIL HOME_DIR
CHANGED=0

put_file() {  # put_file DEST MODE < content  -- writes only when different, reports changes
  local dest=$1 mode=$2 tmp
  tmp=$(mktemp)
  cat > "$tmp"
  if [[ -f $dest ]] && cmp -s "$tmp" "$dest"; then
    rm -f "$tmp"
    return 1
  fi
  install -D -m "$mode" "$tmp" "$dest"
  rm -f "$tmp"
  echo "changed: $dest"
  CHANGED=1
}

render() { envsubst '${DOMAIN} ${OWNER_EMAIL} ${HOME_DIR}' < "$HOME_DIR/app/scripts/server/templates/$1"; }

as_js() { sudo -u jobseeker -H bash -c "$1"; }

open_port() {  # open_port iptables|ip6tables PORT  -- insert above Oracle's REJECT rule, once
  local ipt=$1 port=$2 pos
  local rule=(-p tcp -m state --state NEW --dport "$port" -j ACCEPT)
  "$ipt" -C INPUT "${rule[@]}" 2>/dev/null && return 0
  pos=$("$ipt" -L INPUT --line-numbers -n | awk '$2 == "REJECT" { print $1; exit }')
  if [[ -n $pos ]]; then "$ipt" -I INPUT "$pos" "${rule[@]}"; else "$ipt" -A INPUT "${rule[@]}"; fi
  echo "changed: $ipt INPUT accepts tcp/$port"
  CHANGED=1
}

# ---- Phase A: the system ----
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq sqlite3 git curl gettext-base iptables-persistent netfilter-persistent \
  unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
if [[ ! -f /etc/apt/sources.list.d/caddy-stable.list ]]; then  # (verify) against caddyserver.com/docs/install
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  CHANGED=1
fi
apt-get install -y -qq caddy >/dev/null

if ! id jobseeker >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$HOME_DIR" --shell /usr/sbin/nologin jobseeker
  CHANGED=1
fi
install -d -o jobseeker -g jobseeker -m 750 "$HOME_DIR" "$HOME_DIR/data" "$HOME_DIR/data/backups" "$HOME_DIR/config"
install -d -o jobseeker -g jobseeker -m 700 "$HOME_DIR/.ssh"

open_port iptables 80
open_port iptables 443
if ip -6 addr show scope global | grep -q inet6; then
  open_port ip6tables 80
  open_port ip6tables 443
fi
netfilter-persistent save >/dev/null 2>&1

if [[ ! -s $HOME_DIR/.ssh/id_ed25519 ]]; then
  as_js "ssh-keygen -q -t ed25519 -N '' -C jobseeker-deploy -f $HOME_DIR/.ssh/id_ed25519"
  as_js "ssh-keyscan -t ed25519 github.com >> $HOME_DIR/.ssh/known_hosts 2>/dev/null"  # (verify) fingerprint vs docs.github.com
  CHANGED=1
fi
if ! as_js "git ls-remote -q $REPO HEAD" >/dev/null 2>&1; then
  echo
  echo "Add this public key as a READ-ONLY deploy key (GitHub repo -> Settings -> Deploy keys), then re-run:"
  cat "$HOME_DIR/.ssh/id_ed25519.pub"
  exit 0
fi

# ---- Phase B: the app ----
if [[ ! -x $HOME_DIR/.local/bin/uv ]]; then
  as_js 'curl -LsSf https://astral.sh/uv/install.sh | sh' >/dev/null
  CHANGED=1
fi
as_js "$HOME_DIR/.local/bin/uv python install 3.13" >/dev/null
if [[ ! -d $HOME_DIR/app/.git ]]; then  # first time only: later checkouts belong to deploy.sh
  as_js "git clone -q $REPO $HOME_DIR/app && cd $HOME_DIR/app && git checkout -q --detach origin/$BRANCH"
  CHANGED=1
fi
as_js "cd $HOME_DIR/app && $HOME_DIR/.local/bin/uv sync --frozen" >/dev/null  # stops here if a wheel is missing

if [[ ! -f $HOME_DIR/.env ]]; then
  install -o jobseeker -g jobseeker -m 600 "$HOME_DIR/app/scripts/server/env.example" "$HOME_DIR/.env"
  echo "created: $HOME_DIR/.env (empty values; fill it with: sudo -u jobseeker nano $HOME_DIR/.env)"
  CHANGED=1
fi

# put_file reads from process substitution, not a pipe: a pipe would run it in a subshell and lose CHANGED.
for unit in jobseeker-web.service jobseeker-tick.service jobseeker-tick.timer duckdns.service duckdns.timer; do
  put_file "/etc/systemd/system/$unit" 644 < <(render "$unit") || true
done
if put_file /etc/caddy/Caddyfile 644 < <(render Caddyfile); then systemctl reload caddy || true; fi
put_file /etc/apt/apt.conf.d/52jobseeker-upgrades 644 < <(render 52jobseeker-upgrades) || true
if put_file /etc/systemd/journald.conf.d/jobseeker.conf 644 < <(render journald-jobseeker.conf); then
  systemctl restart systemd-journald
fi
if put_file /etc/ssh/sshd_config.d/jobseeker.conf 644 < <(render sshd-jobseeker.conf); then
  sshd -t && systemctl reload ssh
fi
if [[ ! -f /etc/duckdns.env ]]; then
  put_file /etc/duckdns.env 600 < <(printf 'DUCKDNS_DOMAIN=%s\nDUCKDNS_TOKEN=\n' "${DOMAIN%%.*}") || true
  echo "Put your DuckDNS token in /etc/duckdns.env (sudo nano /etc/duckdns.env), then re-run."
fi
systemctl daemon-reload
systemctl enable --now caddy >/dev/null 2>&1
if grep -Eq '^DUCKDNS_TOKEN=.+' /etc/duckdns.env; then
  systemctl enable --now duckdns.timer >/dev/null 2>&1
fi

if "$HOME_DIR/app/scripts/server/ready.sh" "$HOME_DIR"; then
  systemctl enable --now jobseeker-web.service jobseeker-tick.timer >/dev/null 2>&1
else
  echo "jobseeker-web and the tick timer stay disabled until the items above are done."
fi

echo
echo "---- status ----"
for unit in caddy duckdns.timer jobseeker-web jobseeker-tick.timer; do
  printf '%-22s %s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
done
journalctl -u caddy -n 5 --no-pager 2>/dev/null || true
[[ $CHANGED == 1 ]] || echo "No changes."
```

Run `chmod +x scripts/server/ready.sh scripts/server/js scripts/server/bootstrap.sh`.

- [ ] **Step 6: Run the tests**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_server_scripts.py`, then the full suite.
Expected: all pass. `update.sh`/`deploy.sh` parse checks are skipped until Task 4. Full suite green.

- [ ] **Step 7: Commit**

```bash
git add scripts/server/ready.sh scripts/server/js scripts/server/bootstrap.sh tests/test_server_scripts.py
git commit -m "feat(server): idempotent bootstrap.sh, readiness gate and js CLI wrapper"
```

---

### Task 4: `update.sh` and `deploy.sh` with dry-run

**Files:**
- Create: `scripts/server/update.sh`, `scripts/deploy.sh` (both `chmod +x`)
- Test: `tests/test_deploy.py` (new)

**Interfaces:**
- Consumes:
  - `scripts/server/js` (Task 3);
  - at real-run time: `jobseeker migrate` (spec 2), `GET /healthz` (spec 6), and the `jobseeker-tick.service` unit (Task 2).
- Produces:
  - `scripts/deploy.sh [--branch B] [--host H] [--sha SHA] [--dry-run] [--rollback]`, which runs `ssh H "sudo DRY_RUN=0|1 bash -s -- <SHA|--rollback>" < scripts/server/update.sh`.
  - `update.sh` dry-run knobs, for tests only:
    - `DRY_RUN=1` prints `+ <command>` instead of running it;
    - `DRY_FAIL=<substring>`: a printed command containing it "fails";
    - `DRY_TICK_RUNNING=1`;
    - `DRY_UV_BEFORE` / `DRY_UV_AFTER` (default 5/5);
    - `DRY_PREV=<sha or empty>`;
    - `DRY_OLD=<sha>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deploy.py
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB_SSH = """#!/usr/bin/env bash
# Test stub for ssh: run the remote command locally, without sudo. $1 = host, $2 = remote command.
cmd=$2
exec bash -c "${cmd#sudo }"
"""


def deploy(tmp_path, *args, **dry):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "ssh").write_text(STUB_SSH)
    (bin_dir / "ssh").chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "DRY_OLD": "old0000"}
    env.update({k: str(v) for k, v in dry.items()})
    result = subprocess.run(["bash", str(ROOT / "scripts/deploy.sh"), "--dry-run", "--host", "fake", *args],
                            capture_output=True, text=True, env=env, cwd=ROOT, timeout=30)
    commands = [ln[2:] for ln in result.stdout.splitlines() if ln.startswith("+ ")]
    return result, commands


def in_order(commands, *needles):
    pos = 0
    for needle in needles:
        while pos < len(commands) and needle not in commands[pos]:
            pos += 1
        assert pos < len(commands), f"{needle!r} not found in order in {commands}"
        pos += 1


def test_deploy_dry_run_sequence(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234")
    assert result.returncode == 0, result.stderr
    in_order(commands, "systemctl is-active --quiet jobseeker-tick.service", "systemctl stop jobseeker-tick.timer",
             "git checkout -q --detach abc1234", "uv sync --frozen", "systemctl stop jobseeker-web",
             "js migrate", "deploy.log", "systemctl start jobseeker-web", "/healthz",
             "systemctl start jobseeker-tick.timer")
    assert "Deployed abc1234" in result.stdout


def test_deploy_refuses_while_tick_runs(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_TICK_RUNNING=1)
    assert result.returncode == 2 and "A run is in progress" in result.stderr
    assert not any("systemctl stop" in c or "git checkout" in c for c in commands)


def test_failed_health_rolls_code_back(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_FAIL="/healthz")
    assert result.returncode == 1
    in_order(commands, "git checkout -q --detach abc1234", "/healthz", "git checkout -q --detach old0000",
             "uv sync --frozen", "systemctl start jobseeker-web", "systemctl start jobseeker-tick.timer",
             "journalctl -u jobseeker-web")
    assert "rolled back to old0000" in result.stderr


def test_failed_health_after_migration_prints_restore_steps(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_FAIL="/healthz", DRY_UV_BEFORE=4, DRY_UV_AFTER=5)
    assert result.returncode == 1
    assert not any("--detach old0000" in c for c in commands)
    assert "schema changed (user_version 4 -> 5)" in result.stderr and "pre-migrate-v4" in result.stderr


def test_failed_migrate_with_unchanged_schema_restarts_old_code(tmp_path):
    result, commands = deploy(tmp_path, "--sha", "abc1234", DRY_FAIL="js migrate")
    assert result.returncode == 1
    in_order(commands, "js migrate", "git checkout -q --detach old0000", "systemctl start jobseeker-web")


def test_rollback_redeploys_previous_sha(tmp_path):
    result, commands = deploy(tmp_path, "--rollback", DRY_PREV="prev999")
    assert result.returncode == 0, result.stderr
    in_order(commands, "git checkout -q --detach prev999", "systemctl start jobseeker-tick.timer")


def test_rollback_without_log(tmp_path):
    result, commands = deploy(tmp_path, "--rollback", DRY_PREV="")
    assert result.returncode == 1 and "No previous deploy recorded" in result.stderr
    assert not any("systemctl stop" in c for c in commands)


def test_unknown_option(tmp_path):
    result, _ = deploy(tmp_path, "--bogus")
    assert result.returncode == 2 and "Unknown option: --bogus" in result.stderr
```

- [ ] **Step 2: Run it and check it fails**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_deploy.py`
Expected: every test FAILS (bash: `scripts/deploy.sh`: No such file).

- [ ] **Step 3: Write `scripts/server/update.sh`**

```bash
#!/usr/bin/env bash
# Server half of scripts/deploy.sh; runs as root:  bash -s -- <SHA|--rollback> < update.sh
# DRY_RUN=1 prints commands instead of running them (tests use DRY_* knobs, see tests/test_deploy.py).
set -euo pipefail
HOME_DIR=${HOME_DIR:-/srv/jobseeker}
APP=$HOME_DIR/app
LOG=$HOME_DIR/data/deploy.log
DB=$HOME_DIR/data/jobseeker.db
JS=$APP/scripts/server/js
DRY_RUN=${DRY_RUN:-0}
target=${1:?usage: update.sh <sha>|--rollback}

run() {
  if [[ $DRY_RUN == 1 ]]; then
    echo "+ $*"
    if [[ -n ${DRY_FAIL:-} && "$*" == *"$DRY_FAIL"* ]]; then return 1; fi
    return 0
  fi
  "$@"
}
as_app() { run sudo -u jobseeker -H bash -c "cd $APP && $1"; }
tick_running() {
  if [[ $DRY_RUN == 1 ]]; then
    echo "+ systemctl is-active --quiet jobseeker-tick.service"
    [[ ${DRY_TICK_RUNNING:-0} == 1 ]]
  else
    systemctl is-active --quiet jobseeker-tick.service
  fi
}
user_version() {  # user_version before|after
  if [[ $DRY_RUN == 1 ]]; then
    if [[ $1 == before ]]; then echo "${DRY_UV_BEFORE:-5}"; else echo "${DRY_UV_AFTER:-${DRY_UV_BEFORE:-5}}"; fi
  else
    sqlite3 "$DB" 'PRAGMA user_version'
  fi
}
current_sha() { if [[ $DRY_RUN == 1 ]]; then echo "${DRY_OLD:-old0000}"; else git -C "$APP" rev-parse HEAD; fi; }
previous_sha() {
  if [[ $DRY_RUN == 1 ]]; then echo "${DRY_PREV-prev0000}"; return; fi
  [[ -f $LOG ]] && awk 'END { print $2 }' "$LOG"
}
base_url() {
  if [[ $DRY_RUN == 1 ]]; then echo "https://example.duckdns.org"; else grep -E '^BASE_URL=' "$HOME_DIR/.env" | cut -d= -f2-; fi
}
healthy() {
  local url i
  url="$(base_url)/healthz"
  for i in $(seq 1 15); do
    if run curl -fsS -o /dev/null "$url"; then return 0; fi
    [[ $DRY_RUN == 1 ]] && return 1
    sleep 2
  done
  return 1
}
restart_old_code() {
  as_app "git checkout -q --detach $old" || true
  as_app "$HOME_DIR/.local/bin/uv sync --frozen" || true
  run systemctl start jobseeker-web || true
  run systemctl start jobseeker-tick.timer || true
  run journalctl -u jobseeker-web -n 30 --no-pager || true
}

if [[ $target == --rollback ]]; then
  target=$(previous_sha || true)
  if [[ -z $target ]]; then echo "No previous deploy recorded in $LOG" >&2; exit 1; fi
fi

if tick_running; then
  since=$(systemctl show -p ActiveEnterTimestamp --value jobseeker-tick.service 2>/dev/null || echo "unknown")
  echo "A run is in progress since $since; try again later. Nothing was changed." >&2
  exit 2
fi

old=$(current_sha)
run systemctl stop jobseeker-tick.timer
as_app "git fetch -q origin && git checkout -q --detach $target"
as_app "$HOME_DIR/.local/bin/uv sync --frozen"

uv_before=$(user_version before)
run systemctl stop jobseeker-web
if ! run "$JS" migrate; then
  if [[ $(user_version after) == "$uv_before" ]]; then
    restart_old_code
    echo "migrate failed; schema unchanged, rolled back to $old" >&2
  else
    echo "migrate failed after changing the schema; restore data/backups/pre-migrate-v$uv_before-* by hand" >&2
  fi
  exit 1
fi
uv_after=$(user_version after)
run bash -c "echo \"$(date -u +%FT%TZ) $old -> $target user_version=$uv_before->$uv_after\" >> $LOG"

run systemctl start jobseeker-web
if ! healthy; then
  if [[ $uv_after == "$uv_before" ]]; then
    restart_old_code
    echo "/healthz failed after deploying $target; rolled back to $old" >&2
  else
    run systemctl stop jobseeker-web || true
    {
      echo "/healthz failed and the schema changed (user_version $uv_before -> $uv_after)."
      echo "The old code can't run on the new schema, so the web service stays stopped. To restore:"
      echo "  1. sudo cp $HOME_DIR/data/backups/pre-migrate-v$uv_before-<timestamp>.db $DB"
      echo "  2. scripts/deploy.sh --sha $old"
    } >&2
  fi
  exit 1
fi
run systemctl start jobseeker-tick.timer
echo "Deployed $target"
```

- [ ] **Step 4: Write `scripts/deploy.sh`**

```bash
#!/usr/bin/env bash
# Deploy from the Mac:  scripts/deploy.sh [--branch multi-user] [--host jobseeker] [--sha SHA] [--dry-run] [--rollback]
set -euo pipefail
cd "$(dirname "$0")/.."
BRANCH=multi-user
HOST=jobseeker
SHA=""
DRY=0
MODE=deploy
while (($#)); do
  case $1 in
    --branch) BRANCH=$2; shift 2 ;;
    --host) HOST=$2; shift 2 ;;
    --sha) SHA=$2; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --rollback) MODE=rollback; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ $MODE == rollback ]]; then
  target=--rollback
else
  if [[ -z $SHA ]]; then
    git fetch -q origin
    SHA=$(git rev-parse "origin/$BRANCH")
  fi
  if [[ $(git rev-parse HEAD 2>/dev/null) != "$SHA" ]]; then
    echo "Note: local HEAD differs from $SHA; unpushed commits are not deployed." >&2
  fi
  target=$SHA
fi

dry_env=""
if [[ $DRY == 1 ]]; then
  for name in DRY_FAIL DRY_TICK_RUNNING DRY_UV_BEFORE DRY_UV_AFTER DRY_PREV DRY_OLD; do
    if [[ -n ${!name+x} ]]; then dry_env+=" $name=$(printf '%q' "${!name}")"; fi
  done
fi
ssh "$HOST" "sudo DRY_RUN=$DRY$dry_env bash -s -- $target" < scripts/server/update.sh
```

Run `chmod +x scripts/server/update.sh scripts/deploy.sh`.

- [ ] **Step 5: Run the tests**

Run: `FORCE_COLOR= uv run pytest --color=no tests/test_deploy.py tests/test_server_scripts.py`, then the full suite.
Expected: all pass, including the `bash -n` parse checks for `update.sh` and `deploy.sh`. Full suite green.

- [ ] **Step 6: Commit**

```bash
git add scripts/server/update.sh scripts/deploy.sh tests/test_deploy.py
git commit -m "feat(server): deploy.sh with run-in-progress refusal and healthz code rollback"
```

---

### Task 5: Provisioning, cutover and acceptance (manual, with the user)

**Prerequisites:** specs 2, 3, 4, 5 and 6 implemented and merged on the deployed branch. The full suite is green. The coordinator says go. This task changes no code unless a **(verify)** item fails. If one fails, stop, write the deviation into the spec, and tell the coordinator.

**Files:**
- Modify (only if something deviates): `docs/superpowers/specs/2026-10-08-mu-hosting-design.md`
- Modify: `HANDOFF.md` (record the live URL, the provider choices and the runbook pointers; no secrets)

- [ ] **Step 1: User checklist (spec §2), done by the user, one item at a time**

Tick each of these and record the outcome:
1. Oracle signup, home region Mumbai or Hyderabad. (verify) The home region is permanent, and A1 runs only there. Upgrade to PAYG. Create a ₹100/month budget alert. (verify) Idle reclaim doesn't apply to PAYG.
2. Mac: `ssh-keygen -t ed25519 -f ~/.ssh/jobseeker_oci`, plus a `~/.ssh/config` `Host jobseeker` entry.
3. VM `VM.Standard.A1.Flex`, 2 OCPU / 12 GB, Ubuntu 24.04 aarch64, with a reserved public IP. (verify) The reserved IP is free.
4. Security list: ingress TCP 80 and 443 from `0.0.0.0/0`.
5. DuckDNS subdomain pointing at the reserved IP. (verify) The inactivity-expiry rule.
6. Google OAuth Web client redirect URIs `https://<sub>.duckdns.org/auth/callback` and `/gmail/callback`. (verify) Google accepts `<sub>.duckdns.org` as an authorized domain. **Stop if it doesn't.**
7. B2 bucket, lifecycle rules, and a `writeFiles`-only key (extras spec §2; its (verify) items).

- [ ] **Step 2: Bootstrap, three passes**

Run each pass from the repo root on the Mac:
1. `ssh jobseeker 'sudo BASE_URL=https://<sub>.duckdns.org OWNER_EMAIL=<email> BRANCH=multi-user bash -s' < scripts/server/bootstrap.sh`. Expected: it prints the deploy key. The user adds it in GitHub.
2. Re-run the same command. Expected: uv, the clone and `uv sync --frozen` succeed with no compiled source builds (only the pure-Python `http-ece` sdist). The templates are installed, and `.env` and `/etc/duckdns.env` are created. The user fills in the DuckDNS token and `.env` (`js gen-key` for the keys).
3. Re-run. Expected: `duckdns.timer` is active, and Caddy has a certificate once DNS resolves. The jobseeker services stay disabled: "missing: data/jobseeker.db, config/app.yaml".

(verify) `iptables -S INPUT` shows the 80/443 ACCEPT rules above the REJECT. Record whether Oracle's image still ships that REJECT rule.

- [ ] **Step 3: Data move (spec §10)**

Follow spec §10 steps 1–7 exactly, recording the row counts before and after in the session.

Expected:
- every pre-existing table's count matches;
- the owner signs in and sees the same Today, Jobs, Job detail and Pipeline;
- Gmail is reconnected through the web flow;
- `js tick` exits 0;
- the Mac launchd agents and `tailscale serve` are off.

- [ ] **Step 4: Acceptance criteria (spec §Acceptance 1–12)**

Check each one and record the evidence (command output) in the session:
- `curl -I https://<sub>.duckdns.org/healthz` returns 200;
- after signing in, the first POST (e.g. saving a setting) succeeds rather than returning 403 (proves `BASE_URL` exactly equals the browser origin for OriginCheck);
- `nc -z <ip> 8000` fails;
- a second `bootstrap.sh` run prints "No changes.";
- after `sudo reboot`, all four units are active;
- the next day's 11:15 IST run and its Healthchecks.io ping happen;
- a deploy of a trivial commit works;
- a deploy of a deliberately broken commit (on a throwaway branch, `--branch spike/broken`) rolls back;
- a deploy during a run is refused;
- the restore drill passes;
- `.env` is 600, owned by `jobseeker`;
- the Oracle billing page shows ₹0 after a week.

- [ ] **Step 5: Record and commit**

Update `HANDOFF.md`:
- the live URL (subdomain only);
- the region;
- that PAYG and the budget alert are set;
- the B2 bucket name (no keys);
- the `scripts/deploy.sh` and `js` usage;
- any spec deviations found.

```bash
git add HANDOFF.md docs/superpowers/specs/2026-10-08-mu-hosting-design.md
git commit -m "docs: server is live; provisioning notes and deviations"
```
