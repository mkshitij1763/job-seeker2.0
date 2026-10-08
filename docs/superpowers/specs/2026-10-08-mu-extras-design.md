# Multi-user, sub-project 6: small extras (design)

Date: 2026-10-08 · Branch: `multi-user` (merged into `main` only when the user says so)
Source: `docs/superpowers/research/2026-10-08-extras-proposal.md`, with the coordinator's rulings: daily push only; encryption for off-site copies only; Backblaze B2.
Builds on: the auth spec (users, sessions, Origin check, public allow-list, `jobseeker migrate`, `seeded_two`), the onboarding spec (`UserPrefs`, `AppConfig`, Settings page), the per-user pipeline spec (`run_all`, `tick`, `runs`, IST) and the hosting spec (env names, `/healthz` consumers).

## Goal

Four small things that make the hosted app feel finished and safe to run:

1. **A daily web push**, "N new matches", to each user's phone.
2. **Nightly backups** with an encrypted off-site copy in Backblaze B2.
3. **`/healthz`** for the uptime monitor, plus a dead-man's switch for the daily run.
4. **A public landing page** for signed-out visitors.

**Success:**
- A roommate who turned on alerts gets at most one notification a day, only when there are new `apply` matches, and it shows no job details on the lock screen.
- Every night a restorable archive exists on the VM and, encrypted, in B2.
- UptimeRobot and Healthchecks.io alert the owner within minutes, or 26 hours for the run check.
- A stranger opening the URL sees what the app is and a "Continue with Google" button, and no data.

## Non-goals

- Any other push type ("Fetch now finished", reminders, follow-ups). Daily only, per the ruling.
- Offline mode or a caching service worker. It would bring back the stale-asset problem the fingerprinted URLs fixed (`src/jobseeker/web/app.py:21-39`).
- Encrypting local backups. Only the off-site copy is encrypted, per the ruling.
- Reading, listing or deleting from B2 in code. The app only PUTs, and retention is a bucket lifecycle rule.
- Restoring straight from B2. The owner downloads the `.enc` file from B2's web UI and restores it from a local path.
- boto3, pywebpush, aiohttp or requests.
- Usage analytics, a marketing site, SEO.

## Design

### 1. Daily web push

**Dependencies:** `py-vapid` (1.9.4, VAPID JWT signing) and `http-ece` (1.2.1, RFC 8291 `aes128gcm` payload encryption).
- Both are pure Python and depend only on `cryptography`; `uv.lock` already has 50.0.2, and `py-vapid` needs ≥ 46.
- `py-vapid` ships a universal wheel. `http-ece` publishes **only an sdist** (checked 2026-10-08), but it's a single pure-Python module, so `uv sync` builds it in seconds with no compiler, on the Mac and on aarch64 alike.
- The request itself goes out through `httpx`, which the app already uses.
- **Not `pywebpush`:** 2.5.0 pulls in `aiohttp` and `requests` (checked on PyPI 2026-10-08), two HTTP stacks just to send one POST. Its remaining logic, the headers around the two libraries above, is about 40 lines.
- No crypto is hand-written: ECDH, HKDF and AES-GCM all stay inside `http-ece`, and JWT ES256 inside `py-vapid`.

**Keys:**
- `jobseeker vapid-keys` prints `VAPID_PRIVATE_KEY` (raw P-256 private key, base64url), `VAPID_PUBLIC_KEY` (uncompressed point, base64url, what the browser's `applicationServerKey` takes) and a suggested `VAPID_SUBJECT=mailto:<OWNER_EMAIL>`.
- If any of the three is empty, push is disabled: the Settings card says "Alerts aren't set up on this server", and sending is a no-op.
- Rotating the keys invalidates every subscription, so the owner keeps them with `.env` in the password manager.
- `jobseeker gen-key` prints `base64(secrets.token_bytes(32))` for `SECRET_KEY`, `TOKEN_KEY` and `BACKUP_KEY` (hosting spec §6).

**Data (migration v3):**

```sql
CREATE TABLE push_subscriptions (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  last_success_at TEXT,
  failures INTEGER NOT NULL DEFAULT 0
);
ALTER TABLE users ADD COLUMN notified_on TEXT;   -- IST date (YYYY-MM-DD) of the last match alert
```

**Delete and export coverage** (onboarding spec §4.7):
- `push_subscriptions` is added to the per-user delete list, before `users`. The explicit delete is the rule; `ON DELETE CASCADE` is only a backstop.
- It's left out of the export: endpoints and keys are device credentials, not the user's data. `users.notified_on` goes with the `users` row.

`UserPrefs` gains `notify_new_matches: bool = True`. That's a field in the onboarding spec's JSON, so no SQL is needed, and a missing key reads as `True`.

**Service worker `GET /sw.js`:**
- served from a route at the root, because a worker under `/static/` could only control `/static/`;
- public, so it's added to the auth guard's allow-list;
- `Content-Type: text/javascript`, `Cache-Control: no-cache`;
- the body is a static file, `web/static/sw.js`, read at startup. It has only two handlers:
  - `push`: parse the JSON, then `event.waitUntil(self.registration.showNotification(title, {body, icon: "/static/icon-180.png", badge: "/static/icon-180.png", data: {url}}))`;
  - `notificationclick`: close the notification, then focus an open same-origin window and navigate it to `data.url`, or `clients.openWindow(data.url)`.

There's no `fetch` handler.

**Settings card "Daily match alerts"** is rendered by `/settings` (onboarding spec). Its script is `static/push.js`, loaded only on that page. Its state comes from the browser, plus a server flag that says whether this device's endpoint is stored:

| Browser state | Card shows |
|---|---|
| No `PushManager`, or not standalone (`matchMedia('(display-mode: standalone)')` false) | "Add Job Seeker to your Home Screen first: Share → Add to Home Screen, then open it from there." No button. |
| Standalone, `Notification.permission == 'default'` | **Turn on alerts** button |
| `granted` and subscribed | "On for this device" · **Send a test** · **Turn off** |
| `denied` | "Notifications are blocked. Turn them on in iOS Settings → Notifications → Job Seeker." |

**Turn on** (all inside the click handler, so the permission prompt counts as user-initiated):
1. `navigator.serviceWorker.register('/sw.js')`, then `await navigator.serviceWorker.ready`.
2. `Notification.requestPermission()`.
3. `registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: <VAPID_PUBLIC_KEY bytes>})`.
4. `POST /push/subscribe` with the subscription JSON.

**Turn off:** `subscription.unsubscribe()`, then `POST /push/unsubscribe {endpoint}`.

The "Daily match alerts" toggle (`notify_new_matches`) sits in the same card and is saved with the Settings form.

**Routes** (all need a session and pass the Origin check):

| Route | Behaviour |
|---|---|
| `POST /push/subscribe` | Body: `{endpoint, keys: {p256dh, auth}}`. Validate: `endpoint` is `https://` and ≤ 1 KB; the keys are base64url and decode to 65 and 16 bytes. Then upsert by `endpoint`; an existing row is moved to this user, which handles a shared phone. Store `user_agent` cut to 200 chars. Return 204. |
| `POST /push/unsubscribe` | Body: `{endpoint}`. Delete it only if it belongs to the current user. Return 204 either way. |
| `POST /push/test` | Body: `{endpoint}`. Send `{"title": "Test alert", "body": "Alerts work on this device.", "url": "/settings"}` to that endpoint if it belongs to the user. At most 1 per user per minute (429 otherwise). Returns the outcome text the card shows. |

**Sending:** `push.notify_new_matches(conn, user_id, run_started_at, now)`.
- `run_all` (pipeline spec) calls it once per user, after that user's scoring finishes, when the trigger is `schedule` or `fetch_now`.
- It runs after the user's write transaction has committed, and never inside one.
- Steps:
  1. Return if push isn't configured, or `notify_new_matches` is off, or `users.notified_on` equals today's IST date.
  2. `N` = the user's applications with `created_at >= run_started_at` whose latest score band is `apply`, using the same band rule as the inbox. If `N == 0`, return. Also read `top` = the highest score among them.
  3. Payload, **counts only**, because the lock screen is public: `{"title": "N new matches" (singular for 1), "body": "Top: <top> · Open Job Seeker", "url": "/?band=apply"}`.
  4. For each of the user's subscriptions:
     - encrypt with `http_ece.encrypt(payload, private_key=<ephemeral P-256>, dh=p256dh, auth_secret=auth, version="aes128gcm")`;
     - `POST endpoint` with `Authorization: vapid t=<JWT>, k=<VAPID_PUBLIC_KEY>`, `Content-Encoding: aes128gcm`, `TTL: 86400`, `Urgency: normal`;
     - JWT claims: `aud` = the endpoint's origin, `exp` = now + 12 h, `sub` = `VAPID_SUBJECT`;
     - 10-second timeout.
  5. Results:
     - `201`/`200`/`202`: set `last_success_at` and reset `failures` to 0;
     - `404`/`410`: delete the row;
     - anything else, or a transport error: increment `failures` and delete the row at 5.
  6. If at least one send succeeded, set `users.notified_on` to today (IST). If every send failed, leave it unset, so a later run that day may try again. Add one line to the user's run notes: "Couldn't send the match alert."

A push failure never raises out of `notify_new_matches`.

### 2. Nightly backups with an encrypted B2 copy

**Module:** a new package `src/jobseeker/backup/`. It reuses the SQLite snapshot from `src/jobseeker/db/backup.py`, which `jobseeker migrate` also uses (auth spec), so that function's signature stays as it is.
- `archive.py`: `write_archive(settings, now) -> Path`.
- `crypto.py`: `encrypt(data, key) -> bytes` and `decrypt(blob, key) -> bytes`.
- `s3.py`: `put_object(client, cfg, key, body)` with SigV4.
- `nightly.py`: `nightly_backup(conn, settings, now, force=False) -> BackupResult`.
- `restore.py`.

**Archive:** `jobseeker-YYYY-MM-DD.tar.gz` (IST date), built in a temp directory and renamed into `BACKUP_DIR` when complete. It contains:
- `jobseeker.db`, a snapshot taken with the SQLite backup API, as today; safe under WAL while the web process writes;
- `data/users/**` (resumes);
- `config/app.yaml`;
- `MANIFEST.json`: `{created_at, user_version, row_counts: {table: n}, files: [{path, sha256}]}`.

It **never** contains `.env`, `secrets/`, or anything outside those paths. Archive members are added from an explicit list, not a directory walk of `JOBSEEKER_HOME`.

**Local retention:** keep the newest **7** daily archives plus the newest **4** archives made on a Sunday (IST). Anything else matching `jobseeker-*.tar.gz` is deleted. Older `jobseeker-*.db.gz` and `facts-*.json` from the Mac format are left alone.

**Encryption, off-site only:** `crypto.encrypt` produces `b"JSBK1" ‖ nonce (12 random bytes) ‖ AESGCM(key).encrypt(nonce, archive, aad=b"JSBK1")`.
- The key is `BACKUP_KEY`: 32 bytes, base64; a wrong length is a config error.
- The whole archive is held in memory (the DB is 27 MB today, so the archive is ~10 MB).
- A `.enc` file larger than 512 MB is refused with a clear error; that limit is far away.

**Upload:** `s3.put_object` is a path-style `PUT {BACKUP_S3_ENDPOINT}/{BACKUP_S3_BUCKET}/{key}` signed with AWS SigV4:
- service `s3`, region `BACKUP_S3_REGION`;
- headers `x-amz-content-sha256: <hex sha256 of body>` and `x-amz-date`;
- signed headers `host;x-amz-content-sha256;x-amz-date`;
- 60-second timeout, 2 retries on a transport error or 5xx.

About 60 lines with `hashlib`/`hmac` and `httpx`, no new dependency.

**Keys in the bucket:**
- every night: `daily/jobseeker-<date>.tar.gz.enc`;
- on Sundays (IST): also `weekly/jobseeker-<date>.tar.gz.enc` (a second PUT of the same bytes).

**B2 setup** (owner, once; hosting spec §2 step 7). Each **(verify)** item gets checked against B2's docs then:
1. Create a **private** bucket, then use "Lifecycle settings → custom":
   - `daily/`: hide after 7 days, delete 1 day after hiding;
   - `weekly/`: hide after 28 days, delete 1 day after hiding.
   (verify) B2 still expresses lifecycle as `daysFromUploadingToHiding` / `daysFromHidingToDeleting` per prefix.
2. Create an **application key** limited to that bucket with only the `writeFiles` capability. A compromised server then can't read or delete existing backups. (verify) S3 `PutObject` works with a `writeFiles`-only key; if it needs more, add the minimum and record it here.
3. Fill `.env`:
   - `BACKUP_S3_ENDPOINT=https://s3.<region>.backblazeb2.com`;
   - `BACKUP_S3_REGION=<region>` (for example `us-west-004`, the part between `s3.` and `.backblazeb2.com`);
   - `BACKUP_S3_BUCKET`, `BACKUP_S3_KEY_ID`, `BACKUP_S3_SECRET`.

**Bookkeeping (migration v3):**

```sql
CREATE TABLE backups (
  day TEXT PRIMARY KEY,                -- IST date
  local_path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  uploaded_at TEXT,                    -- NULL until the off-site PUT(s) succeed
  upload_error TEXT,                   -- last error text, NULL on success
  created_at TEXT NOT NULL
);
```

**`nightly_backup(conn, settings, now, force=False)`** is idempotent per IST day:
1. Unless `force`: if today's `backups` row exists and was **ok** (below), return its result with `skipped=True` and do no work. A row from a failed attempt is redone in full; the day's archive file is overwritten.
2. Write the archive and apply local retention. A failure here raises `BackupFailed`; nothing is recorded.
3. Upsert the `backups` row for the IST day.
4. If `BACKUP_S3_*` and `BACKUP_KEY` are all set: encrypt and PUT the daily key (and the weekly one on Sunday). Then set `uploaded_at`, or `upload_error`.
   - Off-site settings present but `BACKUP_KEY` missing: `upload_error = "BACKUP_KEY is not set, so nothing was uploaded"`. Plaintext never leaves the host.
   - No off-site settings at all (none of the five `BACKUP_S3_*` set): `upload_error = "Off-site backup isn't configured"`. This is a notice, not a failure.
5. Return `BackupResult(path, ok, uploaded, error, skipped)`. **`ok`** = the archive was written **and** either the upload succeeded or no off-site settings exist at all. A failed or refused upload is `ok=False` but doesn't raise.

**When it runs:**
- `tick` (pipeline spec §4.8) calls `nightly_backup(conn, settings, now)` after **every** scheduled-run attempt, **even if the run failed**. Idempotency makes a retried attempt cheap: a day that already has an ok backup isn't backed up twice.
- `jobseeker backup` stays as the manual command: it calls `nightly_backup(..., force=True)` and prints the result.

**Admin page:** a "Backups" card on `/admin` (auth spec) shows the last 7 `backups` rows: day, size, "Uploaded" or the error. Nothing else is added to `/admin`.

**Restore:** `jobseeker restore <path> [--to DIR]`.
- `<path>` is a local `.tar.gz`, or a `.tar.gz.enc` downloaded from B2 (decrypted with `BACKUP_KEY`).
- `--to` defaults to `./restore-<date>`, which must be empty or absent.
- It unpacks only the allowed member paths, refusing absolute paths and `..`.
- It checks every `MANIFEST.json` sha256, runs `PRAGMA integrity_check`, and prints the manifest's row counts next to the restored DB's.
- It never touches the live `JOBSEEKER_HOME`. The operator stops the services and swaps directories (hosting spec, Errors table).

### 3. Health

**`GET /healthz` and `HEAD /healthz`** live in `web/health.py`. They're public and in the auth allow-list:
- open the DB **read-only** (`sqlite3.connect(f"file:{db}?mode=ro", uri=True)`, 2-second timeout), never through `get_conn`, so the check can't migrate or write;
- run `SELECT 1` and read `PRAGMA user_version`;
- return `200 {"ok": true}`;
- on a DB error, return `503 {"ok": false, "check": "db"}`;
- if `user_version != LATEST`, return `503 {"ok": false, "check": "schema"}`;
- `HEAD` returns the same status with no body;
- `Cache-Control: no-store`; no counts, users, versions or timings are exposed.

**Dead-man's switch:** the ping is sent by `tick` (pipeline spec §4.8). With `HEALTHCHECK_PING_URL` set, after a scheduled-run attempt and its `nightly_backup` call, it sends one request with a 5-second timeout; a failure is only logged:
- `GET <url>` when the run finished without aborting **and** `nightly_backup` returned `ok=True`;
- `GET <url>/fail` when the run aborted, `nightly_backup` raised, or it returned `ok=False` (for example a failed B2 upload). The owner gets an email right away instead of after the 26-hour grace;
- Fetch-now and CLI runs never ping.

### 4. Public landing page

**`GET /`, signed out:**
- renders `landing.html`; signed in, it renders the Jobs inbox as today;
- the branch is inside the route handler, and every other route stays guarded;
- the landing is in the public allow-list only as "`/` without a session".

**Layout:**
- `base.html` with the nav hidden (`{% block nav %}{% endblock %}`), the `ui.css` tokens, one centred card, phone-first;
- `<meta name="robots" content="noindex">`;
- no app data, no counts, no user names except the owner's first name below.

**Copy:**
- **Headline:** "Your daily shortlist of product and analytics roles in India."
- **Three lines:**
  - "Every morning it searches LinkedIn, Naukri, Indeed and company career pages for your roles and cities."
  - "Each job is scored against your resume, with the reasons, so you read 10 jobs, not 600."
  - "Built for your phone: add it to your Home Screen."
- **Button:** "Continue with Google" → `/login`. It follows Google's sign-in branding: the official "G" mark as an inline SVG and the exact wording "Continue with Google".
- **Note:** "Invite-only. If you haven't been invited, ask <owner first name>." The name is the first word of `users.name` for `id = 1`; without one, it reads "ask the person who shared this link".
- **Privacy line:** "Your resume, preferences and applications are visible only to you. Download or delete them any time in Settings."
- **Footer:** "A personal project, not affiliated with LinkedIn, Naukri, Indeed or Google."

The auth spec's "not invited" 403 page reuses `landing.html`, with the invite note in place of the button.

## Errors

| Situation | Behaviour |
|---|---|
| VAPID keys missing | the Settings card says alerts aren't set up; `notify_new_matches` and `/push/test` are no-ops (test returns 409 with that text) |
| Malformed subscription | `/push/subscribe` returns 422; nothing is stored |
| Push service 404/410 | the subscription is deleted silently |
| Push service other error ×5 | the subscription is deleted; each failure adds "Couldn't send the match alert" to the run notes |
| `BACKUP_DIR` not writable, disk full, snapshot fails | `BackupFailed`; `tick` logs it, pings `/fail`, and the next tick that day retries (no `backups` row was written) |
| B2 PUT fails after retries | the local archive is kept; `upload_error` is set and shown on `/admin`; `/fail` ping |
| `BACKUP_KEY` missing or wrong length | no upload ever; an explicit `upload_error` |
| Restore: wrong key or corrupted `.enc` | "Couldn't decrypt: wrong BACKUP_KEY or damaged file"; nothing written |
| Restore: target not empty, bad member path, sha mismatch, integrity failure | refused with the reason; a partial target directory is removed |
| `/healthz` DB locked over 2 s | 503 `db`; the next check usually passes, and UptimeRobot alerts only on a sustained failure |

## Testing

All tests are offline (`pytest-socket`). HTTP goes through `respx`.

- **Push** (`tests/test_push.py`):
  - subscribe/unsubscribe/test need a session (401/redirect without one) and fail the Origin check from a foreign origin;
  - a duplicate endpoint is upserted and moves to the new user;
  - malformed keys give 422;
  - unsubscribing another user's endpoint is a no-op;
  - `/sw.js` is served at the root with `no-cache` and needs no session;
  - **encryption round-trip:** generate a subscriber key pair in the test, encrypt with the production function, decrypt with `http_ece.decrypt(…, private_key=subscriber, auth_secret=auth, version="aes128gcm")` → the original JSON;
  - the VAPID header parses: a JWT with `aud` = the endpoint origin and `sub` = `VAPID_SUBJECT`, which verifies against `VAPID_PUBLIC_KEY`;
  - `notify_new_matches` (with `seeded_two`):
    - sends only when N > 0, the toggle is on and `notified_on` isn't today;
    - a second call the same IST day sends nothing;
    - just after 00:00 IST counts as a new day (a fixed `now` in UTC);
  - the payload never contains a job title, company or location;
  - 410 deletes the row; 5 failures delete it; when all sends fail, `notified_on` stays unset and the run note is added;
  - an exception inside sending doesn't propagate to `run_all`.
  - the onboarding spec's table-walk delete test covers `push_subscriptions`, and the export zip contains no endpoint or key.
- **Backups** (`tests/test_backup.py`):
  - the archive members are exactly the DB, `data/users/**`, `config/app.yaml` and `MANIFEST.json`, and **never `.env`**, even when `.env` and `secrets/` exist in `JOBSEEKER_HOME`;
  - the manifest sha256s match;
  - local retention keeps 7 daily + 4 Sunday archives across 40 simulated days and leaves old-format Mac files untouched;
  - encrypt/decrypt round-trip; a wrong key or a flipped byte fails cleanly;
  - **SigV4** reproduces the canonical request, string-to-sign and signature of a fixed vector. Use AWS's documented S3 `PUT` example (`examplebucket`, `test$file.text`, the AWS example key pair); if it can't be reached offline, check in a vector computed once with `botocore` and record that in the test file;
  - respx-mocked PUT: the `Authorization` scope is `<date>/<region>/s3/aws4_request`, `x-amz-content-sha256` equals the body hash, and it goes to the daily key, plus the weekly key on Sunday IST;
  - upload refused without `BACKUP_KEY`; failed PUT (500 ×3) → local archive kept and `upload_error` set;
  - idempotency: a second `nightly_backup` the same IST day after an ok one returns `skipped=True` without writing; after a failed one it redoes the work; `force=True` always redoes it;
  - `ok` semantics: upload success → ok; no off-site settings → ok with the notice; `BACKUP_KEY` missing or a failed PUT → `ok=False`, no exception;
  - **restore drill:** back up `seeded_two`, restore to a temp dir, and both users' rows, the resume files and the manifest counts match; refuses a non-empty target and a `../` member.
- **Health** (`tests/test_health.py`):
  - 200 with no session;
  - 503 `schema` when `user_version` is changed;
  - 503 `db` when the file is missing;
  - HEAD returns the same status and no body;
  - the handler never calls `get_conn`, checked with a monkeypatched `get_conn` that raises;
  - the `tick` call and the ping itself are tested in the pipeline spec (§7, "Calls into sub-project 6"); this spec tests `BackupResult.ok`, which drives the ping;
- **Landing** (`tests/test_landing.py`):
  - anonymous `/` shows the headline, the Google button linking to `/login`, `noindex`, the owner's first name, and no job or application text from `seeded_two`;
  - signed-in `/` shows the inbox;
  - the auth spec's route-walk guard test passes with the new public entries (`/`-anonymous, `/sw.js`, `/healthz`).
- **CLI:** `vapid-keys` prints a pair that round-trips through `py_vapid`; `gen-key` prints 32 bytes of base64.

## Acceptance criteria

1. On the owner's iPhone (Home Screen app, iOS ≥ 16.4): Turn on alerts → permission prompt → "On for this device"; **Send a test** shows a notification; tapping it opens `/settings` in the app.
2. After a scheduled run that creates ≥ 1 `apply` match for a user with alerts on, that user gets exactly one "N new matches" notification that day. Tapping it opens Jobs filtered to Apply. The lock screen shows no job details.
3. Turning alerts off, or the user removing the app, stops notifications. A removed app's subscription is deleted after the push service returns 410.
4. Every day after the scheduled run, `BACKUP_DIR` has that day's archive and B2 has `daily/jobseeker-<date>.tar.gz.enc`, plus `weekly/…` on Sundays. After 9 days, B2 shows no `daily/` object older than 8 days.
5. A restore drill from a B2-downloaded `.enc` on the VM passes `integrity_check` and matches the manifest counts.
6. UptimeRobot shows `/healthz` up. Stopping `jobseeker-web` triggers its alert within 10 minutes. Healthchecks.io receives the daily ping, and a forced upload failure produces an immediate `/fail` alert.
7. A signed-out visitor at `https://<sub>.duckdns.org/` sees the landing page and no data; an uninvited Google account gets the invite note; signed-in users see Jobs as before.
8. No new dependency beyond `py-vapid` and `http-ece`. `uv sync --frozen` on the aarch64 VM builds nothing except the pure-Python `http-ece` sdist.
