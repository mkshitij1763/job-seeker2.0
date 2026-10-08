# Proposal: sub-project 5, per-user outreach (Gmail and contacts) (draft, pre-spec)

**Date:** 2026-10-08 · **Branch:** `multi-user` · **Builds on:** the audit, plus the auth, onboarding, pipeline and extras proposals.
**Rulings applied:**
- **Q2 = C** (the user's decision): roommates get matching only at launch, and the admin switches outreach on per user.
- **Q1:** company, domain and people/email lookups are a shared cache; outreach state is per-user; one user's blocklist never hides people from another.
- Equal per-user shares under the global caps, with no pooling.

---

## (a) Per-user Gmail OAuth (Web client, separate from sign-in)

- **Client:** the same Google **Web** OAuth client as sign-in (auth proposal §a), with a second registered redirect URI, `BASE_URL/gmail/callback`. Today's Desktop client and `InstalledAppFlow` loopback flow (`src/jobseeker/gmail/client.py:19-25`) are retired, and so is `jobseeker auth-gmail` (`src/jobseeker/cli.py:134-141`).
- **Consent:** `GET /gmail/connect` (behind `require_outreach`, see b) redirects to Google with:
  - `scope = openid email https://www.googleapis.com/auth/gmail.compose`, where `openid email` is only there so we know *which* account the drafts go to;
  - `access_type=offline` and `prompt=consent`, so Google always returns a refresh token;
  - `login_hint=<user email>`, plus state and PKCE, as in sign-in.

  `GET /gmail/callback` checks state, exchanges the code with `httpx`, verifies the ID token, and stores the token.

  This is a separate grant from sign-in: losing Gmail never signs anyone out, and sign-in never asks for Gmail.
- **Storage (migration v4):**
  ```
  gmail_tokens(user_id PRIMARY KEY REFERENCES users, account_email TEXT NOT NULL, token_enc BLOB NOT NULL,
               status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'expired')), connected_at, refreshed_at)
  ```
  `token_enc` is `Credentials.to_json()` encrypted with AES-256-GCM under `TOKEN_KEY` from `.env`. That's a separate key from `BACKUP_KEY`, so a leaked backup plus the backup key still doesn't expose tokens. The AAD is `user:<id>`, so a ciphertext copied to another user's row fails to decrypt.
- **`load_service(conn, user_id)`** replaces `load_service(token_path)` (`gmail/client.py:28-46`). It decrypts, refreshes if needed, re-encrypts, and writes back (today's write-back at `:43`, now per user).
  - On `RefreshError` (`invalid_grant`): set `status='expired'` and raise `GmailUnavailable(reconnect=True)`.
  - The Approve, #3 and follow-up routes then redirect with the error "Gmail needs reconnecting" and a **one-tap "Reconnect Gmail"** button (`/gmail/connect?next=/applications/<id>`). After consent the user lands back on the same job.
  - Settings shows the status: "Drafts go to x@gmail.com · Connected 3 days ago · Reconnect".
- **`gmail_factory`** (`src/jobseeker/web/app.py:59`) becomes `gmail_factory(conn, user_id)`. Its 4 call sites (`src/jobseeker/web/application.py:169, 208`; `src/jobseeker/web/contacts.py:136, 170`) pass `user.id`. The resume attachment (`web/application.py:195`) uses `data/users/<id>/resume.pdf` (onboarding proposal §c).
- **Testing mode:**
  - the app stays unverified, at ≤ 100 test users;
  - each outreach user's Gmail address must be added as a test user in Google Cloud before they connect, otherwise Google shows "access blocked";
  - refresh tokens expire after about 7 days, hence the one-tap reconnect;
  - users see Google's "unverified app" screen once per consent. The Connect card says so in advance: "Google will warn that this app isn't verified. It's Kshitij's personal app; continue."
- **Owner at migration:** the old `secrets/token.json` belongs to the Desktop client and can't be refreshed by the Web client, so it is **not migrated**. `secrets/` is not copied to the server. The owner taps "Connect Gmail" once after cutover. Existing `gmail_draft_id`s stay valid, because they live in the same Gmail account.
- **Turning outreach off for a user** deletes their `gmail_tokens` row (least privilege). Their drafts and outreach history stay.

## (b) The `outreach_enabled` gate

- `users.outreach_enabled INTEGER NOT NULL DEFAULT 0` (migration v4; the owner is set to 1).
- `require_outreach = Depends(current_user)` plus the flag, **else 404**, so the routes stay invisible.
- **Gated routes:**
  - `web/application.py`: `POST /{id}/draft` (`:108`), `POST /{id}/drafts/{kind}` (`:97`), `POST /{id}/approve` (`:128`), `POST /{id}/contact` (`:84`), `POST /{id}/followed-up` (`:220`);
  - **all** of `web/contacts.py`: `find` `:37`, `card` `:54`, `domain` `:64`, `remove` `:77`, `edit` `:105`, `3/email` `:122`, `followup` `:153`;
  - all of `/gmail/*`.

  These move to an `outreach` router, so the gate is one router-level dependency. Status, snooze, notes, undo and not-interested stay ungated.
- **UI for a matching-only user:**
  - **Job detail** (`src/jobseeker/web/templates/application.html`): no People or Drafts tabs, no Find contacts (`:50`), no Approve card (`:151-166`), no Regenerate (`:178`). The step path (`STEPS`, `src/jobseeker/web/view.py:13`) becomes `["Apply on the company site", "Mark applied"]`, with a primary "Open job posting ↗" (`apply_url`) and "Mark applied" (→ `applied_via_portal`). That transition is already allowed from every active status (`src/jobseeker/status.py:6, 24`).
  - **Today** (`today.html`): send, follow-ups, ready and find-contacts give way to "New strong matches" and "Applied, waiting to hear".
  - **Pipeline:** the `drafted`, `approved` and `sent` columns are hidden.
  - **Inbox and pipeline** never show "Find contacts →" or "Ready to approve". Those only appear for `drafted`, which a matching-only user can't reach, because the pipeline skips drafting for them (pipeline proposal §c).

  Templates read one flag, `user.outreach_enabled`.
- **/admin toggle:** `POST /admin/users/{id}/outreach` (admin, CSRF-checked). Switching on shows a checklist: "1. Add <email> as a test user in Google Cloud → OAuth consent screen. 2. Ask them to open Settings → Connect Gmail." Their `shortlisted` applications get drafts in the next run, within their draft share. Switching off deletes the token (a).
- **Gate test:** the route walk (auth proposal §d) asserts `require_outreach` on every route under the outreach router and `/gmail/*`. A behavioural test logs in as a matching-only user, POSTs or GETs each of them, and expects **404**. A render test checks that their detail, Today and Pipeline HTML contain none of `/contacts/find`, `/approve` or `Gmail`.

## (c) Shared contact cache vs per-user state

**Layers:**

| Shared cache (no user) | Per-user (through `applications.user_id` or `user_id`) |
|---|---|
| `company_domains` (domain, MX, pattern, catch-all) | `application_contacts` (who is #1-3, emailed_at, nudged_at, gmail_draft_id) |
| `contacts` rows with `owner_user_id IS NULL` (name, LinkedIn URL, work email, `email_status`) | `contact_candidates` (the ranked list for *this* job) |
| **new** `people_searches(company_norm, query, results TEXT, searched_at, PRIMARY KEY (company_norm, query))`: Tavily/Apify search results reused for 30 days | `blocklist` (`user_id`, migration v1) |
| | `contacts` rows with `owner_user_id = u` (people a user added or edited themselves) |

- **Search reuse:** `find_contacts` (`src/jobseeker/contacts/finder.py:44-49, 71-84`) checks `people_searches` before spending. A hit spends nothing. Ranking stays per job (`finder.py:90`, an LLM call over this job's JD), and it counts against the user's draft share (d).
- **`contacts.owner_user_id`** (nullable, migration v4). Shared-row dedup in `upsert_contact` (`src/jobseeker/db/contacts_repo.py:178-201`) and `save_contact` (`src/jobseeker/db/applications.py:131-156`) only ever matches `owner_user_id IS NULL`. Private rows are never adopted by anyone else.
- **Fixing the edit route** (`web/contacts.py:105-119`; today `:114` rewrites the shared row):
  - If **only** `email_status` changes to `bounced` and the email is unchanged, update the **shared** row. A bounce is a fact about the address and protects everyone. That's acceptable for 3 trusted users; the spec notes it.
  - Any other change (name, email, verified/unverified), or any change to a row this user already owns: **copy on write**. Insert `contacts(owner_user_id=u, source='manual', …)` (or update their own private row) and re-point **only this user's** `application_contacts` row (and `applications.contact_id` if it is #1).
  - "Add someone myself" (`POST /{id}/contact`, `save_contact`) always creates or updates a private row.
- **Per-user blocklist:**
  - `blocked_companies`, `blocked_profile_urls` and `blocked_names` (`applications.py:121-122`, `contacts_repo.py:156-175`) gain a `user_id` filter;
  - `upsert_contact`'s "blocked → return None" (`contacts_repo.py:186-187`) checks this user's blocklist only;
  - `save_contact`'s `BlockedContact` check (`applications.py:141-142`) does the same.
- **Not interested** (`mark_not_interested`, `applications.py:159-175`): it writes `blocklist(user_id=u, …)` rows for the linked contacts and, optionally, the company. The other users are unaffected: they still see that person in shared lookups, and the company still appears in their matches.

## (d) Per-user budgets inside the global free caps

- `Budget` (`src/jobseeker/db/usage.py:11-42`) becomes `Budget(conn, user_id, app_config, now)`. For each service (Tavily, Apify USD, Hunter and SMTP, plus the drafting units from the pipeline proposal), `can(svc, amount)` is true only if:
  - `used(u) + amount ≤ share(svc)`, **and**
  - `used(all) + amount ≤ global(svc)`.

  `spend` writes `usage(user_id, period, service)` (v1 key). The periods stay as today: monthly for Tavily, Apify and Hunter; daily (IST) for SMTP and drafts.
- **Shares** are split among **outreach-enabled** users only: `share = floor(global / outreach_users)`. Matching-only users don't hold a slice of quota they can't use. At launch the owner is the only outreach user and keeps 100% of today's limits (`src/jobseeker/config.py:106-111`: Tavily 950/month, Apify $4.50/month, Hunter 45/month, SMTP 60/day).
- **Mid-month changes:** when outreach is enabled for a second user mid-month, the shares are recomputed immediately. If the owner has already used more than the new share, they're simply out until the month resets. No pooling, as ruled.
- **The card summary** (`usage.py:38-42`, shown at `web/contacts.py:33`) reads "Your Tavily 120/475 · All 300/950 …". The admin usage table (already ruled) shows the same per user.
- **Drafting share:** the per-job drafts, the people ranking, and `pick_domain` (`finder.py:102`, which runs on the scoring model) all count as Groq units against this user's draft share and the global daily drafting cap. Facts extraction keeps its own small `groq:facts` counter (onboarding proposal §c).

## (e) SMTP verification behind a config flag

- `AppConfig.contacts.smtp_verify: "auto" | "on" | "off"` (default `auto`).
  - **`off`:** `find_contacts` skips step 3 entirely (`finder.py:117-152`). `catch_all` stays whatever is remembered (`known_catch_all`). The flow goes straight to the Apify profile email (step 4, `:154-171`), then the Hunter domain search (`:181-200`, whose `not hints` condition is unchanged), then the pattern guess (`:210-218`), which is saved as `unverified` and labelled "likely".
  - **`auto`:** once every 24 h, a 5-second TCP probe to port 25 of a well-known MX. The result is cached in an `app_state(key, value, checked_at)` row. If blocked, it behaves as `off`, so a find never burns the 15-second `smtplib` timeout (`src/jobseeker/contacts/smtp_verify.py:35, 44-45`) per company.
- Every use of the `SmtpVerifier` is kept, unchanged and tested, so moving to a host with port 25 open needs only a config change. `MAIL FROM` uses the outreach user's own email (`finder.py:123`), not the owner's.
- **Notes** reworded: "Email checks aren't available on this server; emails are best guesses unless Apify or Hunter found them." This replaces "try again from office Wi-Fi" (`finder.py:143`) and "the Mac may have slept" (`contacts_repo.py:37`).
- The spike measures the rest. With port 25 open, datacenter IPs without reverse DNS still get more `VerifyUnavailable` refusals. Those already degrade to "likely" (`finder.py:146-150`).

## (f) Migrating the owner's outreach data, and tests

**Migration v4** (after v1-v3; current counts: contacts 16 (15 finder, 1 manual), application_contacts 12, contact_candidates 19, drafts 135, blocklist 0, company_domains 4):
- `users.outreach_enabled = 1` for user 1.
- `contacts`: rows with `source = 'manual'` (created by "Add someone myself" or the edit route) get `owner_user_id = 1`. Rows with `source = 'finder'` stay shared. The spec's dry run lists both groups, so the owner can check them.
- `application_contacts`, `contact_candidates`, `drafts` and `events` need no change: they're already scoped through the owner's applications (v1).
- `company_domains` stays shared. `people_searches`, `gmail_tokens` and `app_state` are created empty. There's no token import (a). Checks: `foreign_key_check`, unchanged row counts, and every application contact still resolves to a contact.

**Tests:**
- **Gmail:**
  - the connect redirect carries `gmail.compose`, `access_type=offline`, `prompt=consent` and `login_hint`;
  - the callback stores an encrypted token that is unreadable with a different user's AAD;
  - refresh writes back, re-encrypted;
  - `invalid_grant` → `status='expired'` and the error carries the Reconnect link with `next`;
  - the token is deleted when outreach is turned off;
  - sign-in never requests the Gmail scope (respx plus a stubbed verifier).
- **Gate:** the route walk asserts `require_outreach`; a matching-only user gets 404 on every outreach route; the rendered HTML has no outreach UI; the matching path "Mark applied" works from `shortlisted`; the admin toggle requires admin and CSRF.
- **Cache vs per-user:**
  - a second user's find reuses `people_searches` and spends no Tavily;
  - a name or email edit makes a private copy and the other user still sees the original;
  - a bounce-only edit updates the shared row;
  - B's not-interested hides the person from B but not from A;
  - private rows are never adopted by `upsert_contact` for another user.
- **Budgets:** a user's share stops them while the other continues; the global cap stops both; shares recompute when outreach is enabled; matching-only users don't dilute the shares; ranking and `pick_domain` count against the draft share.
- **SMTP flag:** `off` never constructs `SmtpVerifier` (the factory fails the test if called) and still returns Apify, Hunter or pattern results; `auto` with a blocked probe behaves as `off` and caches the result for 24 h; `on` keeps today's behaviour (the existing `tests/test_contacts_smtp.py` and `tests/test_contacts_finder.py` pass unchanged under `on`).
- **Migration v4:** manual vs finder contacts are split as described; the counts hold; the owner's existing People cards and drafts render the same before and after.

## Open points for the coordinator
1. The bounce-only edit updating the shared row: OK for 3 trusted users, or should every edit be private? I propose shared for bounces only.
2. Should `people_searches` reuse be 30 days, or shorter for small startups where people change often? I propose 30.
3. When outreach is turned on for a roommate, do they get drafts for their existing shortlist? I propose yes, within their draft share, in the next run.
