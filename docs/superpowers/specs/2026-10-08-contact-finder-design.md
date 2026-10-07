# job-seeker2.0: contact finder (top-3 people + verified work emails) (design)

**Date:** 2026-10-08
**Status:** Sections 1–4 approved in brainstorming. Awaiting the user's review of this written spec.
**Builds on:** the MVP, job-discovery and mobile-access specs (all dated 2026-10-07). Those specs still hold except where this one changes them.

## 1. Goal

From a job page, one tap on **Find contacts** finds the **3 most relevant people** at that company for that role, with a reason for each, and their **work email**. The email is verified wherever possible, **using only free services**.

The outreach pattern:
- emails to the top **2** now;
- an email to **#3** if no reply after 5 days;
- LinkedIn notes to **all 3** right away.

**Success criteria:**
1. Find contacts returns up to 3 people. Every one comes from a real search result: none are invented, and every one is linked to their LinkedIn profile.
2. Each person's email has a clear status: **verified**, **likely** or **not found**.
3. No paid usage, ever. Each service stops before its free limit and says so.
4. Approve drafts emails for #1 and #2. The follow-up badge later offers #3. Nothing is sent automatically: Gmail drafts only, as before.
5. The user's LinkedIn account is never touched by automation.

## 2. Decisions from brainstorming

| Topic | Decision |
|---|---|
| Approach | **Hybrid**: Tavily web search for public LinkedIn profiles, then Groq picks the top 3, then emails built from patterns and **verified over SMTP from the Mac**. Apify and Hunter free tiers are fallbacks only. |
| LinkedIn | No logged-in automation: LinkedIn's terms forbid it and accounts get restricted. Only public profile pages are used, found through Tavily. Apify actors run on Apify's servers without the user's account. |
| Budget | Free only. Tavily: 1,000 searches a month. Apify: $5 a month. Hunter: 50 credits a month. All three were validated on 2026-10-08 (Apify plan FREE, $5; Hunter Free, 50/50; Tavily returning results). |
| Timing | **On demand only**, from a **Find contacts** button. Nothing runs automatically in the daily run. |
| Outreach | Top 2 emailed at Approve. #3 suggested by the follow-up badge after 5 days with no reply. LinkedIn notes for all 3 at once. |
| Keys | `TAVILY_API_KEY` (required), `APIFY_API_TOKEN` and `HUNTER_API_KEY` (optional), all in the git-ignored `.env`. |

## 3. Design

### 3.1 Finding people

**Trigger:** `POST /applications/{id}/contacts/find` starts a background job (FastAPI `BackgroundTasks`) and redirects back. While `find_status = running`, the job page polls `GET /applications/{id}/contacts/status` every 3 s through HTMX and swaps in the People card when the job is done. The button appears on the job page; on phones it is under **More** too.

**Search:** two Tavily searches per job, with `include_domains: ["linkedin.com"]` and `max_results: 10`:
1. **Team:** `site:linkedin.com/in "<company>" <role words> <city>`. The role words come from the job title and role family, e.g. "product manager", "product analyst" or "founder's office".
2. **Recruiting:** `site:linkedin.com/in "<company>" (recruiter OR "talent acquisition")`.

**Parsing each result:**
- **Name:** the result title's text before the first " - ".
- **Headline:** the rest of the title.
- **Profile URL:** normalised to `https://www.linkedin.com/in/<slug>`.
- **Snippet:** kept as given.

A result is kept only if the company name (normalised as `normalize_company` does) appears in its headline or snippet. Duplicates are removed by profile URL.

**Ranking:** Groq (`models.drafting`) receives the job's title, company and the first 1,500 characters of the description, plus the numbered candidate list. It returns, under strict JSON, up to 3 picks, each with:
- `index` (int, from the list);
- `label`: `hiring_manager`, `team_lead`, `peer`, `recruiter` or `founder`;
- `reason`: one line.

Indices outside the list are dropped. **The model cannot add people.**

**Fallback:** if there are fewer than 3 candidates after filtering, and the Apify budget allows, the app runs harvestapi's no-login people-search actor (company + role words). Its results go through the same filter and ranking.

**Card controls:**
- **Remove** a person: the next-best ranked candidate takes their place (the full ranked list is kept).
- **Edit** a person's name or email.
- **Add someone myself**: the existing manual contact form.

### 3.2 Finding and verifying emails

1. **Company domain** (cached per company in `company_domains`):
   1. a company website URL among the job's source data (JobSpy `company_url_direct`) or in the description (`@domain` or `https://domain`);
   2. otherwise one Tavily search for `"<company>" official website`, taking the first result whose host is not a job board, LinkedIn or a social site.

   The domain must have MX records (looked up with `dnspython`).
2. **Pattern hints**, ordered:
   1. a pattern previously verified for this domain (`company_domains.pattern`);
   2. the pattern inferred from public addresses: one Tavily search for `"@<domain>"`, with addresses extracted from the snippets and matched to name-like local parts;
   3. a Hunter domain-search pattern, used only in the fallback (step 5).
3. **Candidates per person**, in this order: hinted patterns first, then `first.last`, `first`, `firstlast`, `flast`, `f.last`, `first_last`, `firstl`, `last.first`, without duplicates.

   **Name cleanup:**
   - drop anything after `,` or `|`;
   - drop text in brackets, emoji and titles (Dr., Mr., Ms., CA, PMP …);
   - simplify accents to ASCII;
   - first = first word, last = last word, with middle words ignored;
   - initials ("K. Meshram") allow only `{f}.{last}` and `{f}{last}`;
   - a single-word name allows only `{first}`.
4. **SMTP check** (`smtplib`, port 25, to the lowest-preference MX host):
   1. `EHLO` with the Mac's hostname, then `MAIL FROM:<user's gmail>`.
   2. **Catch-all probe:** `RCPT TO` a random 12-character address first. If that is accepted, the domain is catch-all and nothing can be verified.
   3. **Candidates:** `RCPT TO` each candidate in order, stopping at the first `250`/`251`.
   4. `QUIT`. **`DATA` is never sent, so no email ever goes out.**
   5. **Limits:** one connection per domain per run, a 2 s pause between `RCPT`s, at most 8 candidates per person, and at most `contacts.smtp_daily_limit` (default 60) `RCPT`s per day.
   6. **Answers:**
      - 250/251 on a domain that isn't catch-all: **verified**. The pattern is saved to `company_domains`.
      - 550/551/553: that candidate doesn't exist.
      - 4xx: **unknown** (greylisting).
      - A connect failure or timeout means port 25 is blocked on this network. It is recorded once per run, and verification is skipped.
5. **Fallbacks** for people still not verified, within budget:
   1. **Apify** profile-plus-email actor (harvestapi) for that profile URL. An email it returns that matches the domain is **verified** (its own verification).
   2. **Hunter** domain search, once per domain per month, to learn the pattern (`data.pattern`) and any listed address for that name.
6. **Result per person:**
   - **verified:** SMTP or the provider confirmed it.
   - **likely:** the best guess, from the learned pattern or else `first.last`.
   - **not found:** no domain, or no usable name.
   - Each email also records its `email_source`: `smtp`, `apify`, `hunter`, `pattern` or `manual`.

### 3.3 Outreach flow

**People card** (replaces the single contact card; "Add someone myself" stays). Each person shows:
- rank, name, label and reason;
- a LinkedIn link;
- their email and status;
- their wave: **email now** for #1–2, **follow-up** for #3;
- **Copy note**: the LinkedIn note with "Hi <first>, " in front, kept within 300 characters by trimming the note body if needed;
- **Open LinkedIn**, **Remove**, **Edit**.

**Approve:**
- creates one Gmail draft for **each** wave-1 person that has an email: **verified** goes through, **likely** needs a per-person confirmation, and **bounced** or **not found** is skipped with a message;
- every draft has the same body and subject, plus that person's greeting, the signature and the resume;
- it moves the application to `approved` if at least one draft was created;
- it stores each draft id on that person's link row.

**Gmail failure:** if Gmail is unavailable partway through, any drafts already created stay, and the message names them.

**Follow-up:**
- When an application has been `sent` for at least 5 days with no newer event and #3 hasn't been emailed, the pipeline badge reads **"Email #3: <first name> (<label>)"**.
- The job page shows **Draft email to #3**. It creates one Gmail draft with the same body, #3's greeting and the line "I also reached out to your colleague earlier." It records the action as follow-up 1, so the existing cap of 2 applies.
- If #3 has no usable email, the badge falls back to the existing follow-up.

**Stopping:**
- `replied`, `interview`, `offer` or `rejected` suppress wave 2.
- **Not interested** adds all linked people to the blocklist (plus the company if ticked).
- Blocked people are excluded from future searches at that company.

### 3.4 Data

- **`application_contacts`:** `id, application_id, contact_id, rank (1–3), label, reason, wave (1|2), email_source, gmail_draft_id NULL, emailed_at NULL, created_at`, with `UNIQUE (application_id, rank)`.
- **`contact_candidates`:** the full ranked candidate list per application, used for Remove/replace: `application_id, position, name, headline, linkedin_url, label, reason`.
- **`company_domains`:** `name_norm PRIMARY KEY, domain, pattern NULL, catch_all INTEGER NULL, mx_host NULL, checked_at`.
- **`usage`:** `month TEXT, service TEXT, amount REAL`, primary key (month, service), plus a daily SMTP counter stored as `service = 'smtp:<YYYY-MM-DD>'`.
- **`applications` gains:** `find_status` (`idle|running|done|failed`), `find_error`, `find_started_at`.
- **`contacts.email_status`** keeps `unverified|verified|bounced`. The new **likely** maps to `unverified`, and `email_source` says how the address was found.
- **`applications.contact_id`** continues to point at #1, so existing code and history keep working.

**Migration:** `connect()` adds the new tables and columns to existing databases, as it did in the discovery build.

### 3.5 Settings (`profile/preferences.yaml`, `contacts:` block, all with defaults)

```yaml
contacts:
  tavily_monthly_limit: 950
  apify_monthly_usd_limit: 4.5
  hunter_monthly_limit: 45
  smtp_daily_limit: 60
  smtp_pause_seconds: 2
  sender_email: mkshitij1763@gmail.com   # used for SMTP MAIL FROM only; nothing is sent
```

### 3.6 Failure handling

| Failure | Behaviour |
|---|---|
| Missing `TAVILY_API_KEY` | The Find contacts button shows "Add TAVILY_API_KEY to .env"; manual entry still works. |
| Tavily, Groq or Apify error | `find_status = failed` with the reason; **Try again** button; whatever was found so far is kept. |
| A budget is reached | That service is skipped; the card names it ("Apify budget used for October"). |
| Port 25 blocked | Verification is skipped for the run; emails come back as **likely**; the card says "Couldn't verify on this network". |
| Catch-all or 4xx answer | **likely** for that person; fallbacks are tried within budget. |
| Mac sleeps mid-run | A `running` job older than 10 minutes is shown as failed, with **Try again**. |

### 3.7 Privacy and limits

- Only public name, headline, profile URL and work email are stored, for at most 3 people per application. No personal emails or phone numbers.
- Everything stays in the local database.
- The app sends nothing. SMTP checks stop before `DATA`.
- The card shows a monthly usage line: "Tavily 37/950 · Apify $0.40/$4.50 · Hunter 2/45 · SMTP today 12/60".

## 4. Testing

- **No network in tests.** Tavily, Apify, Hunter and DNS are faked (`respx`, or injected resolvers). The SMTP verifier takes an injectable `smtp_factory`, tested against a fake server class that scripts the replies: 250, 550, 4xx, catch-all, and a connection refusal.
- **Unit tests:**
  - name cleanup and candidates, with the §3.2 examples (Asha Rao, Rahul Kumar Sharma, K. Meshram, a single name, "José", "Asha Rao, PMP | Ex-Flipkart");
  - parsing Tavily titles and filtering by company;
  - ranking guarded to list indices only;
  - domain detection and the MX requirement;
  - inferring a pattern from public addresses;
  - the SMTP outcomes, including "DATA is never sent";
  - budget caps per service and per day;
  - Apify and Hunter fallbacks, used only when needed and within budget.
- **Flow tests:**
  - Approve creates drafts for wave 1 only, with per-person greetings, honouring likely/bounced;
  - the #3 badge and "Draft email to #3" appear after 5 days;
  - a reply suppresses wave 2;
  - Not interested blocks all linked people;
  - Remove promotes the next candidate;
  - background status: running → done/failed, and the stale-run timeout.
- **Live check after the build:** Find contacts on 2–3 real jobs using real Tavily and real SMTP checks (nothing sent), with Apify and Hunter only if triggered. Report each person's status and the usage counts. No Gmail drafts are created; the user does the first real Approve.

## 5. Out of scope

- Any automation of the user's logged-in LinkedIn (connection requests, messages, profile visits).
- Phone numbers, personal emails, and enrichment beyond name, headline, profile and work email.
- Automatic contact finding in the daily run (it is on demand by decision).
- Paid tiers of any service.
- Sending email, or automating the follow-up send.
