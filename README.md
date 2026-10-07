# job-seeker2.0

A personal job-search assistant that runs locally. Every morning it finds new jobs, scores them against your resume, and drafts an email and a LinkedIn message for each strong match. **It never sends anything.** Approving a job creates a Gmail draft, and you press Send yourself.

## Setup (once)
1. `uv sync`
2. `cp .env.example .env` and fill in `GROQ_API_KEY` (free, from https://console.groq.com/keys; no card needed).
3. Put your resume at `profile/resume.pdf`.
4. `uv run jobseeker init`. This extracts `profile/facts.json`. **Read it and fix any mistakes**, because every draft is checked against it.
5. Gmail:
   1. In Google Cloud Console, create an OAuth client of type **Desktop app** with the Gmail API enabled.
   2. Save it as `secrets/credentials.json`.
   3. Run `uv run jobseeker auth-gmail`. This asks only for permission to create drafts.
6. `scripts/install_launchd.sh` schedules the daily run (11:15, or on wake) and keeps the dashboard running on 127.0.0.1:8000 while you're logged in.
7. Phone access (optional): install Tailscale on the Mac and phone with the same account, then run `tailscale serve --bg 8000`. The dashboard is then at `https://<mac>.<tailnet>.ts.net`, reachable only from your own Tailscale devices while the Mac is awake. Undo with `tailscale serve --bg off`.

## Daily use
- `uv run jobseeker serve` → open http://127.0.0.1:8000
- **Inbox** keyboard shortcuts:

  | Key | Action |
  |---|---|
  | `j` / `k` | Move down / up |
  | `enter` | Open the job |
  | `s` | Skip |
  | `z` | Snooze for 3 days |

- **Job page:**
  1. Read the score and the job description.
  2. Use **Search LinkedIn** to find the contact, then paste their name and email.
  3. Edit the drafts if needed.
  4. Click **Approve → Gmail draft**.
  5. Send it from Gmail, then click **Mark sent**.
- **Pipeline:** every application at a glance, with a **follow up** badge after 5 days without a reply.
- **Find contacts:** on a job page, tap **Find contacts**. In about half a minute the People card lists the 3 most relevant people (via public LinkedIn search), each with a reason and a work email marked verified / likely / not found. **Approve** drafts emails to #1 and #2; 5 days after **Mark sent** with no reply, the pipeline offers **Email #3**. Each person has **Copy note** + **LinkedIn ↗** for a connection request. If the card shows the wrong **Email domain**, correct it once and run Find contacts again. Uses only free tiers (`TAVILY_API_KEY` required; `APIFY_API_TOKEN`, `HUNTER_API_KEY` optional, in `.env`); monthly usage is shown under the card.
- **On your iPhone:** open the Tailscale address (see Setup step 7) and Add to Home Screen. In the inbox, swipe a card left to **Skip** or right to **Snooze** (Undo appears for 6 seconds). On a job page, **Approve** is pinned to the bottom; everything else is under **More**.

## Tuning
- `profile/preferences.yaml`: cities, title allow/deny lists, budgets, models. Filters apply to new jobs; to apply changed rules to jobs already stored, run `uv run jobseeker refilter` (lists the changes) and then `uv run jobseeker refilter --apply`. Unapproved applications it removes are skipped, so Undo still works.
- `rubric.yaml`: scoring weights. Bump `version`, then run `uv run jobseeker rescore`.
- `profile/preferences.yaml` → `search:` the roles and cities searched every morning on LinkedIn, Naukri and Indeed India. Companies found there that use Greenhouse, Lever or Ashby are discovered automatically and fetched from their own boards afterwards; see them with `uv run jobseeker companies`.
- `companies.yaml`: optional favourites that are always fetched. Check a slug with `uv run python scripts/verify_companies.py <slug>`.

## AI fallbacks
Groq's free quota is per model and per day. When it runs out, scoring moves to Groq's qwen model, then Gemini (`GEMINI_API_KEY`), then Cloudflare Workers AI (`CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`). Drafting moves to Gemini 3.5 Flash, then Cloudflare. Providers without keys in `.env` are skipped. Change the chains under `models: fallbacks:` in `profile/preferences.yaml`.

## Backups
After each daily run, a gzipped copy of the database and `facts.json` is saved, keeping the last 7 days. It goes to `BACKUP_DIR` from `.env` if set, otherwise iCloud Drive (`JobSeeker-backups`) when iCloud Drive is on, otherwise `~/JobSeeker-backups`. Run `uv run jobseeker backup` at any time. To restore, stop the dashboard and run `gunzip -c <backup>.db.gz > data/jobseeker.db`.

## Cost and limits
- Free. Groq's free tier allows about 200K tokens/day per model, which covers about 35 scored and 10 drafted jobs a day (the default caps).
- If a run hits the daily quota it stops cleanly, and the remaining jobs are picked up the next morning.
- The scheduled run may take 30–60 minutes because it waits out per-minute limits. That's fine, since it runs before you're up.
- Job-site scraping is free but unofficial: LinkedIn may rate-limit after a few searches. A blocked site is skipped for the day and listed in the run's errors; everything else continues.
