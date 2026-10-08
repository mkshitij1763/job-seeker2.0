# Proposal: sub-project 6, small extras (draft, pre-spec)

**Date:** 2026-10-08 · **Branch:** `multi-user` · **Builds on:** the auth proposal (sessions, Origin check, guard test, public allow-list), onboarding (Settings), and the per-user pipeline (`run_all`, `tick`, `runs`, IST).
**Out of scope:** hosting specifics (the spike decides) and outreach (sub-project 5). The admin page was ruled on already (auth proposal + rulings): invites, users, a usage table.

---

## (a) Daily web push: "N new matches"

**Where we are:** there is a manifest (`src/jobseeker/web/static/manifest.webmanifest`, `scope: "/"`, `display: standalone`, linked at `src/jobseeker/web/templates/base.html:12`) but **no service worker**. iOS delivers web push only to a Home Screen web app on 16.4+, only after a permission request made from a user gesture, and every push must show a visible notification (silent pushes get the subscription revoked).

**Dependency: `pywebpush`.** It's maintained by Mozilla's web-push team: 2.5.0 was released 2026-08-30, and it requires Python ≥ 3.10. It handles VAPID signing (`py-vapid`) and payload encryption (`http-ece`, RFC 8291). Hand-rolling ECDH and AES-GCM payload encryption isn't worth the risk. The spec should check its dependency tree (`cryptography`, `requests`) before adding it.

**Keys:** a one-time `jobseeker vapid-keys` command prints a P-256 key pair for `.env`: `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` and `VAPID_SUBJECT=mailto:<owner>`. Apple rejects a missing or odd subject. Rotating the keys invalidates every subscription, so the keys belong in the secrets backup (b).

**Table (migration v3):**
```
push_subscriptions(id, user_id NOT NULL REFERENCES users, endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL,
                   auth TEXT NOT NULL, user_agent TEXT NOT NULL DEFAULT '', created_at, last_success_at,
                   failures INTEGER NOT NULL DEFAULT 0)
```
`UserPrefs` gains `notify_new_matches: bool = True`. `users` gains `notified_on` (an IST date), so a user gets at most one push per day.

**Service worker: `/sw.js`.** It's served by a route at the **root**, because a worker under `/static/` could only control `/static/`. It's public (it holds no data) and sent with `Cache-Control: no-cache`. It contains only:
- a `push` handler: `showNotification(title, {body, icon: "/static/icon-180.png", data: {url}})`;
- a `notificationclick` handler: focus an open window or `clients.openWindow(url)`.

**No fetch or offline caching in v1.** A caching worker would bring back the stale-HTML/CSS problem that the fingerprinted assets fixed (`src/jobseeker/web/app.py:21-39`).

**Permission UX** (a Settings card, "Daily match alerts"); the browser prompt is never shown on page load:
- **In a Safari tab** (not standalone; check `matchMedia('(display-mode: standalone)')`): show "Add Job Seeker to your Home Screen first: Share → Add to Home Screen, then open it from there." No button.
- **Standalone, permission `default`:** an "Turn on alerts" button. On click: `navigator.serviceWorker.register('/sw.js')`, then `Notification.requestPermission()` (inside the gesture), then `pushManager.subscribe({userVisibleOnly: true, applicationServerKey})`, then `POST /push/subscribe` (guarded, and passes the Origin check).
- **Granted:** "On for this device · Send a test · Turn off". Turning off calls `subscription.unsubscribe()` and `POST /push/unsubscribe`.
- **Denied:** "Notifications are blocked. Turn them on in iOS Settings → Notifications → Job Seeker."

The code is a small new `static/push.js`, loaded only on `/settings`.

**Sending:** in `run_all`, after a user's scoring finishes (`trigger` is `schedule` or `fetch_now`):
- N = applications for this user whose latest score is `apply` and that were created by this run.
- If N > 0, `notify_new_matches` is on, and `notified_on` isn't today in IST: send to each of the user's subscriptions.
- The payload is **counts only**, because lock screens are public: `{"title": "3 new matches", "body": "Top: 92 · Open Job Seeker", "url": "/?band=apply"}`.
- Each send has a 10-second timeout and runs after the user's work, outside any write transaction.
- A 404 or 410 deletes the subscription. Other errors increment `failures` (deleted at 5) and add a line to that user's run errors ("Couldn't send the match alert"). A push failure never fails the run.

## (b) Host-agnostic nightly backups with an optional off-site copy

**Today:** `jobseeker backup` (`src/jobseeker/cli.py:64-73`, `src/jobseeker/db/backup.py:13-34`) writes a gzipped snapshot of the database made with the SQLite backup API, which is safe while the web app writes (WAL). It also copies `facts.json` and keeps 7. On a server, facts live in the DB (sub-project 3) and resumes live in `data/users/`.

**Archive:** `jobseeker-YYYY-MM-DD.tar.gz` contains `jobseeker.db` (snapshot), `data/users/**` (resumes) and `config/app.yaml`. It's written to `BACKUP_DIR`, then renamed into place. **`.env` is excluded**. It goes in the owner's password manager, together with the VAPID keys and the encryption key (below).

**Encryption:** backups hold resumes and, later, Gmail tokens. `BACKUP_KEY` (32 random bytes, base64) encrypts the archive with AES-256-GCM through `cryptography` (already a transitive dependency, and needed by `pywebpush`) before it leaves the host, giving `.tar.gz.enc`. Without `BACKUP_KEY`, the off-site upload is refused, so plaintext never goes off-site. Local copies can stay plaintext, so a restore works even without the key.

**Off-site storage: S3-compatible, optional** (Cloudflare R2's free 10 GB or Backblaze B2's free 10 GB). It's set with `BACKUP_S3_ENDPOINT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_KEY_ID` and `BACKUP_S3_SECRET`.

**Recommendation: a minimal SigV4 `PUT` with `httpx`** (about 50 lines, using the existing dependency), rather than `boto3`. boto3 plus botocore is roughly 80 MB installed and releases almost daily (1.43.109 on 2026-10-07), all for one call.

**Retention lives in the bucket, so the client only ever PUTs (no list or delete code):**
- every night → `daily/jobseeker-<date>.tar.gz.enc`, with a bucket lifecycle rule: delete after **7** days;
- on Sundays (IST) → also `weekly/jobseeker-<date>.tar.gz.enc`, with a rule: delete after **28** days, which keeps 4 weeklies.

Both R2 and B2 support prefix lifecycle rules. The spec sets them once in the provider's dashboard and documents the steps. Local retention mirrors this: the newest 7 daily and 4 weekly files (`keep` extended in `backup.py:31-33`).

**Signing:** test SigV4 against AWS's published test vectors, and against a respx-mocked endpoint that checks the `Authorization` and `x-amz-content-sha256` headers.

**When it runs:** `tick` runs the backup once per IST day after the scheduled run, **even if the run failed**. The backup is independent of the run, as in `cli.py:58-61` today. A failed upload is logged and shown on the admin page, and the local copy still counts.

**Restore:** `jobseeker restore <file|s3-key> [--to DIR]` decrypts and unpacks into an empty directory and runs `PRAGMA integrity_check`. It never overwrites the live DB in place; the operator swaps directories. The test is a restore drill: back up the `seeded_two` fixture, restore it into a temp dir, and confirm both users' rows and the resume files match.

## (c) Health endpoint

- `GET /healthz` is public (in the auth guard's allow-list), needs no session, and is cheap:
  - It opens the DB, runs `SELECT 1`, and checks `user_version == LATEST`.
  - It returns `200 {"ok": true}`, or `503 {"ok": false, "check": "db" | "schema"}`.
  - No counts, users or versions are exposed. It's not rate-limited, because it does no work beyond that query.
- **Run freshness is a separate dead-man's switch,** not part of `/healthz`. That way an uptime pinger hitting `/healthz` every minute never touches the run tables. With an optional `HEALTHCHECK_PING_URL` (e.g. a free Healthchecks.io check), `tick` pings it after each successful scheduled run and backup. A missed ping, with a 26-hour grace, emails the owner.
- `HEAD /healthz` is answered as well, since some uptime checkers use HEAD.

## (d) Public landing page

`GET /` for a signed-out visitor renders `landing.html`. A signed-in visitor gets the Jobs inbox as today; the signed-out branch lives inside the route, and the route stays guarded for every other case. It uses `base.html` without the nav, the `ui.css` tokens, one card, and is phone-first. It carries `<meta name="robots" content="noindex">`, since the app is invite-only.

- **Headline:** "Your daily shortlist of product and analytics roles in India."
- **Three short lines:**
  - "Every morning it searches LinkedIn, Naukri, Indeed and company career pages for your roles and cities."
  - "Each job is scored against your resume, with the reasons, so you read 10 jobs, not 600."
  - "Built for your phone: add it to your Home Screen."
- **Primary button:** "Continue with Google" → `/login`. It follows Google's sign-in button branding guidelines (the official "G" mark and wording).
- **Note under the button:** "Invite-only. If you haven't been invited, ask Kshitij."
- **Privacy line:** "Your resume, preferences and applications are visible only to you. Download or delete them any time in Settings."
- **Footer:** "A personal project, not affiliated with LinkedIn, Naukri, Indeed or Google."

The "not invited" 403 page (auth proposal §b) reuses this layout with the invite note in place of the button.

## Tests

- **Push:**
  - subscribe and unsubscribe are guarded and CSRF-checked;
  - a duplicate endpoint is upserted;
  - `/sw.js` is served at the root with no-cache;
  - the send happens once per IST day, and only when N > 0 and the toggle is on;
  - 410 deletes the subscription, and 5 failures delete it;
  - the payload holds no job titles or companies;
  - a push failure doesn't fail the run (`pywebpush.webpush` is monkeypatched).
- **Backups:**
  - the archive holds the DB, `data/users/` and the config, and never `.env`;
  - an encrypt/decrypt round-trip works, and the upload is refused without `BACKUP_KEY`;
  - SigV4 matches the AWS test vectors;
  - daily and weekly prefixes are chosen on Sunday by the IST date;
  - local retention keeps 7 + 4;
  - the restore drill passes;
  - a failed upload keeps the local copy and doesn't stop the backup.
- **Health:** 200 when healthy; 503 on a schema mismatch; it works without a session; HEAD is answered.
- **Landing:** an anonymous `/` shows the landing page with the Google button and no app data; a signed-in `/` shows the inbox; the route-walk guard test still passes with the landing branch.

## Open points for the coordinator
1. Is client-side encryption of backups wanted, at the cost of one more key to keep safe? Proposed: yes, for off-site copies only.
2. R2 or B2 is a hosting-adjacent choice. Both work with the same code; I'd let the spike pick.
3. Should push also cover "Fetch now finished" for the user who asked? It's cheap, but a 2nd alert type. Proposed: v1 is the daily alert only.
