# Sub-project 1: hosting and deployment (proposal)

**Date:** 2026-10-08 · **Branch:** `research/hosting` (from `multi-user`) · **Status:** draft for review, nothing provisioned
**Decided:** Oracle Cloud Always Free (ARM, Mumbai or Hyderabad); a free DuckDNS subdomain plus Caddy for HTTPS; port 25 assumed blocked, so `contacts.smtp_verify: off` on the server (outreach proposal §e).
**Evidence:** the hosting spike (run `37777276970`, branch `spike/hosting`, throwaway). From Azure datacenter addresses, LinkedIn, Naukri, Indeed, the LinkedIn description fetch and the Greenhouse, Lever and Ashby APIs all matched the Mac. It ran one search per site from US addresses, so full daily volume from an Indian Oracle address is still unproven. Watch the first week's run notes.

Items marked *(verify)* come from memory of Oracle's, Google's or DuckDNS's rules and must be checked against their current docs while setting up.

## (a) VM shape and ARM compatibility

- **Shape:** `VM.Standard.A1.Flex`, **2 OCPU / 12 GB**, boot volume 50 GB. This is half the Always Free A1 allowance (4 OCPU / 24 GB, 200 GB block storage in total), which leaves room for a second VM or a resize. The load is light: one uvicorn process, plus a `tick` that is mostly network waits and SQLite.
- **Image:** Canonical **Ubuntu 24.04 (aarch64)**. Python 3.13 comes from `uv python install 3.13`, a uv-managed build; Ubuntu ships 3.12.
- **Region:** Always Free A1 runs only in the **home region**, which is chosen at signup and **can't be changed** *(verify)*. Pick Mumbai or Hyderabad at signup. Each has one availability domain.
- **"Out of host capacity" is common for A1.** Advice:
  1. Retry creation at off-peak hours (early morning IST), in each fault domain.
  2. Fall back to 1 OCPU / 6 GB and resize later (resizing a stopped Flex VM is allowed).
  3. Upgrading to Pay As You Go (see g) is widely reported to clear capacity errors. The A1 allowance stays free.
  4. Don't use auto-retry scripts against the console API without the user's OK.
- **Wheels:** every package in `uv.lock` was checked (2026-10-08). 64 are pure Python. All 12 compiled packages (`numpy 2.5.3`, `pandas 3.0.6`, `curl-cffi 0.16.3`, `cryptography 50.0.2`, `cffi`, `pydantic-core`, `pymupdf 1.28.2`, `pyyaml`, `markupsafe`, `httptools`, `uvloop`, `watchfiles`), plus `protobuf`, `websockets` and `charset-normalizer`, publish cp313 or abi3 `manylinux` **aarch64** wheels. The newest glibc any of them needs is 2.34 (`cryptography`), and Ubuntu 24.04 ships 2.39. Nothing builds from source.
  - **`tls-client` is not in the lock.** `python-jobspy==1.2.0` depends on `curl-cffi`, whose aarch64 wheel bundles its own curl-impersonate `.so`.
  - Proof on real hardware is the first `uv sync --frozen` on the VM; a failure there stops the deploy before anything is switched.
- **Pending dependencies** from other proposals: `pywebpush` (pure Python; it pulls `cryptography`, `requests` and `http-ece`) and `tzdata` (pure Python). Neither changes the ARM picture.

## (b) What the user does by hand, and what we automate

**User checklist (about 45 minutes, once):**
1. Sign up for Oracle Cloud with a card, choosing **home region Mumbai or Hyderabad**. Optionally upgrade to Pay As You Go and set a **₹100 budget alert** (see g).
2. Create the VM as in (a). Paste the SSH public key, made on the Mac with `ssh-keygen -t ed25519 -f ~/.ssh/jobseeker_oci`, and **reserve the public IP** (Networking → Reserved public IPs, free *(verify)*) so it survives a stop or start.
3. In the VCN's default security list, add ingress rules for TCP **80** and **443** from `0.0.0.0/0`. Port 22 is already there.
4. At duckdns.org, sign in, create the subdomain (for example `jobseeker-km`), point it at the reserved IP, and copy the **token**.
5. In GitHub, add a **read-only deploy key** (repo → Settings → Deploy keys), so the server can `git pull` the private repo.
6. In Google Cloud, on the OAuth client from the auth proposal, add the redirect URIs `https://<sub>.duckdns.org/auth/callback` and `/gmail/callback`. Add `<sub>.duckdns.org` as an authorized domain *(verify: `duckdns.org` is on the public-suffix list, so the subdomain should count as its own domain)*.
7. Give us SSH access, then paste the secrets from (e) into the server `.env` yourself, or let `bootstrap.sh` prompt for them.

**Automated after that:** `scripts/server/bootstrap.sh`, run once over SSH as root. It is idempotent: re-running it changes nothing that is already correct. It:
- creates the `jobseeker` service user;
- installs uv, Python 3.13, Caddy (from its apt repo) and `sqlite3`;
- opens the firewall (d);
- clones the repo and runs `uv sync --frozen`;
- writes the systemd units, the Caddyfile and the DuckDNS timer from templates in `scripts/server/`;
- enables unattended-upgrades.

After that, `scripts/deploy.sh` handles every change (f).

## (c) Runtime: uv on the host, managed by systemd

**Recommendation: uv directly, no Docker.**
- It's one app on one VM, and uv already gives reproducible installs from `uv.lock`.
- Docker would add an image build on ARM, a registry or on-box builds, volume mounts for SQLite and resumes, and a second layer of restart policy, without isolating anything that a dedicated user plus systemd hardening doesn't.
- The Mac and the server would run the same way (`uv run jobseeker …`).
- Revisit only if the app ever needs to move hosts often.

**Layout:**
- `/srv/jobseeker/app`: the git checkout.
- `/srv/jobseeker/data`: the DB, `users/` resumes, `logs/` and `backups/`. This is `JOBSEEKER_HOME=/srv/jobseeker`, so `data_dir` resolves there, as `config.py` expects.
- `/srv/jobseeker/.env`: secrets.
- `/srv/jobseeker/config/app.yaml`: global settings.

`/etc/systemd/system/jobseeker-web.service` replaces `com.kshitij.jobseeker.web`:
```ini
[Unit]
Description=Job Seeker web
After=network-online.target
Wants=network-online.target

[Service]
User=jobseeker
WorkingDirectory=/srv/jobseeker/app
EnvironmentFile=/srv/jobseeker/.env
Environment=JOBSEEKER_HOME=/srv/jobseeker
ExecStart=/srv/jobseeker/.local/bin/uv run --frozen --no-sync jobseeker serve --port 8000
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=/srv/jobseeker/data

[Install]
WantedBy=multi-user.target
```
`serve` already binds `127.0.0.1` (`cli.py:131`), so only Caddy can reach it. Uvicorn needs `--proxy-headers --forwarded-allow-ips=127.0.0.1` so that `request.url.scheme` is `https` behind Caddy, which the `BASE_URL` and Origin checks rely on. Add both flags to `serve`.

`jobseeker-tick.service` + `jobseeker-tick.timer` replace `com.kshitij.jobseeker`:
- **service:** `Type=oneshot`; the same `User`, `WorkingDirectory`, `EnvironmentFile`, `Environment` and hardening as above; `ExecStart=… uv run --frozen --no-sync jobseeker tick`; `TimeoutStartSec=3h` as a ceiling (runs take up to 78 minutes today).
- **timer:** `OnCalendar=*:0/5`, `Persistent=true`, `RandomizedDelaySec=0`.
- **overlap:** systemd won't start a oneshot that is still active, and the app's `locks` row (pipeline proposal) is the real guard.
- **missed runs:** the 11:15 IST schedule lives in the app, so missed runs catch up on the next tick.

**Logs:** journald (`journalctl -u jobseeker-tick -S today`), with `SystemMaxUse=500M`. `data/logs/` stays for the app's own run logs.

## (d) Caddy, DuckDNS, firewall, upgrades, service user

**Caddyfile** (`/etc/caddy/Caddyfile`):
```
{
	email <OWNER_EMAIL>
}
<sub>.duckdns.org {
	reverse_proxy 127.0.0.1:8000
	header Strict-Transport-Security "max-age=31536000"
	log {
		output file /var/log/caddy/access.log
	}
}
```
- Caddy gets and renews the Let's Encrypt certificate through the HTTP-01 challenge, which needs port 80 open. Port 80 also redirects to 443.
- Pages are already gzipped by the app (`deb1441`), so Caddy doesn't `encode` them again.
- If HTTP-01 is ever blocked, switch to the DNS-01 challenge with the `caddy-dns/duckdns` plugin (a custom `xcaddy` build). Not needed by default.

**DuckDNS updater:**
- `duckdns.service` (oneshot) runs `curl -fsS "https://www.duckdns.org/update?domains=<sub>&token=${DUCKDNS_TOKEN}&ip="` and must print `OK`.
- `duckdns.timer` runs it every 15 minutes.
- The token lives in `/etc/duckdns.env` (root, 600), separate from the app's `.env`.
- With a reserved IP this rarely changes anything, but it keeps the subdomain alive. DuckDNS can expire unused domains *(verify)*.

**Firewall: Oracle's Ubuntu images ship restrictive iptables rules.**
- `/etc/iptables/rules.v4` (from `netfilter-persistent`) allows only port 22 and ends `INPUT` with a `REJECT`. **Opening the security list alone isn't enough.**
- `bootstrap.sh` inserts the new rules *before* the REJECT and saves them:
  ```
  iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
  iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  netfilter-persistent save
  ```
  It finds the REJECT's line number with `iptables -L INPUT --line-numbers` instead of hard-coding 6.
- Repeat the same rules for `ip6tables` if IPv6 is enabled on the VCN.
- **Don't enable ufw** on top: it fights `netfilter-persistent`, and Oracle's guidance is iptables only *(verify)*. Port 8000 is never opened.

**SSH:** key-only (the default on Oracle images); `PermitRootLogin no`; the user logs in as `ubuntu` and uses `sudo`. Optional: `fail2ban`.

**unattended-upgrades:** on by default in the cloud image; `bootstrap.sh` confirms it. Set:
```
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "21:30";   // UTC = 03:00 IST, outside 11:00–23:59 use
```
After a reboot, systemd brings back the web service, Caddy and both timers.

**Service user:** `useradd --system --create-home --home-dir /srv/jobseeker --shell /usr/sbin/nologin jobseeker`. It owns `/srv/jobseeker`. `.env` is `jobseeker:jobseeker 600`. The deploy key lives in `/srv/jobseeker/.ssh` (600).

## (e) Secrets

`/srv/jobseeker/.env`:
- mode **600**, never in git (`.env` is already in `.gitignore`), never in backups (extras proposal §b);
- loaded by systemd's `EnvironmentFile`, so pydantic `Settings` reads the variables from the environment;
- for manual CLI use: `sudo -u jobseeker bash -c 'set -a; . /srv/jobseeker/.env; cd app; uv run jobseeker …'`, wrapped as `scripts/server/js`.

The owner keeps a copy of the whole file in their password manager.

| Variable | Source | Notes |
|---|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | today | LLM chain |
| `TAVILY_API_KEY`, `APIFY_API_TOKEN`, `HUNTER_API_KEY` | today | shared quotas |
| `JOBSEEKER_HOME`, `BACKUP_DIR` | today | set in the unit; `BACKUP_DIR=/srv/jobseeker/data/backups` (the iCloud default is meaningless here) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | auth | the Web client, also used for Gmail |
| `SECRET_KEY` | auth | 32+ random bytes, signs cookies |
| `OWNER_EMAIL`, `BASE_URL=https://<sub>.duckdns.org`, `COOKIE_SECURE=true` | auth | |
| `TOKEN_KEY` | outreach | AES-GCM key for the Gmail tokens; not the same key as `BACKUP_KEY` |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` | extras | from `jobseeker vapid-keys` |
| `BACKUP_KEY`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_KEY_ID`, `BACKUP_S3_SECRET` | extras | off-site upload is refused without `BACKUP_KEY` |
| `HEALTHCHECK_PING_URL` | extras | optional dead-man's switch |

`DUCKDNS_TOKEN` stays in `/etc/duckdns.env`. Generate the keys on the server with `python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"`.

## (f) Deploy and the first data move

**`scripts/deploy.sh [host]`** runs from the Mac and does everything over SSH. It fails fast at each step:
1. `ssh host` checks that `systemctl is-active jobseeker-tick.service` is not active. If a run is in progress, it **refuses** and prints when the run started. A migration must not run under a live run.
2. `sudo systemctl stop jobseeker-tick.timer`.
3. As `jobseeker`: `git fetch && git checkout --detach origin/<branch>`. The branch is `main` once merged, `multi-user` until then. Record the previous SHA in `data/deploy.log`.
4. `uv sync --frozen`.
5. `uv run jobseeker migrate`: the versioned `user_version` migrations from the auth proposal. It takes a pre-migration `.backup` snapshot first.
6. `sudo systemctl restart jobseeker-web`, then poll `https://<sub>.duckdns.org/healthz` for up to 30 s.
7. `sudo systemctl start jobseeker-tick.timer`.

If step 6 fails, it checks out the previous SHA and restarts the web service. A migration that already ran is **not** rolled back automatically: the operator restores the step-5 snapshot. `deploy.sh --rollback` re-deploys the previous SHA.

**First-time move from the Mac** (one evening, after the auth and pipeline code is on the branch):
1. On the Mac, stop the scheduled runs: `launchctl bootout gui/$(id -u)/com.kshitij.jobseeker` (keep the web agent until the cutover).
2. Snapshot the DB: `sqlite3 data/jobseeker.db ".backup '/tmp/js-move.db'"`, then `PRAGMA integrity_check` on the copy.
3. `scp` that DB, plus `profile/` (resume PDF, `facts.json`, `preferences.yaml` for the onboarding import), to `/srv/jobseeker/data/import/`.
4. On the server:
   - `jobseeker migrate --import /srv/jobseeker/data/import`: v1 assigns every existing row to `users.id=1` (`OWNER_EMAIL`), and onboarding's importer moves preferences and facts into the DB;
   - `integrity_check`, then row counts compared with the Mac (jobs 3,948 and applications as of the cutover).
5. Sign in as the owner. Check Today, Jobs, one Job detail and Pipeline. Run `jobseeker tick` once by hand.
6. On the Mac, `launchctl bootout` the web agent and `tailscale serve reset`. Keep the Mac DB untouched for 2 weeks as the rollback.

Gmail: the old Desktop-client `token.json` doesn't move. The owner reconnects through the new web flow (outreach proposal).

## (g) Oracle idle reclaim

- Oracle reclaims **idle Always Free** instances. The rule: over 7 days, the 95th-percentile CPU is below 20%, network is below 20%, and (for A1) memory is below 20% *(verify)*. This app idles almost all day, so **it will meet that rule.**
- **Mitigation, recommended:** upgrade the account to **Pay As You Go**. Always Free resources stay free, idle reclaim doesn't apply to PAYG accounts *(verify)*, and capacity errors get rarer. The risk is accidental paid resources, so set a **₹100 monthly budget alert** and create nothing outside the Always Free list.
- **Not recommended:** CPU-burner "keep-alive" scripts. They waste power, go against the spirit of the free tier, and are fragile.
- **Backstop either way:** the nightly encrypted off-site backup (extras proposal §b) plus `bootstrap.sh` mean a reclaimed VM is rebuilt in about an hour. Losing at most one day of data is acceptable.

## (h) Monitoring

- **Uptime:** UptimeRobot free (5-minute checks, email alerts) on `HEAD https://<sub>.duckdns.org/healthz`. It catches Caddy, certificate, DNS, VM and web-process failures, and a DB or schema failure through the 503.
- **Runs:** a Healthchecks.io free check as `HEALTHCHECK_PING_URL`, pinged by `tick` after each successful daily run and backup, with a 26-hour grace. It catches a dead timer, a stuck lock or a failing pipeline.
- **On the box:** `systemctl --failed`, `journalctl -u jobseeker-tick`, and the admin page's run notes and backup status (extras proposal).
- **Certificates:** Caddy renews 30 days before expiry. A failed renewal eventually shows up as an uptime failure, and the UptimeRobot TLS-expiry alert gives earlier warning.

## Open questions for the user

1. Upgrade to Pay As You Go (recommended for reclaim and capacity) or stay pure free tier and accept the reclaim risk?
2. The DuckDNS subdomain name.
3. Off-site backups: Cloudflare R2 or Backblaze B2 (both have a free 10 GB tier and both need a signup).
