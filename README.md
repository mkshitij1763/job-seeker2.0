# job-seeker2.0

A small, invite-only job-search app for a few people. Every morning it fetches new jobs once for everyone (LinkedIn, Naukri, Indeed India, plus the Greenhouse, Lever and Ashby boards of companies it has found). Then it filters and scores them against **each user's own** preferences and resume. For users with outreach turned on, it also finds the right people at the company and drafts an email and a LinkedIn note. **It never sends anything.** Approving a job creates a draft in that user's own Gmail, and they press Send themselves.

It runs on one small server (Oracle Cloud Always Free, Caddy for HTTPS on a DuckDNS subdomain, SQLite on disk, systemd timers) and is used from a browser or as a phone home-screen app (PWA).

## What each person gets
- **Sign in with Google**, invite-only. Uninvited addresses see "Ask <owner> for an invite."
- **Onboarding** in 4 steps: roles, where (cities or remote), experience and pay, resume upload. Then the AI reads the resume into facts, which the user reviews and corrects. Matching uses only these facts.
- **Today, Jobs, Job detail, Pipeline**: the user's own matches, scores and applications. Nobody sees anyone else's.
- **Settings**: preferences (with a "hides N, brings back M" preview before saving), resume and facts, Gmail connection, daily push notification, **Download my data** (zip), **Delete my account**, sign out (here or everywhere).
- **Fetch now**: an on-demand run for that user, rate-limited.
- **Outreach** (per user, switched by the owner; off for new users): Find contacts, drafts, Approve → Gmail draft, follow-ups. With outreach off, a job page shows **Open job posting ↗** and **Mark applied**.
- **Admin** (owner only, `/admin`): invites, users (disable, outreach on/off), usage per person and per service.

Free quotas (Groq, Tavily, Apify, Hunter) are shared: each user gets an even share of each service, and the admin page shows who used what.

## Run it on a server (production)

The full runbook, with every **(verify)** step, is in `docs/superpowers/plans/2026-10-08-mu-hosting.md` Task 5 and `docs/superpowers/specs/2026-10-08-mu-hosting-design.md` §2–§10. In short:

1. **Accounts (by hand, once):**
   - **Oracle Cloud**: home region Mumbai or Hyderabad, upgraded to Pay As You Go, with a ₹100/month budget alert. Create a `VM.Standard.A1.Flex` VM (2 OCPU / 12 GB, Ubuntu 24.04 aarch64) with a reserved public IP. Add ingress TCP 80 and 443 to the security list.
   - **DuckDNS**: a `<sub>.duckdns.org` name pointing at that IP.
   - **Google Cloud**: an OAuth client of type **Web application**, with redirect URIs `https://<sub>.duckdns.org/auth/callback` and `https://<sub>.duckdns.org/gmail/callback`, and the Gmail API enabled. The consent screen stays in **Testing** mode. Add every person who will use outreach as a **test user**.
   - **Backblaze B2**: a bucket with lifecycle rules, and a write-only key for that bucket (nightly encrypted backups).
   - Optional: UptimeRobot on `/healthz` and a Healthchecks.io check for the daily run.
2. **Bootstrap** from the Mac, from the repo root. The script is idempotent; run it again after each step it asks for:
   ```
   ssh jobseeker 'sudo BASE_URL=https://<sub>.duckdns.org OWNER_EMAIL=<you@gmail.com> BRANCH=multi-user bash -s' < scripts/server/bootstrap.sh
   ```
   The first run prints a deploy key: add it in GitHub → repo → Settings → Deploy keys (read-only). The second run installs uv, the app and the systemd units, and creates `/srv/jobseeker/.env` (mode 600) and `/etc/duckdns.env`.
3. **Fill in `.env`** on the server: `sudo -u jobseeker nano /srv/jobseeker/.env`. Every name is listed in `scripts/server/env.example`. Make the keys with `js gen-key` (a different one for each of `SECRET_KEY`, `TOKEN_KEY` and `BACKUP_KEY`) and the push keys with `js vapid-keys`. Never paste secrets into chat or git.

   | Variable | Required | What it is |
   |---|---|---|
   | `GROQ_API_KEY` | yes | Scoring, drafting and resume reading (free at console.groq.com) |
   | `GEMINI_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | no | AI fallbacks when Groq's daily quota runs out |
   | `TAVILY_API_KEY` | for outreach | Find contacts |
   | `APIFY_API_TOKEN`, `HUNTER_API_KEY` | no | Better contact search and email lookup |
   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | yes | The Web OAuth client (sign-in and Gmail) |
   | `BASE_URL` | yes | Exactly the browser origin, `https://<sub>.duckdns.org`, with no trailing slash. Any other value gets every POST a 403 |
   | `SECRET_KEY` | yes | `js gen-key`; signs the short-lived OAuth cookie |
   | `TOKEN_KEY` | yes | `js gen-key`; seals Gmail tokens. Losing it only means everyone taps Reconnect Gmail |
   | `OWNER_EMAIL` | yes | The owner's Google address; that account becomes user 1 and admin |
   | `COOKIE_SECURE` | — | `true` (the default); `false` only for local http |
   | `BACKUP_DIR` | — | `/srv/jobseeker/data/backups` |
   | `BACKUP_KEY`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_REGION`, `BACKUP_S3_BUCKET`, `BACKUP_S3_KEY_ID`, `BACKUP_S3_SECRET` | no | Encrypted off-site copy in B2 |
   | `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` | no | Daily "N new matches" push notifications |
   | `HEALTHCHECK_PING_URL` | no | Pinged after each daily run |

   `JOBSEEKER_HOME` is set by the systemd units, not in `.env`.
4. **First run.** The web service and timer stay off until `scripts/server/ready.sh` finds the `.env` values above plus `data/jobseeker.db` and `config/app.yaml`.
   - **Moving from the old single-user Mac app:** follow the data move in hosting spec §10 (copy the DB and `profile/` up, then `js migrate --dry-run`, `js migrate`, then `js refilter` and `js refilter --apply` once). The cutover checklist in `HANDOFF.md` §8 covers it end to end.
   - **A fresh install:** `js init`, then `js migrate`. On a new database `migrate` changes no schema, but it writes `config/app.yaml` from `config/app.example.yaml` whenever that file is missing (it never overwrites one). Then sign in as the owner and go through onboarding.
   - Re-run `bootstrap.sh`; it enables `jobseeker-web` and `jobseeker-tick.timer`.
5. **Invite people.** Open `/admin` → Invites, add their Google address, and send them the site link yourself (invites send no email). For outreach, first add their Gmail address as a test user in Google Cloud, then turn **Outreach on** for them in `/admin` → Users. They tap Settings → Connect Gmail once.

**Day to day on the server:**
- `scripts/deploy.sh` (from the Mac) deploys the newest `multi-user` commit. It refuses during a run, migrates, checks `/healthz`, and rolls back by itself if that fails. `--dry-run`, `--sha`, `--rollback` and `--branch` are available.
- `js <command>` on the server runs the CLI as the service user with `.env` loaded: `js tick`, `js run --user <email>`, `js refilter [--user <email>] [--apply]`, `js rescore --user <email>`, `js backup`, `js restore <file> [--to DIR]`, `js companies`.
- `jobseeker-tick.timer` fires every 5 minutes. It does the daily run (`schedule.daily_at` in `config/app.yaml`, 11:15 IST by default) and the nightly backup, and serves Fetch now requests.
- Server-wide settings (models, thresholds, budgets, search knobs, the role catalog and city chips, `contacts.smtp_verify`) live in `/srv/jobseeker/config/app.yaml`. Restart the web service after changing it. Keep `contacts.smtp_verify: off` on Oracle, because port 25 is blocked.

## Run it locally (development)
1. `uv sync`
2. Pick a home for `data/` and `config/app.yaml`, e.g. `mkdir ~/js-home` (`config/app.yaml` is git-ignored if you use the repo itself).
3. `cp .env.example .env` and fill it in. For local use: `JOBSEEKER_HOME=~/js-home` (use the full path), `BASE_URL=http://127.0.0.1:8000`, `COOKIE_SECURE=false`, a Web OAuth client with the redirect URIs `http://127.0.0.1:8000/auth/callback` and `/gmail/callback`, and keys from `uv run jobseeker gen-key`.
4. `uv run jobseeker init`, `uv run jobseeker migrate` (writes `config/app.yaml`), then `uv run jobseeker serve`, then open http://127.0.0.1:8000 and sign in as `OWNER_EMAIL`.
5. `uv run jobseeker run` runs the pipeline once (add `--user <email>` for one person).

Tests: `uv run pytest -p no:warnings` and `node --test tests/js/*.test.mjs`. They need no network and no `.env`.

## Tuning
- Per user: everything in Settings.
- Server-wide: `config/app.yaml` (see above). `rubric.yaml` holds the scoring weights; bump its `version`, then run `js rescore --user <email>`.
- `companies.yaml`: optional favourite companies whose ATS boards are always fetched. Check a slug with `uv run python scripts/verify_companies.py <slug>`.

## AI fallbacks
Groq's free quota is per model and per day. When it runs out, scoring moves to Groq's qwen model, then Gemini (`GEMINI_API_KEY`), then Cloudflare Workers AI (`CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`). Drafting moves to Gemini Flash, then Cloudflare. Providers without keys are skipped. The chains are under `models: fallbacks:` in `config/app.yaml`. If a run hits every quota it stops cleanly, and the remaining jobs are picked up by the next run.

## Backups
Each night the tick writes a `.tar.gz` (the DB, resumes and a manifest with row counts) to `BACKUP_DIR`. With `BACKUP_KEY` and the B2 settings, it also uploads an encrypted copy, `daily/…` and `weekly/…` on Sundays, with retention set by the bucket's lifecycle rules. `js backup` makes one now. To restore, run `js restore <file.tar.gz | file.tar.gz.enc> --to <empty dir>`; it checks every checksum and the DB's integrity, and prints the counts.

## Cost and limits
- Free: Oracle Always Free, DuckDNS, Let's Encrypt, free tiers of Groq, Tavily, Apify and Hunter, B2's free 10 GB.
- Job-site scraping is free but unofficial; a blocked site is skipped for the day and listed in the run's notes.
- Gmail access uses the restricted `gmail.compose` scope in Testing mode, so Google shows an "unverified app" warning (Advanced → Continue), and consent can expire after about a week; the app then shows **Reconnect Gmail**.
