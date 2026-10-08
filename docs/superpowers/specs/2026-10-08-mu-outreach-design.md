# job-seeker2.0 multi-user: per-user outreach (Gmail and contacts) (design)

**Date:** 2026-10-08
**Status:** The combined multi-user design was approved by the user on 2026-10-08. This is the written spec for sub-project 5, awaiting review.
**Depends on:**
- sub-project 2 (`…-mu-accounts-auth-design.md`): users, guards, the route walk, `user_id` scoping, `Budget(conn, user_id, limits, now)`, migrate;
- sub-project 3 (`…-mu-onboarding-settings-design.md`): `AppConfig`, `current_prefs`, Settings, per-user resume, and the export/delete lists;
- sub-project 4 (`…-mu-per-user-pipeline-design.md`): drafting round-robin and `drafts_enabled(user)`, which this spec replaces with `users.outreach_enabled`.

**Hosting interface (sub-project 1):**
- the Google Web client's second redirect URI, `BASE_URL/gmail/callback`;
- `TOKEN_KEY` in the server `.env`;
- the server's `config/app.yaml` sets `contacts.smtp_verify: off`.

Research: `docs/superpowers/research/2026-10-08-outreach-proposal.md`.

## 1. Goal

Keep the owner's full outreach flow (Find contacts, AI drafts, Approve → Gmail drafts, follow-ups, Email #3) working in the hosted, multi-user app, with **each user's own Gmail**. Make outreach a **per-user switch** that is off for roommates at launch (the user's **option C**). Share the expensive company and people lookups between users, while keeping who-was-emailed, edits and "not interested" **private to each user**.

## 2. Non-goals

- Sending email, or reading Gmail (the scope stays `gmail.compose`; "Mark replied" stays manual).
- Google app verification or the CASA audit: the app stays in **Testing** mode.
- Changing the contact-finding algorithm itself (contact-finder spec): only caching, scoping, budgets and the SMTP switch change.
- Outreach for roommates at launch: the code supports it; the admin turns it on later.
- Pooling unused budget.

## 3. Decisions (brainstorming and coordinator rulings)

| Topic | Decision |
|---|---|
| Gmail consent | A separate grant from sign-in, on the same Google **Web** client. Scopes `openid email gmail.compose`; `access_type=offline`, `prompt=consent`, `login_hint`; state + PKCE |
| Token storage | `gmail_tokens`: AES-256-GCM under `TOKEN_KEY` (not `BACKUP_KEY`), AAD `user:<id>` |
| Expiry | Testing-mode refresh tokens expire after about 7 days; a one-tap **Reconnect Gmail** that returns to the same job |
| Owner at cutover | The Desktop-client `token.json` is **not** migrated; the owner taps Connect Gmail once |
| Gate | `users.outreach_enabled` (the owner 1, everyone else 0). A single outreach router behind `require_outreach`, **404** when off. The admin toggle in `/admin` |
| Contacts | A shared cache (`company_domains`, `contacts` with `owner_user_id IS NULL`, `people_searches`) vs per-user state (`application_contacts`, `contact_candidates`, `blocklist`, private contacts) |
| Bounces | A bounce-only edit updates the **shared** row (ruled yes) |
| Search reuse | `people_searches` results reused for **30 days** (ruled yes) |
| Budgets | Tavily, Apify, Hunter, SMTP and drafts: per-user share = `floor(global / outreach-enabled users)`, plus the global cap |
| SMTP | `contacts.smtp_verify: off \| on \| auto`, **default `off`** (Oracle blocks port 25); `auto` stays available |
| Enabling outreach for a user | Their existing shortlist gets drafts within their draft share, best first (ruled yes) |

## 4. Design

### 4.1 Gmail connect, tokens and reconnect (`src/jobseeker/gmail/`)

- **`GET /gmail/connect?next=<path>`** (`require_outreach`): the same oauth-cookie mechanism as sign-in (sub-project 2 §4.2), with a different cookie name, `__Host-js_gmail_oauth`. It redirects to Google's auth endpoint with:
  - `redirect_uri=BASE_URL/gmail/callback`;
  - `scope=openid email https://www.googleapis.com/auth/gmail.compose`;
  - `access_type=offline`, `prompt=consent`, `include_granted_scopes=false`;
  - `login_hint=<users.email>`, state, nonce and S256 PKCE.
- **`GET /gmail/callback`:**
  1. Check state; exchange the code (`httpx`); verify the ID token (aud, nonce).
  2. Require that a `refresh_token` is present; otherwise show "Google didn't grant offline access. Try again".
  3. Build `google.oauth2.credentials.Credentials(token, refresh_token, token_uri, client_id, client_secret, scopes)`.
  4. Upsert `gmail_tokens(user_id, account_email=claims.email, token_enc, status='ok', connected_at, refreshed_at)`.
  5. Redirect to `next` (a local path) with "Gmail connected: drafts go to <email>".
- **Encryption** (`src/jobseeker/crypto.py`): `seal(plaintext, aad) -> nonce‖ciphertext‖tag`, using `cryptography`'s `AESGCM` with a 12-byte random nonce, and `open_(blob, aad)`. The key is `base64-decode(TOKEN_KEY)`, which must be 32 bytes, or startup is refused. The AAD is `b"user:%d" % user_id`.
- **`load_service(conn, user_id)`** replaces `load_service(token_path)` (`src/jobseeker/gmail/client.py:28-46`):
  - no row, or `status='expired'` → `GmailUnavailable(reconnect=True)`;
  - decrypt and build `Credentials.from_authorized_user_info(json, SCOPES)`;
  - refresh if it isn't valid, then **re-encrypt and write back** with a new `refreshed_at`;
  - a refresh failing with `invalid_grant` → `status='expired'`, `GmailUnavailable(reconnect=True)`;
  - a transport error → `GmailUnavailable(reconnect=False)`, with today's wording.

  `create_draft` (`client.py:49-58`) is unchanged, except that a 401/403 also marks the token `expired`.
- **Removed:** `authorize` (`client.py:19-25`), the `InstalledAppFlow` import, `jobseeker auth-gmail` (`src/jobseeker/cli.py:134-141`), and the `secrets/` paths in `Settings` (`src/jobseeker/config.py:68-70`).
- **`gmail_factory(conn, user_id)`** (`src/jobseeker/web/app.py:59`). The call sites pass `user.id`: `web/application.py:169, 208` and `web/contacts.py:136, 170`.
- **Attachment:** `_raw_for` (`web/application.py:190-196`) attaches `data/users/<id>/resume.pdf` and builds the signature (`src/jobseeker/outreach/drafter.py:37`) from `current_prefs`.
- **Reconnect UX:** when an approve, Email #3 or follow-up route gets `GmailUnavailable(reconnect=True)`, it redirects back with `err="Gmail needs reconnecting"`, and the flash area renders a **Reconnect Gmail** button linking to `/gmail/connect?next=/applications/<id>`. After consent the user is back on the job and taps Approve again. Drafts already created in that request are kept and named, as today (`web/application.py:179-186`).
- **Settings → Account** gains a Gmail card (only when outreach is on):
  - "Drafts go to x@gmail.com · connected 3 days ago · Reconnect", or "Not connected · Connect Gmail";
  - a note before the first connect: "Google will warn that this app isn't verified. It's Kshitij's personal app: tap Advanced → Continue."
- **Testing mode:** ≤ 100 test users. Each outreach user's Gmail address must be added as a test user in Google Cloud → OAuth consent screen before connecting, otherwise Google answers "access blocked". The admin toggle shows this as a checklist (§4.2).

### 4.2 The `outreach_enabled` gate

- **`require_outreach`** = `current_user` + `require_onboarded` + `user.outreach_enabled`, **else 404**.
- **The outreach router** (`src/jobseeker/web/outreach.py`, prefix `/applications`, `dependencies=[Depends(owned_app), Depends(require_outreach)]`) receives these routes, moved unchanged in behaviour:
  - from `web/application.py`: `POST /{id}/draft` (`:108`), `POST /{id}/drafts/{kind}` (`:97`), `POST /{id}/approve` (`:128`), `POST /{id}/contact` (`:84`), `POST /{id}/followed-up` (`:220`);
  - **all** of `web/contacts.py`: `find` `:37`, `card` `:54`, `domain` `:64`, `remove` `:77`, `edit` `:105`, `3/email` `:122`, `followup` `:153`.

  `/gmail/*` uses `require_outreach` too. **Ungated:** detail, status, snooze, notes, undo and not-interested.
- **Templates** read `user.outreach_enabled`. When it's off:
  - `application.html`: no People and Drafts tabs, no Find contacts (`:50`), no Approve card (`:151-166`), no Regenerate (`:178`), no "Mark followed up" (`:177`). The step path (`STEPS`, `src/jobseeker/web/view.py:13`) becomes `["Apply on the company site", "Mark applied"]`, with **Open job posting ↗** (`apply_url`) and **Mark applied** (→ `applied_via_portal`, already allowed from every active status, `src/jobseeker/status.py:6, 24`).
  - `today.html`: sections "New strong matches" (apply-band applications in `new` or `shortlisted`) and "Applied, waiting to hear" (`applied_via_portal`), in place of send, follow-ups, ready and find contacts.
  - `pipeline.html`: the `drafted`, `approved` and `sent` columns are hidden.
  - `inbox.html` and `pipeline.html`: the "Find contacts →" and "Ready to approve" labels never render (`drafted` is unreachable, because drafting skips the user).
- **Drafting eligibility:** sub-project 4's `drafts_enabled(user)` becomes `user.outreach_enabled`.
- **Admin toggle:** `POST /admin/users/{id}/outreach` (`require_admin`, Origin-checked), with `enabled=1|0`. The users list shows "Outreach: on/off".
  - **Turning it on** shows a checklist: "1. Add <email> as a test user in Google Cloud → OAuth consent screen. 2. Ask them to open Settings → Connect Gmail." From the next run, their existing `shortlisted` applications are drafted within their draft share, by `_apps_needing_drafts` order: **best latest score first, ties broken by `user_jobs.prescore`**.
  - **Turning it off** deletes their `gmail_tokens` row. Their drafts and history stay, and are hidden by the gate.

### 4.3 The shared contact cache and per-user state

| Shared (no user) | Per-user |
|---|---|
| `company_domains` (domain, MX, pattern, catch-all) | `application_contacts`, `contact_candidates` (through `applications.user_id`) |
| `contacts` with `owner_user_id IS NULL` | `contacts` with `owner_user_id = u` (added or edited by that user) |
| `people_searches` (search results, 30 days) | `blocklist` (`user_id`, sub-project 2) |

- **`people_searches(company_norm, query, provider, results, searched_at, PRIMARY KEY (company_norm, query, provider))`.** `_search` (`src/jobseeker/contacts/finder.py:44-49`) and the Apify people search (`:71-84`) first look up `(normalize_company(company), query, provider)` with `searched_at ≥ now − 30 days`. A hit spends **no budget**. A miss checks the budget, calls the provider, then upserts the results.
  - Ranking stays per job: an LLM call over this job's JD (`finder.py:90`).
  - Apify profile emails (`:154-171`) and Hunter domain searches (`:181-200`) aren't cached in this table. Their results already land in the shared `contacts` and `company_domains` rows.
- **Dedup and adoption:** `upsert_contact` (`src/jobseeker/db/contacts_repo.py:178-201`) and `save_contact` (`src/jobseeker/db/applications.py:131-156`) only ever match rows with `owner_user_id IS NULL`. A private row is never adopted by any user.
- **Not-interested and blocklist checks** use the acting user's `user_id`: `blocked_profile_urls`, `blocked_names`, the block check in `upsert_contact` (`contacts_repo.py:186-187`), `save_contact`'s `BlockedContact` (`applications.py:141-142`), and `mark_not_interested` (`applications.py:159-175`). User B's "not interested" never hides a person from user A, and never stops A's matches at that company.
- **Edit route** (`POST /{id}/contacts/{rank}/edit`, today `web/contacts.py:105-119`, which overwrote the shared row at `:114`):
  1. Load this user's `application_contacts` row and its contact.
  2. **Bounce only** (the form's name and email equal the stored ones, and `email_status` changes to `bounced`) on a shared row: `UPDATE contacts SET email_status='bounced'` on the **shared** row. A bounce is a fact about the address and protects everyone.
  3. **Any other change** to a shared row: **copy on write**. Insert `contacts(company, name, role, linkedin_url, email, email_status, source='manual', owner_user_id=u)`, re-point **only this** `application_contacts` row (and `applications.contact_id` if rank 1), and set `email_source='manual'`.
  4. A row already owned by this user is updated in place.
- **"Add someone myself"** (`POST /{id}/contact`, `save_contact`) always writes a private row (`owner_user_id=u`).
- **Remove and replace** (`web/contacts.py:77-102`) and the finder's linking (`finder.py:219-225`) are unchanged, apart from the user-scoped block checks.

### 4.4 Per-user budgets inside the global free caps

- **Limits** built per request or run for user `u` (sub-project 2's `Budget`):
  ```
  n = max(1, COUNT(users WHERE outreach_enabled AND disabled_at IS NULL))
  tavily: Limit("month", cfg.contacts.tavily_monthly_limit,       floor(global / n))
  apify:  Limit("month", cfg.contacts.apify_monthly_usd_limit,    round(global / n, 2))
  hunter: Limit("month", cfg.contacts.hunter_monthly_limit,       floor(global / n))
  smtp:   Limit("day",   cfg.contacts.smtp_daily_limit,           floor(global / n))
  draft:  Limit("day",   cfg.budgets.global_drafts_per_day,       floor(global / n))   # replaces sub-project 4's draft share
  ```
  Months and days are IST (`src/jobseeker/clock.py`, sub-project 4).
- **Draft units:** draft generation (`draft_application`), people ranking (`finder.py:90`) and `pick_domain` (`finder.py:102`) each spend 1 `draft` unit.
- **Changing the number of outreach users** changes the shares immediately. A user already above their new share is simply out until the period resets (no pooling).
- **The card's usage line** (`src/jobseeker/db/usage.py:38-42`, shown at `web/contacts.py:33`) becomes "Your Tavily 120/475 · All 300/950 · Apify $0.40/$2.25 · …". The `/admin` usage table already shows every user (sub-project 2).
- **Matching-only users hold no outreach share,** so at launch the owner keeps 100% of today's limits.

### 4.5 SMTP verification switch

- **`AppConfig.contacts.smtp_verify: Literal["off", "on", "auto"] = "off"`.**
  - **`off`:** `find_contacts` skips step 3 entirely (`finder.py:117-152`). `catch_all` stays whatever `known_catch_all` remembers. The flow goes straight to the Apify profile email (step 4), then the Hunter domain search (`:181-200`; `not hints` is unchanged), then the pattern guess (`:210-218`). The result is saved as `unverified` and shown as **likely**.
  - **`on`:** today's behaviour.
  - **`auto`:** before step 3, read `app_state['smtp25']`. If it's missing or older than 24 h, probe by opening a TCP connection to port 25 of `gmail-smtp-in.l.google.com` with a 5 s timeout, then store `open` or `blocked` with `checked_at`. `blocked` behaves as `off`, so a find never waits out `smtplib`'s 15 s timeout (`src/jobseeker/contacts/smtp_verify.py:35, 44-45`).
- **`SmtpVerifier`** (`smtp_verify.py`) is unchanged and stays tested. `MAIL FROM` is the acting user's `sender_email or email` (`finder.py:123`), which `effective_prefs` fills per user.
- **Note wording:**
  - when off or blocked: "Email checks aren't available on this server; emails are best guesses unless Apify or Hunter found them." (replaces `finder.py:143`);
  - the stale find message (`contacts_repo.py:37`) becomes "Finding contacts timed out. Try again."

### 4.6 Delete and export coverage (sub-project 3 §4.7)

- **Delete adds:** `gmail_tokens` (user), and `contacts WHERE owner_user_id = u` (after removing the user's `application_contacts`).
- **Shared rows stay:** `contacts` with no owner, `people_searches`, `company_domains`.
- **Export:** already lists linked people. It gains `gmail.json` (`account_email`, `connected_at`; **never the token**).

## 5. Data model (migration v5)

```sql
ALTER TABLE users ADD COLUMN outreach_enabled INTEGER NOT NULL DEFAULT 0;
UPDATE users SET outreach_enabled = 1 WHERE id = 1;
ALTER TABLE contacts ADD COLUMN owner_user_id INTEGER REFERENCES users(id);   -- NULL = shared cache row
UPDATE contacts SET owner_user_id = 1 WHERE source = 'manual';                -- live data: 1 manual, 15 finder
CREATE INDEX idx_contacts_owner ON contacts (owner_user_id);
CREATE TABLE people_searches (company_norm TEXT NOT NULL, query TEXT NOT NULL, provider TEXT NOT NULL,
  results TEXT NOT NULL, searched_at TEXT NOT NULL, PRIMARY KEY (company_norm, query, provider));
CREATE TABLE gmail_tokens (user_id INTEGER PRIMARY KEY REFERENCES users(id), account_email TEXT NOT NULL,
  token_enc BLOB NOT NULL, status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'expired')),
  connected_at TEXT NOT NULL, refreshed_at TEXT);
CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, checked_at TEXT NOT NULL);
```

- **Unchanged:** `application_contacts` (12 rows), `contact_candidates` (19), `drafts` (135), `events`, `company_domains` (4). They're already scoped through the owner's applications (v1) or shared.
- **Post-checks:**
  - `foreign_key_check` is clean;
  - every `application_contacts.contact_id` still resolves;
  - the owner's People cards render identically before and after on the fixture.
- **No token import.** `secrets/` isn't copied to the server (hosting runbook).

## 6. Errors

| Situation | Behaviour |
|---|---|
| `TOKEN_KEY` missing or not 32 bytes | Startup refused, naming the variable |
| Callback without a `refresh_token` | "Google didn't grant offline access. Try again" + Connect button |
| Gmail account not a test user | Google shows "access blocked"; Settings explains that the admin must add the address as a test user |
| Refresh `invalid_grant`, or a 401/403 from Gmail | `status='expired'`; the error flash with **Reconnect Gmail** returns to the same job; drafts already made are kept and named |
| Gmail unreachable | Today's message ("Couldn't reach Gmail…"); no status change |
| Outreach route as a matching-only user | 404 |
| A user's share used, or the global cap | That service is skipped with today's note style ("Your Tavily share is used for October" / "Shared Tavily budget used for October") |
| Port 25 blocked (`auto`) or `off` | Step 3 skipped with the server wording; emails are **likely** |
| Decrypt fails (key rotated, row tampered) | The token is treated as expired, so Reconnect; logged |

## 7. Testing

No network: Google endpoints use `respx`, `verify_oauth2_token` is stubbed, the Gmail service is a fake (`tests/test_web_application.py` pattern), and Tavily, Apify and Hunter are faked.

- **Gmail:**
  - the connect redirect has the exact scopes, `access_type=offline`, `prompt=consent`, `login_hint` and S256 PKCE;
  - the callback stores `token_enc`, which `open_` can decrypt only with the same user's AAD (a swapped row fails);
  - a missing `refresh_token` is refused;
  - a refresh writes back a new ciphertext and `refreshed_at`;
  - `invalid_grant` → `expired`, and the approve redirect carries the Reconnect link with the right `next`;
  - a 401 from `create_draft` marks it expired;
  - turning outreach off deletes the token;
  - sign-in (sub-project 2) never requests `gmail.compose`;
  - `auth-gmail` no longer exists.
- **Gate:**
  - the route walk asserts `require_outreach` on every route of the outreach router and `/gmail/*`;
  - a matching-only user gets **404** on each (GET and POST, ids from `seeded_two`);
  - the rendered detail, Today and Pipeline HTML for them contain none of `/contacts/find`, `/approve`, `Gmail` or `Find contacts`, and contain "Open job posting" and "Mark applied";
  - Mark applied works from `shortlisted`;
  - the admin toggle requires an admin plus the Origin check;
  - enabling outreach makes the next run draft the existing shortlist in score order, within the share.
- **Cache vs per-user:**
  - a second user's find for the same company and query within 30 days reuses `people_searches` and spends 0 Tavily; after 31 days it spends again;
  - a name or email edit creates a private row, and the other user still sees the original;
  - a bounce-only edit updates the shared row;
  - B's not-interested hides the person from B's future finds and blocks the company for B only; A is unaffected;
  - a private row is never adopted by `upsert_contact`/`save_contact` for another user.
- **Budgets:**
  - with 2 outreach users, each gets half of every service, and the global cap stops both;
  - enabling a third recomputes the shares mid-month;
  - matching-only users don't dilute the shares;
  - ranking and `pick_domain` spend `draft` units;
  - the usage line shows "Your … · All …".
- **SMTP switch:**
  - `off` never constructs `SmtpVerifier` (a factory that fails if called) and still returns Apify, Hunter or pattern results with the server wording;
  - `auto` with a refused probe stores `blocked` and behaves as `off` for 24 h, then re-probes;
  - `on` passes the existing `tests/test_contacts_smtp.py` and `tests/test_contacts_finder.py` unchanged.
- **Delete and export:** the sub-project 3 table-walk delete test covers `gmail_tokens` and private contacts; the export never contains `token_enc`.
- **Migration v5:**
  - on a fixture with 15 finder and 1 manual contact, the split is right, the owner has `outreach_enabled=1`, every link resolves, the People cards render the same, and a re-run is a no-op.

## 8. Acceptance criteria

1. After cutover, the owner taps Connect Gmail once. Approve then creates Gmail drafts with the resume attached, exactly as before.
2. When the token expires, Approve shows Reconnect Gmail. One tap and consent bring the owner back to the same job, and Approve works.
3. A roommate with outreach off never sees outreach UI and gets 404 from every outreach route. Their path is Open job posting → Mark applied.
4. Turning outreach on for a roommate (after adding them as a Google test user) lets them connect their own Gmail. Their existing shortlist gets drafts in the next run within their share. Their drafts go to **their** Gmail.
5. Contact searches for the same company within 30 days cost nothing the second time. An edit by one user never changes another user's view, except bounces. "Not interested" is private.
6. With `smtp_verify: off` on the server, Find contacts completes without waiting on port 25, and emails are labelled likely or verified (Apify/Hunter).
7. No user exceeds their outreach share, and the global free caps are never exceeded.
8. All tests pass, with no network.
