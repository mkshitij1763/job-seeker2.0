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


def test_tick_yields_memory_and_cpu_to_the_web():  # GCP e2-micro has 1 GB: the tick must never starve the web
    service = rendered("jobseeker-tick.service")
    assert "MemoryHigh=600M" in service and "MemoryMax" not in service  # soft: throttled into swap, never OOM-killed
    assert "Nice=10" in service
    assert "MemoryHigh" not in rendered("jobseeker-web.service")


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
