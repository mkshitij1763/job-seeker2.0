# Multi-user, sub-project 1: hosting and deployment (design)

Date: 2026-10-08 · Branch: `multi-user` (merged into `main` only when the user says so)
Source: `docs/superpowers/research/2026-10-08-hosting-proposal.md`, hosting spike run `37777276970` (branch `spike/hosting`, throwaway).

## Goal

Run Job Seeker on an always-on public server so the owner and two roommates can use it from phone and web without the Mac being awake and without Tailscale. The server costs nothing beyond what the user approved: a Google Cloud Always Free **e2-micro** VM (us-central1) with a ₹100 budget alert, a free DuckDNS subdomain, and Backblaze B2's free tier for off-site backups. The user's hard ceiling is ₹300–400/month.

> **Host change (user, 2026-10-09):** Oracle Always Free was the original choice, but its signup failed twice on card verification. GCP e2-micro replaces it. Oracle remains a later option: run `bootstrap.sh` on an Oracle VM and `jobseeker restore` the latest backup (the script still handles Oracle's iptables REJECT rule).

**Success:** `https://<sub>.duckdns.org` serves the app over valid HTTPS. The daily run happens at 11:15 IST from the server. A deploy is one command from the Mac. All of the owner's existing data (jobs, applications, drafts and contacts) is on the server and unchanged. Losing the VM costs at most one day of data and about an hour to rebuild.

## Non-goals

- Docker, Kubernetes, CI/CD deploys, or more than one VM.
- A paid domain, a CDN or Cloudflare Tunnel.
- High availability. One VM, and a restore from backup if it's lost.
- Opening port 25. `contacts.smtp_verify` is `off` on the server (outreach spec). The `SmtpVerifier` code stays for a future host that allows it.
- A Mac-side job fetcher. The spike showed LinkedIn, Naukri, Indeed and the ATS APIs all answer from datacenter addresses.
- Automatic DB rollback on a failed deploy (see Errors).

## Decisions this design relies on

| Decision | Source |
|---|---|
| GCP Always Free e2-micro (x86_64, 1 GB RAM), us-central1, 30 GB **Standard** persistent disk, ephemeral IP, ₹100 budget alert (replaces Oracle A1) | user, 2026-10-09 |
| HTTPS via Caddy + a DuckDNS subdomain; the subdomain is chosen at signup and only ever appears as config (`BASE_URL`) | user / coordinator |
| uv on the host, no Docker; systemd replaces launchd | hosting proposal, accepted |
| Backblaze B2 for off-site backups | coordinator ruling |
| `jobseeker migrate [--dry-run]` (auth spec): refuses while another process holds the DB, takes its own pre-migration backup | auth spec |
| `jobseeker tick` every 5 minutes; the 11:15 IST schedule and the run lock live in the app | per-user pipeline spec |
| `GET`/`HEAD /healthz` and `HEALTHCHECK_PING_URL` | extras spec |
| Every locked package has a cp313 manylinux wheel for both aarch64 and x86_64 (glibc ≤ 2.34; Ubuntu 24.04 has 2.39); `http-ece` is the only sdist; `tls-client` isn't used, `curl-cffi` is | `uv.lock` checks, 2026-10-08 (aarch64) and 2026-10-09 (x86_64) |

## Design

### 1. Server shape

- GCP **e2-micro** (0.25 vCPU, bursts to 2; **1 GB RAM**) in **us-central1** (us-west1 or us-east1 are also free; no other region is), **30 GB Standard persistent disk** (NOT the default Balanced, which is billed), **Ubuntu 24.04 LTS x86_64**, ephemeral external IP (no static IP; DuckDNS follows the address, and the updater timer re-registers it after a stop/start).
- 1 GB is tight, so `bootstrap.sh` adds a **2 GB `/swapfile`** (`vm.swappiness=10`), and `jobseeker-tick.service` runs with `MemoryHigh=600M` (soft: reclaimed into swap, never OOM-killed) and `Nice=10`, so a run never starves the web service.
- Latency: about 220–280 ms from India to us-central1. Pages are small and server-rendered, so it's acceptable for 3 users.
- **Egress** (free: 1 GB/month to most destinations, then billed): nightly encrypted backups of a few MB to B2 are ~0.1–0.3 GB/month; three users' pages and htmx swaps are ~50–150 MB/month; JobSpy/ATS fetches are mostly *ingress* (free). Expected total: well under 0.5 GB. The ₹100 budget alert catches an overrun.
- Python 3.13 comes from `uv python install 3.13` (Ubuntu ships 3.12).
- The VM's clock stays UTC. The app converts to `Asia/Kolkata` itself (pipeline spec, `tzdata`).
- Layout, all owned by the `jobseeker` system user (`/usr/sbin/nologin`, home `/srv/jobseeker`):

```
/srv/jobseeker/
  app/               git checkout (detached at the deployed SHA); also holds companies.yaml and rubric.yaml
  data/              jobseeker.db, users/<id>/resume.pdf, logs/, backups/, deploy.log
  profile/           only during the first migration (Mac import), then removed
  config/app.yaml    global settings (onboarding spec), written by migration v2
  .env               secrets, 600
  .ssh/              GitHub deploy key, 600
```

`JOBSEEKER_HOME=/srv/jobseeker`, so `Settings.data_dir`, `profile_dir` and `db_path` resolve as on the Mac.

`companies.yaml` and `rubric.yaml` stay in the code checkout (`/srv/jobseeker/app`), not in `JOBSEEKER_HOME`: `AppConfig.companies_path` and `rubric_path` default to the checkout (onboarding spec §4.1). They're versioned with the code and change only through a deploy. `bootstrap.sh`, `deploy.sh` and the data move never copy them into `/srv/jobseeker`.

### 2. What the user does by hand

The owner does this once, about 45 minutes. **(verify)** items must be checked against the provider's current docs while doing the step; if a check fails, stop and tell the developer.

1. **Google Cloud signup:** use the same Google Cloud account as the OAuth client (or a new project in it); enable billing with a card (the free trial credit is separate and isn't needed); create a **budget of ₹100/month** with email alerts at 50% and 100% (Billing → Budgets & alerts). (verify) e2-micro is still in the Always Free list for us-central1/us-west1/us-east1 at cloud.google.com/free.
2. **SSH key** on the Mac: `ssh-keygen -t ed25519 -f ~/.ssh/jobseeker_gcp -C ubuntu`. Add the public key under Compute Engine → Metadata → SSH keys (username `ubuntu`, from the key comment), plus an `~/.ssh/config` entry `Host jobseeker` (HostName = the VM's external IP, User `ubuntu`, IdentityFile as above). If the external IP changes after a stop/start, update HostName (or use `<sub>.duckdns.org`).
3. **VM** (Compute Engine → Create instance), exactly:
   - region **us-central1** (or us-west1/us-east1), any zone; machine **e2-micro**;
   - boot disk: **Ubuntu 24.04 LTS (x86/64)**, type **Standard persistent disk** (NOT the default Balanced), size **30 GB**;
   - networking: external IPv4 **Ephemeral**; do **not** reserve a static IP (it's billed when unattached, and DuckDNS covers the changing address);
   - firewall: tick **Allow HTTP traffic** and **Allow HTTPS traffic** at creation (they create the VPC rules for 80/443); port 22 is open by default.
4. **(No separate firewall step.)** Check under VPC network → Firewall that `default-allow-http` and `default-allow-https` exist and target the VM's `http-server`/`https-server` tags. Port 8000 is never opened.
5. **DuckDNS:**
   - sign in, create `<sub>`, point it at the VM's external IP, copy the token;
   - (verify) the current inactivity-expiry rule, so the updater's 15-minute interval satisfies it.
6. **Google OAuth** (the Web client from the auth spec): add the redirect URIs `https://<sub>.duckdns.org/auth/callback` and `https://<sub>.duckdns.org/gmail/callback`. (verify) Google accepts `<sub>.duckdns.org` as an authorized domain, given that `duckdns.org` is on the public-suffix list. If it doesn't, stop: the domain choice needs revisiting.
7. **Backblaze B2** (extras spec §2):
   - create the bucket and lifecycle rules;
   - create a **write-only application key** limited to that bucket.
8. **Run `bootstrap.sh`** (§3). When it prints the deploy key, add it in GitHub under repo → Settings → Deploy keys (read-only), then re-run it.
9. **Fill `.env`** (§6) with `sudo -u jobseeker nano /srv/jobseeker/.env`. Never paste secrets into chat.
10. **Monitoring sign-ups** (§9): UptimeRobot and Healthchecks.io.

### 3. `scripts/server/bootstrap.sh`

- Idempotent: every step checks before acting, and a re-run on a configured box changes nothing and exits 0. It runs as root:
  `ssh jobseeker 'sudo BASE_URL=https://<sub>.duckdns.org OWNER_EMAIL=<email> BRANCH=multi-user bash -s' < scripts/server/bootstrap.sh`
  It refuses to start unless `BASE_URL` (must start with `https://`), `OWNER_EMAIL` and `BRANCH` are all set.
- **Phase A, the system:**
  1. apt: `sqlite3 git curl netfilter-persistent unattended-upgrades`; Caddy from its official apt repository (the signed-key steps from Caddy's install docs).
  2. Create the `jobseeker` user and the layout in §1.
  3. Swap (2026-10-09, for the 1 GB e2-micro): a 2 GB `/swapfile` (fallocate, chmod 600, mkswap, swapon), its `/etc/fstab` line, and `vm.swappiness=10` in `/etc/sysctl.d/90-jobseeker-swap.conf`. Each step is skipped when already done.
  4. Firewall (§5).
  5. unattended-upgrades (§7).
  6. journald: set `SystemMaxUse=500M` in `/etc/systemd/journald.conf.d/jobseeker.conf`.
  7. If `/srv/jobseeker/.ssh/id_ed25519` is missing, generate it (no passphrase), print the public key with "Add this as a read-only deploy key, then re-run", and exit 0.
- **Phase B, the app** (runs only once `git ls-remote` with the deploy key succeeds):
  1. As `jobseeker`: install uv into `~/.local/bin` (the official installer); `uv python install 3.13`.
  2. Clone into `app/`, check out `origin/$BRANCH` detached, then `uv sync --frozen`. A failure here stops the bootstrap before any service is enabled. That's the real-hardware proof of the wheel check.
  3. Create `.env` from `scripts/server/env.example` if it's missing (mode 600, values empty), and say so.
  4. Render the templates in `scripts/server/templates/` (§4, §5) with `envsubst`, using only `${DOMAIN}`, `${OWNER_EMAIL}` and `${HOME_DIR}`. `DOMAIN` is the host part of `BASE_URL`. Install them into `/etc/systemd/system/` and `/etc/caddy/Caddyfile`.
  5. Write `/etc/duckdns.env` (root, 600) with `DUCKDNS_DOMAIN` (the first label of `DOMAIN`) and `DUCKDNS_TOKEN`. The token is read from the terminal with `read -s` if the file is missing; it's never passed as an argument.
  6. `systemctl daemon-reload`; enable and start `caddy` and `duckdns.timer`.
  7. Enable `jobseeker-web` and `jobseeker-tick.timer` **only if** all of these hold; otherwise it prints which ones are missing:
     - `.env` has non-empty `SECRET_KEY`, `OWNER_EMAIL`, `BASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `TOKEN_KEY`. `create_app` refuses to start without them (auth spec §4.1, outreach spec §6);
     - `data/jobseeker.db` and `config/app.yaml` exist (onboarding spec §4.1).
- It ends with a status block: each unit's state, the Caddy certificate state, and what's left to do.

### 4. systemd units (templates in `scripts/server/templates/`)

`jobseeker-web.service` replaces `com.kshitij.jobseeker.web`:

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

`jobseeker-tick.service` + `.timer` replace `com.kshitij.jobseeker`:
- **service:**
  - `Type=oneshot`;
  - the same `User`, `WorkingDirectory`, `EnvironmentFile`, `Environment` and hardening as the web service;
  - `ExecStart=… uv run --frozen --no-sync jobseeker tick`;
  - `TimeoutStartSec=3h`, a ceiling above the longest run so far (78 minutes);
  - `MemoryHigh=600M` and `Nice=10` (2026-10-09, e2-micro): above 600 MB the kernel reclaims the tick's memory into swap instead of letting it squeeze the web service. It's soft (never `MemoryMax`), so a heavy run slows down but is never OOM-killed.
- **timer:** `OnCalendar=*:0/5`, `Persistent=true`, `AccuracySec=30s`.
- **overlap:** systemd won't start the oneshot again while it's active, and the app's `locks` row is the real guard.

**Code change, the only one in this sub-project:** `jobseeker serve` gains `--proxy-headers/--no-proxy-headers` (default off). When on, `uvicorn.run` gets `proxy_headers=True, forwarded_allow_ips="127.0.0.1"`, so `request.url.scheme` is `https` behind Caddy. The `BASE_URL`/Origin checks in the auth spec rely on that. It still binds `127.0.0.1` only (`cli.py:131`).

`scripts/server/js` is the manual-CLI wrapper:

```bash
sudo -u jobseeker env JOBSEEKER_HOME=/srv/jobseeker \
  bash -c 'set -a; . /srv/jobseeker/.env; cd /srv/jobseeker/app && exec ~/.local/bin/uv run --frozen --no-sync jobseeker "$@"' _ "$@"
```

Usage: `js migrate --dry-run`, `js run --user …`, `js restore …`.

### 5. Caddy, DuckDNS and the firewall

**Caddyfile template:**

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

- Certificates come from Let's Encrypt over the HTTP-01 challenge (port 80), and port 80 redirects to HTTPS.
- No `encode`: the app already gzips (`deb1441`).
- `request_body max_size 6MB` is the proxy-level cap for resume uploads: the onboarding spec's limit is 5 MB, plus room for the multipart overhead. Larger requests get 413 before they reach the app.
- Fallback, not built: a DNS-01 Caddy build with the `caddy-dns/duckdns` plugin, if HTTP-01 is ever blocked.

**DuckDNS:**
- `duckdns.service`: oneshot as root with `EnvironmentFile=/etc/duckdns.env` and `ExecStart=/usr/bin/curl -fsS -o /run/duckdns.out "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip="`. Followed by `ExecStartPost=/usr/bin/grep -qx OK /run/duckdns.out`, so a `KO` fails the unit.
- `duckdns.timer`: `OnBootSec=1min`, `OnUnitActiveSec=15min`.

**Firewall:** on GCP the real firewall is the VPC rules from §2 step 3; the image's iptables policy is ACCEPT, so the step below only adds redundant ACCEPT rules and is harmless. It exists for Oracle (a later option), whose Ubuntu images ship `/etc/iptables/rules.v4` with an `INPUT` chain that ends in `REJECT --reject-with icmp-host-prohibited`. The security list alone is not enough.
- `bootstrap.sh`:
  - finds the REJECT's position with `iptables -L INPUT --line-numbers`;
  - inserts `-p tcp -m state --state NEW --dport 443 -j ACCEPT` and the same for `80` **above** it, skipping each rule if `iptables -C` says it's already there;
  - runs `netfilter-persistent save`;
  - does the same for `ip6tables` when the VM has a global IPv6 address.
- **ufw is not installed or enabled**, because it conflicts with `netfilter-persistent`. (verify) Oracle's current Ubuntu image still ships this REJECT rule; if it doesn't, the step is a no-op.
- Port 8000 is never opened.

**SSH:**
- `PermitRootLogin no` and `PasswordAuthentication no` in `/etc/ssh/sshd_config.d/jobseeker.conf`, set only after confirming the `ubuntu` user's key login works (it's the session running the script).
- No fail2ban in v1.

### 6. Secrets

- `/srv/jobseeker/.env`: `jobseeker:jobseeker`, mode **600**.
  - Loaded by systemd `EnvironmentFile`, and by `scripts/server/js` for manual use.
  - Never in git: `.env` is already ignored, and `scripts/server/env.example` holds names only.
  - Never in backups (extras spec).
  - The owner keeps a copy in their password manager.
- Variable names, used identically by all multi-user specs:

| Variable | Defined by | Notes |
|---|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | today | LLM chain |
| `TAVILY_API_KEY`, `APIFY_API_TOKEN`, `HUNTER_API_KEY` | today | shared quotas |
| `BACKUP_DIR` | today | `/srv/jobseeker/data/backups` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | auth | Web client; Gmail uses the same one |
| `SECRET_KEY` | auth | 32 random bytes, base64 |
| `OWNER_EMAIL` | auth | |
| `BASE_URL` | auth | `https://<sub>.duckdns.org`, no trailing slash; the only place the subdomain appears |
| `COOKIE_SECURE` | auth | `true` |
| `TOKEN_KEY` | outreach | 32 random bytes, base64; different from `BACKUP_KEY` |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` | extras | from `jobseeker vapid-keys` |
| `BACKUP_KEY` | extras | 32 random bytes, base64 |
| `BACKUP_S3_ENDPOINT`, `BACKUP_S3_REGION`, `BACKUP_S3_BUCKET`, `BACKUP_S3_KEY_ID`, `BACKUP_S3_SECRET` | extras | B2's S3-compatible endpoint |
| `HEALTHCHECK_PING_URL` | extras | optional |

- `JOBSEEKER_HOME` is set in the units, not in `.env`.
- `DUCKDNS_DOMAIN`/`DUCKDNS_TOKEN` live only in `/etc/duckdns.env` (root, 600).
- Generate keys with `js gen-key`, a tiny CLI command that prints `base64(secrets.token_bytes(32))`. It's added by the extras spec, which needs it first.

### 7. Unattended upgrades

`/etc/apt/apt.conf.d/52jobseeker-upgrades` sets:
- `Unattended-Upgrade::Automatic-Reboot "true"`;
- `Unattended-Upgrade::Automatic-Reboot-Time "21:30"`, which is UTC, so 03:00 IST, outside the 11:00–23:59 usage window.

After a reboot, `jobseeker-web`, `caddy` and both timers come back by themselves. A tick that was running is killed, its lock heartbeat goes stale after 15 minutes, and the next tick resumes the work (pipeline spec).

### 8. Deploy: `scripts/deploy.sh`

Run from the Mac:

```
scripts/deploy.sh [--branch multi-user] [--host jobseeker] [--dry-run] [--rollback]
```

1. **Locally:** `git fetch origin`, then resolve `SHA = origin/<branch>`. Warn, without failing, if the local `HEAD` differs from `SHA`, i.e. there are unpushed commits.
2. Run `scripts/server/update.sh` on the host as root, with `ssh <host> 'sudo bash -s' -- <SHA> < scripts/server/update.sh`. The Mac's copy of the script is used, so a broken script on the server can't block a fix. It does, stopping at the first failure:
   1. **Refuse** if `jobseeker-tick.service` is active, printing its start time ("A run is in progress since 11:15; try again later.").
   2. `systemctl stop jobseeker-tick.timer`.
   3. As `jobseeker`: `git fetch` and `git checkout --detach <SHA>`. Append `<date> <old SHA> → <SHA> user_version=<before>` to `data/deploy.log`.
   4. `uv sync --frozen`.
   5. `systemctl stop jobseeker-web`, then `js migrate`, which backs up first and refuses if the DB is busy. Append `user_version=<after>` to the log.
   6. `systemctl start jobseeker-web`, then poll `curl -fsS https://<DOMAIN>/healthz` for up to 30 s.
   7. `systemctl start jobseeker-tick.timer`.
3. **If step 6 fails:** check out the old SHA, `uv sync --frozen`, start the web service and the timer, and print the journal tail.
   - If the migration in step 5 changed `user_version`, don't start the web service. Print the path of the pre-migration backup and the restore steps instead. The old code can't run on the new schema, so this needs a human.
4. `--rollback`: deploy the previous SHA from `deploy.log`, under the same refusal rules.
5. `--dry-run`: print every command without running anything on the host.

Downtime per deploy is a few seconds, while the web service is stopped for `migrate`.

### 9. Monitoring

- **UptimeRobot** free tier: an HTTP(S) monitor on `https://<sub>.duckdns.org/healthz`, method HEAD, every 5 minutes, emailing the owner. Turn on its SSL-expiry alert.
- **Healthchecks.io** free tier: one check with period 1 day and grace 2 hours, so a missing ping alerts after 26 hours. Its URL goes in `HEALTHCHECK_PING_URL`; `tick` pings it after each successful scheduled run and backup (extras spec).
- **On the box:** `systemctl --failed`; `journalctl -u jobseeker-tick -S today`; `journalctl -u jobseeker-web -n 100`; the admin page's run notes and backup status.

### 10. First move from the Mac (one evening)

Prerequisites: the deployed branch has all multi-user migrations (v1 auth, v2 onboarding, v3 extras, v4 pipeline, v5 outreach), `bootstrap.sh` has finished Phase B, and `.env` is filled.

1. **Mac:** `launchctl bootout gui/$(id -u)/com.kshitij.jobseeker`, which stops scheduled runs. Leave the web agent running for now.
2. **Mac:** take a consistent copy of the DB and check it:
   ```
   sqlite3 data/jobseeker.db ".backup '/tmp/js-move.db'"
   sqlite3 /tmp/js-move.db "PRAGMA integrity_check"
   ```
   It must print `ok`. Record the row counts per table (`sqlite3 … "SELECT name FROM sqlite_master WHERE type='table'"`, then `COUNT(*)` for each).
3. **Mac:** copy the files up:
   ```
   scp /tmp/js-move.db jobseeker:/tmp/
   scp profile/{resume.pdf,facts.json,preferences.yaml} jobseeker:/tmp/js-profile/
   ```
4. **Server:**
   - move the files into place as `jobseeker`: `/srv/jobseeker/data/jobseeker.db` and `/srv/jobseeker/profile/`;
   - run `js migrate --dry-run`, then `js migrate`. It runs v1 to v5 in order. v1 assigns every row to user 1 (`OWNER_EMAIL`); v2 imports `profile/` into `user_prefs`, `user_facts` and `data/users/1/resume.pdf`, and writes `config/app.yaml`; v4 back-fills the owner's `scores.profile_hash`; v5 turns outreach on for the owner;
   - compare the row counts with step 2: each existing table matches, and the only differences are the new tables.
5. **Server:** delete `/srv/jobseeker/profile/` and the `/tmp` copies. Re-run `bootstrap.sh`, so the web service and timer are enabled now that the DB exists.
6. **Phone:**
   - sign in as the owner at `https://<sub>.duckdns.org`;
   - open Today, Jobs, one Job detail and Pipeline, and check they match the Mac;
   - reconnect Gmail through the new web flow (the old `token.json` doesn't move);
   - run `js tick` once by hand and confirm it exits cleanly.
7. **Mac:** `launchctl bootout gui/$(id -u)/com.kshitij.jobseeker.web` and `tailscale serve reset`. Keep `data/jobseeker.db` untouched for 2 weeks as the rollback; after that, the user decides.

**Rollback during the move:** if anything before step 7 fails, the Mac DB is untouched. Re-bootstrap the Mac agents with `scripts/install_launchd.sh` and carry on as before.

## Errors

| Situation | Behaviour |
|---|---|
| `bootstrap.sh` without its env vars, or `BASE_URL` not `https://` | exits 1 before changing anything and names the missing value |
| Deploy key not yet added | Phase A finishes, prints the key, exits 0; Phase B runs on the next invocation |
| `uv sync --frozen` fails on ARM | bootstrap and deploy stop before any service changes; old code keeps serving |
| `.env` incomplete | services aren't enabled; the missing names are printed (values never) |
| Caddy can't get a certificate (port 80 closed, DNS not pointing yet) | Caddy retries on its own schedule; bootstrap's status block shows the Caddy journal tail and the three likely causes (security list, iptables, DuckDNS IP) |
| DuckDNS update returns `KO` | `duckdns.service` fails; it shows in `systemctl --failed`, and UptimeRobot catches a real outage |
| Deploy while a run is in progress | refused, with the run's start time; nothing changed |
| `migrate` refuses (DB busy) or fails | the deploy stops; the web service is restarted on the old SHA only if `user_version` is unchanged, otherwise the pre-migration backup path is printed |
| `/healthz` not 200 within 30 s after deploy | automatic code rollback as in §8.3 |
| VM reclaimed or lost | create a new VM (§2 steps 3–4), run `bootstrap.sh`, `js restore` the latest B2 backup (extras spec), re-run `bootstrap.sh`; aim for about 1 hour |
| PAYG charge appears | the budget alert emails at ₹100; the owner deletes any non-Always-Free resource. The scripts never create cloud resources |

## Testing

Infrastructure scripts are tested where it's cheap and safe; the real proof is the acceptance checklist on the VM.

- **`tests/test_server_templates.py`** (pytest, no network):
  - Rendering every file in `scripts/server/templates/` with `envsubst` semantics (`string.Template.substitute` with the same three variables) leaves no `${…}` behind.
  - The units contain `User=jobseeker`, `EnvironmentFile=`, `JOBSEEKER_HOME=`, `--frozen --no-sync`, and `--proxy-headers` on the web unit only.
  - The timer has `OnCalendar=*:0/5` and `Persistent=true`.
  - The Caddyfile proxies to `127.0.0.1:8000`.
  - No template or script contains anything matching a secret pattern (`gsk_`, `tvly-`, `apify_api_`, a 32+ char base64 run, `BEGIN … PRIVATE KEY`).
  - `env.example` lists exactly the names in §6 with empty values. The expected list is a constant in the test, copied from §6.
- **`tests/test_cli_serve.py`:** `serve --proxy-headers` calls `uvicorn.run` (monkeypatched) with `proxy_headers=True, forwarded_allow_ips="127.0.0.1", host="127.0.0.1"`; without the flag, it calls it as today.
- **Shell:** `bash -n` on every script in `scripts/server/` and on `scripts/deploy.sh`, run from a pytest test. `shellcheck` runs too if it's installed (skipped otherwise).
- **`deploy.sh --dry-run`** against a fake host name prints the expected command sequence in order (refuse check, stop timer, checkout, sync, stop web, migrate, start web, healthz, start timer). It's a pytest test with `ssh` replaced by a stub script on `PATH`.
- **Manual, on the VM** (the acceptance checklist below): a full bootstrap, a re-run with no changes, a deploy, a forced failed deploy (a commit whose app fails `/healthz`, on a throwaway branch), and a reboot.

## Acceptance criteria

1. Every **(verify)** item in §2 and §5 is ticked, or a deviation is written into this spec before building on it.
2. `bootstrap.sh` completes on a fresh Ubuntu 24.04 x86_64 e2-micro, and a second run reports no changes. `swapon --show` lists the 2 GB `/swapfile`, and it survives a reboot.
3. `uv sync --frozen` succeeds on the VM with no compiled source builds (the pure-Python `http-ece` sdist from the extras spec is the only sdist); `uv pip list` matches `uv.lock`.
4. `curl -I https://<sub>.duckdns.org/healthz` returns `200` with a valid Let's Encrypt certificate. `http://` redirects to `https://`. Port 8000 is unreachable from outside (`nc -z <ip> 8000` fails).
5. The VPC firewall allows only 22, 80 and 443 to the VM (`gcloud compute firewall-rules list` or the console), and port 8000 is unreachable from outside.
6. After a reboot, the web service, Caddy, `jobseeker-tick.timer` and `duckdns.timer` are active with no manual step.
7. The 11:15 IST scheduled run happens on the server the next day; Healthchecks.io receives its ping.
8. `scripts/deploy.sh` deploys a new commit with `/healthz` green. A deliberately broken commit is rolled back automatically. A deploy during a run is refused.
9. After the Mac move, row counts match the Mac snapshot, the owner sees the same Today, Jobs, Job detail and Pipeline, and the Mac launchd agents and `tailscale serve` are off.
10. A restore drill from the latest B2 backup onto a scratch directory on the VM passes `integrity_check` and matches the live row counts (extras spec).
11. `.env` is mode 600 and owned by `jobseeker`; `git grep` on the deployed branch finds no secret values.
12. The GCP budget alert exists at ₹100; after one week the billing report shows ₹0 (the disk is Standard 30 GB, no static IP, egress under 1 GB).
