# Working notes (raw, feeds the report)

## Pass 1: roommate "before" state (2026-10-10, ~05:00 IST, before delete)
Account horizon.1763@gmail.com (Google display name also "Kshitij Meshram", same resume as owner).
- Today: "Good morning, Kshitij." · **36 New today** · **18 Shortlisted**. One section "Shortlisted 18 — Apply on the company site, then tap Mark applied on the job." listing 18 jobs (89 Media.net … 71 AppsForBharat).
- Jobs (`/`): "18 jobs · swipe ← skip, → snooze"; filters Apply/Review/All, Role ▾, City ▾, Source ▾.
- Pipeline: Replies 0, Interviews 0; Shortlisted 18, Replied 0, Interview 0, Offer 0, Closed 0.
- Settings → Account: text "Next possible at 05:31" (Fetch now was used earlier, not by this review), no Gmail card (outreach off, correct).
- Server timings (fetch from the page, warm): /today 309 ms, / 409 ms, /pipeline 306 ms.

### Candidate findings spotted
- Today "36 New today" vs Jobs "18 jobs": two numbers, unclear relation.
- Seniority: "Principal Product Manager" (Target) 77 and "Senior Product Manager – Tech, Amazon" 77 shortlisted for a ~1.3-yr profile.
- Role filter shows raw internal values: "ai pm", "founders office", "pm", "apm", "other" (lowercase, no apostrophe). Source filter "ashby/greenhouse/lever" are ATS vendor names, meaningless to users.
- Pipeline column label "shortlisted 18" lowercase; Move… menu offers "drafted" to a user with outreach OFF.
- Settings → Account: "Next possible at 05:31" orphaned, with no label saying it's about Fetch now.
- Landing (390, dark): no product name/logo on the page itself (only <title>); privacy line is the lowest-contrast text on the card.
- Tooling: Google blocks sign-in in automation-controlled Chrome (not an app bug).

## Pass 1: delete (done 2026-10-10 ~05:04 IST, user OK'd)
- Settings → "Delete my account" (a link) → /settings/delete: bare page (no nav), card left-aligned not centred at 1470; input and "Delete my account" button touch (no gap); danger button is a quiet outline (`btn btn-danger bad`), barely reads as destructive. Placeholder shows the email to type (good); "Download my data first" link (good). img/p1-02.
- **BUG (likely P1): after typing the email and pressing Delete, nothing on screen changes.** The account *is* deleted (fetch /settings → opaqueredirect; reload → Google account chooser). Cause: `<body hx-boost="true">` makes the form an XHR; server returns 303 → /login → 302 to accounts.google.com (cross-origin), which XHR can't follow, so HTMX silently does nothing. User is left on a filled-in delete form, likely presses again (→ error) or thinks it failed. Also wrong destination: it should land on a "Your account is deleted" page, not restart Google sign-in. img/p1-03. `settings.py:152-163`.
- Same chain for **Sign out / Sign out everywhere** (`auth.py:103-120`, 303 → /login) → likely the same silent no-op. VERIFY.
- HTMX 2.0.4 does not swap 4xx by default. **Onboarding is NOT affected** (bare.html has no hx-boost; 422 errors render fine). Still to check: boosted pages that return 422/403 (delete "The email doesn't match", Settings forms).
- Signed-out deep link (/settings) goes straight to Google's account chooser with no landing page: acceptable, but a user who just deleted is bounced into sign-in.

## Pass 1: onboarding (re-invited by owner, signed in ~05:07 IST), desktop 1470 dark
Step 1 Roles (img p1-04/05)
- No welcome or orientation (what's coming, ~2 min, why). First line is the admin-visibility notice, before the question: surveillance-first framing.
- "Step 1 of 4" in small monospace muted text; no progress bar. Card left-aligned at 1470 (not centred); lots of dead space.
- Chips = native checkbox inside a pill (double affordance). Checked state clear (accent).
- Empty submit → 422 "Pick at least one role" inline, OK. But the error stays visible after picking chips (no live clear). P3.
- Catalog: Product Analyst, APM, PM, Founder's Office, Growth/Business/Data Analyst, Program Manager, Strategy & Ops. (Jobs filter later shows different family names: "ai pm", "pm", "apm", "other".)
- Continue gives no busy state; full POST+redirect ~0.6 s, felt like nothing happened once (my click on a ref did not submit; second click did; treat as tooling, not app).
Step 2 Where (img p1-06)
- "Remote within India is fine" is **pre-ticked** and satisfies validation alone: a user who taps Continue gets remote-only (very few jobs). P2.
- Remote is a bare square checkbox; cities are chips: inconsistent. No helper line under the heading (step 1 has one). City list lacks Kolkata/Ahmedabad (fine, "Other cities" covers it); "Gurgaon" vs "Gurugram".
- **Back is a plain link: it discards the current step's unsaved choices** (picked Bengaluru+Mumbai, Back, Continue → both gone). P2.
Step 3 Experience and pay (img p1-07/08)
- 8 fields in one card, ~1.3 screens; only 2 required. Heavy for a phone.
- Label "Hide jobs asking for at least __ years" reads like a fill-in-the-blank; no explanation of what it does.
- **Spec drift: threshold is not pre-filled after entering years** (spec: ceil((years+1)*2)/2 → 2.5 for 1.3). User must invent a number. P2.
- Validation good: threshold 1 < 1.3 → "Must be more than your years of experience" inline, values kept.
- **"Hide titles containing" is a single-line text input** pre-filled with 18 terms that overflow off the right edge (spec: removable chips). Can't see/edit what is hidden. P2.
- Default deny list lacks "senior", "principal", "lead", "staff", "manager II" → explains Principal PM / Senior PM shortlisted for a 1.3-yr profile (before-state). P1 (match quality, both personas).
- "Must-haves", "Deal-breakers", "Your experience in a sentence or two": no hint how they're used (scoring only).
- Focus ring: 1px accent border only, no outline/shadow: visible but weak. P3 (WCAG 2.4.13 enhanced).
- CTC fields: no hint of privacy (admin can see preferences → can the admin see my CTC? Landing says "preferences" are visible to admin). Trust risk. CHECK on admin user view in pass 2.
Step 4 Resume (img p1-09..12)
- Native unstyled file input ("Choose file" light grey on dark), separate Upload button (two actions), Finish disabled with no reason. File input has no accessible name (label wraps text + input, but a11y tree shows "(no name)").
- No line about why the resume is needed or who sees it (landing says only you).
- Upload → "Resume saved. Reading it now." flash (message carried in ?msg= query string → reappears on refresh/back). File input resets to "No file chosen" and the uploaded file's name is not shown → looks like it was lost. P3.
- "Reading your resume…" muted text, no spinner, no time hint. Took <10 s. Extraction quality: excellent (headline, 2 roles with dates, ~25 skills, 13 achievements incl. extracurriculars).
- **BUG P1: when reading finishes, Finish stays disabled.** `_resume_status.html` polls and swaps only #resume-status; Finish is outside it (`onboarding/resume.html:18`, `disabled` rendered server-side when no facts). Only a reload or pressing "Save facts" enables it. New users stall at the last step.
- Flash "Resume saved. Reading it now." stays after reading is done (stale).
- Facts review: Roles in a <fieldset> with a bright default border (unstyled, inconsistent); role rows are 4 unlabeled inputs (title/org/start/end) — a11y + clarity. Skills single-line overflowing. Achievements 13 textareas → page ~2,000 px tall; Finish at the very bottom.
- Copy "Scores and drafts use only these facts": roommate has no drafts (outreach off).
- "Save facts" (secondary) above "Finish" (primary): unclear whether Finish saves edits. After Save facts: full reload to top, flash "Saved" out of view of the button pressed.
- "Enter my skills myself" appears only after a failed read → checklist D item "try Enter my skills myself once" is not reachable on a successful read. BLOCKED unless a read fails.
- Finish → /onboarding/done "You're set." + "Checking jobs…" + Fetch now (outline) + Go to Jobs (primary) stacked touching (no gap). No "first scores arrive with the next run" line visible at first paint (checklist D "Finish" expects it). Fetch now NOT pressed (quota). img p1-13.
- Extraction pre-drafted "Your experience in a sentence or two" correctly (spec OK).
- Owner: invite confirmation URL carries the email in the query string (`/admin?msg=Invited%20horizon…&invited=horizon…`) → PII in URL/history. P3.

## Pass 5 baseline — BEFORE REGION MOVE (Railway US East), 2026-10-10 ~05:10 IST, owner account, Mac on home Wi-Fi in India
Method: same-origin iframe 390×844 per page (window can't go below 500 px), Navigation Timing; "first" = first load this session (static assets already in browser cache from earlier use, so not a true empty-cache cold load), "repeat" = immediate reload; plus 5× `fetch(cache:'no-store')` of the HTML, median. Server time per manager: 5–13 ms, so ~280 ms TTFB ≈ India↔US round trip.

| Page | TTFB first / repeat | DOMContentLoaded first / repeat | Load first / repeat | HTML (decoded) | HTML fetch median (5×) | Notes |
|---|---|---|---|---|---|---|
| /today | 285 / 283 | 308 / 303 | 318 / 315 | 9.1 KB | 291 ms | + `/fetch-now/status` hx-get after load (~275 ms, 2nd round trip) |
| / (Jobs) | 301 / 306 | 443 / 394 | 506 / 439 | **186.5 KB** | 334 ms | heaviest page; owner inbox renders all rows server-side |
| /applications/10 | 340 / 282 | 362 / 307 | 372 / 317 | 25.8 KB | 295 ms | |
| /pipeline | 304 / 333 | 348 / 387 | 504 / 470 | 75.9 KB | 314 ms (one 637 outlier) | |
| /settings | 277 / 280 | 301 / 316 | 324 / 358 | 19.8 KB | 314 ms | + `/fetch-now/status` hx-get (~280 ms) |
| /admin | 274 / 282 | 297 / 304 | 306 / 310 | 9.5 KB | 284 ms | **horizontal scroll at 390** |
Top-level navigation of /today in the real window (500 px): TTFB 286, DCL 396, load 847 ms (manifest 297 ms + fonts ~300 ms each revalidated).
- **Fonts (`/static/fonts/*.woff2`) and manifest are not fingerprinted** → revalidated (304, ~300 B) on every page load = an extra US round trip each. CSS/JS are fingerprinted and served from cache (0 ms). Recommendation: fingerprint fonts + long immutable cache; preload Geist.
- `/fetch-now/status` loaded by hx-get after page load on Today and Settings = a second sequential round trip; inline its initial state in the page.
- No CLS measured (0) in iframes; layout shift to re-check visually in pass 4.

## Pass 1: first matches (new roommate, ~05:12 IST)
- Done card updates to "Checked 3,285 jobs; 170 match your filters. Your first scores arrive with the next run." — never says *when* (11:15 IST, ~6 h away). Fetch now is offered as a quiet outline button with no explanation of what it does or that it's limited.
- **P1 first-run dead end:** Go to Jobs → "0 jobs · We're still looking. New jobs arrive after the 11:15 run, or change the filters." on Apply, Review AND All. The 170 jobs that "match your filters" are invisible anywhere until scored. Today says "**All caught up** — Shortlist jobs from Jobs…" (wrong state for a user who has seen nothing; points to an empty Jobs). Pipeline all zeros. Biggest drop-off risk of the journey: the app's promise (landing: "you read 10 jobs, not 600") meets an empty app. img p1-14.
  Recommendation: auto-queue the first Fetch now/scoring on Finish (or show unscored matches in Review with "score pending"), give a time ("first scores by ~11:30 today"), and a distinct first-run empty state on Today/Jobs.
- Empty-state sentence rendered twice in the Jobs DOM (table row + phone card list); fine visually per width, but screen readers read it twice. CHECK.
- Filter menus: "All roles"/"All cities"/"All sources" links go to `/?band=apply`, dropping the current band (e.g. on Review, choosing All roles jumps back to Apply). P2 bug.
- Desktop sidebar: brand "J Job Seeker" tile, Today/Jobs/Pipeline/Settings; no counts shown for a new user (fine). Keyboard hint "j/k move · enter open · s skip · z snooze" shown even with 0 rows.
- Today (new user, 1470): "Good morning, Kshitij." + "Here's what needs you today." + Fetch now (outline, unexplained) + tiles 0 New today / 0 Shortlisted + "All caught up". Spec wanted date + "last run finished" line: missing. img p1-15.
- **Fetch now used (the review's one, user OK'd) on the roommate at 05:07 IST.** Result: green flash "Queued, starts in a few minutes" at the top; the Fetch now button vanished; no visible status slot / "Running since" line. img p1-16. Timings to follow.

## Quota/OK ledger
- Fetch now: USED on roommate 05:07 IST (user OK). None left.
- Find contacts: not used.

## Pass 2: owner — Admin (1440, read-only)
- /admin: Invites table (Email/Invited/Accepted + Remove), Users (Email/Name/Last login/Status/Outreach + Turn outreach on/off + Disable), Usage, Backups.
- **Dates are UTC, not IST**: horizon invited+accepted "2026-10-09" though it happened 2026-10-10 ~05:05 IST (= 23:35 UTC 9 Oct). Same for Joined/Last login on the user view. P2 (wrong day for ~5.5 h every night).
- Usage: raw float "0.24000000000000007" (apify) — no rounding, no units ($ vs calls), raw service keys ("groq:facts", "score", "tavily"); tombstone row "deleted-2@invalid". Note "Daily services show today, monthly services this month" doesn't say which is which. P2.
- No confirmation on Disable / Remove invite / outreach toggles (single click POST). Disable shown on the owner's own row (server refuses via LastAdmin, so P3: hide it). Remove shown for an *accepted* invite (what does it do to the user? unclear). P2.
- **/admin scrolls horizontally at 1440 and 390** (scrollWidth > innerWidth). P2.
- Backups: "Off-site backup isn't configured" (expected while B2 off).
- Owner row name "Kshitij Meshram" and roommate name "Kshitij Meshram" (same Google display name) → only email distinguishes; fine for the test, but avatar/initial would help.
## Pass 2: Admin user view /admin/users/4 (roommate)
- Header "Kshitij Meshram ← Admin", "Read-only. Their resume, facts, Gmail, contacts and drafts stay private." Good disclosure.
- **Privacy/trust P1: Pay (current CTC, target base) is shown to the admin.** Onboarding's notice says "job preferences and application statuses"; the landing says "job preferences". Salary is the item people least expect to be shared with a roommate. Either hide pay from the admin view or say so explicitly next to the CTC fields.
- Shows "Jobs up to 7 days old" — a setting the user never saw or set (not in onboarding or Settings?). CHECK Settings.
- **Match quality P1:** Shown 170 for roles PA/APM/PM includes Inventory Analyst (Stalwarts), Clinical Business Analyst, QA Analyst Lead, Senior Incident Response Analyst (Jobgether), Operations Analyst (ANZ), Lead Data Analyst (Target), Product Control Sr Analyst (Deutsche Bank), SENIOR, DATA ANALYST (Walmart). Looks like the role filter admits any "Analyst"; seniority words pass (no senior/lead/principal in default deny). The scorer may sink them, but they cost the user's per-day score share and clutter Review.
- Top-20 table: "Score —" for all (not scored yet); "best score first" with no scores reads oddly.

## Pass 2: owner — Today (1440)
- Tiles: 62 New today → `/` (Jobs shows 86, unfiltered: number doesn't carry through) · 3 Ready to approve → #ready · 31 Need contacts → #find · 0 Send in Gmail → **#send, a section not rendered at 0 → dead anchor** (P3).
- Sections: Ready to approve (3: Tracxn Sr APM 92, slice Sr PA 91, Headout PA 84), Find contacts (31; top: **Principal Product Manager · Sabre 95**), "26 more in Jobs →". Rows show only score+title+company (no city/age/next step).
- No run-notes pill anywhere (spec: phone top bar / bottom of sidebar). Spec's date + "last run finished" line missing.
- Sidebar: Jobs 86, **Pipeline 1** (owner has ~240 applications; badge meaning unclear). Admin pinned at the bottom (good).
## Pass 2: Job detail /applications/188 (Principal PM, Sabre)
- **Match quality P1 (scorer):** 95 "Strong match", **Experience 25/25** for a *Principal* PM with a 1.3-yr profile. Why-you-match bullets are generic ("Data-driven product vision and roadmap"); Watch-out misses the obvious seniority gap. img p2-02.
- **P0 (config): Find contacts is disabled on prod**: `<button class=primary disabled title="Add TAVILY_API_KEY to .env">`. Step ① of outreach is dead for all 31 "Need contacts" jobs; the only explanation is a developer tooltip (invisible on touch). Reported to manager. Two Find contacts buttons render (step card + People card), both disabled.
- **Approve → Gmail draft is enabled** while the step bar says ① Find contacts and there are no people; with no people it falls to `_approve_single` (legacy path, `web/outreach.py:108-109`). Not clicked (would touch real Gmail). P2: disable Approve until ① is done, or say who it will draft to.
- Header: status pill "drafted" and source "linkedin" raw lowercase. P3.
- JD renders **raw Markdown** ("**Powering the agentic revolution in travel.**"). P2.
- People card shows a raw quota line: "This month: Your Tavily 32/950 · All 32/950 · Apify $0.24/$4.50 · All $0.24/$4.50 · Hunter 4/45 · All 4/45 · SMTP today 0/60 · All 0/60" — vendor names, $ and SMTP in the user's face. P2 (move to Admin/Settings; show "Contact searches left this month: N").
- More menu: Mark sent, Applied via portal, Skip, Snooze 3d, Regenerate all, Undo last change, Not interested — "Mark sent" offered before Approve; destructive "Not interested" not separated. Term "Applied via portal" (owner) vs "Mark applied" (roommate). P3.
- Drafts: "113/150 words", Save, explanation of greeting/signature, "AI prepared this… nothing is sent until you press Send." Good trust copy.
- Phone (501 px): tabs People/Draft/Job switch client-side, default People for drafted (spec OK). Small targets: back link "← Jobs" 22 px tall, "Search LinkedIn ↗" 20 px. No h-scroll.

## Pass 2: owner — Jobs (501 px phone layout)
- Cards: title, score pill, "Sabre · Bengaluru · 2d · linkedin" (source lowercase), one ✓ + one ⚠ (truncated with …), next-step link "Find contacts →" (dead end in prod), Skip/Snooze buttons ~44 px. Header "86 jobs · swipe ← skip, → snooze". img p2-04.
- Bands: Apply 86 · Review 52 · All 185 → 47 jobs only under All, unexplained (below cutoff?). Band names Apply/Review/All are terse; no tooltip/explainer of what decides the band.
- **Role menu shows CSS-capitalised internal keys: "Ai Pm", "Apm", "Pm", "Founders Office", "Other", "Analytics", "Product Analyst"** — wrong casing and different vocabulary from onboarding's role chips. No counts, no current-selection mark. Source menu = ashby/greenhouse/indeed/lever/linkedin/naukri (vendor names). img p2-05. P2.
- **Filter menus (`<details>`) don't close on Escape or on tapping outside**; the open menu covers the cards. P2 (a11y + usability).
- "All roles/All cities/All sources" reset band to apply (see pass 1). P2.
## Pass 2: owner — Pipeline (501)
- Stat strip "55 Drafted (30d) · 1 Sent · 0 Replies · 0% Reply rate" overflows right; "Reply rate" clipped. **"Drafted (30d) 55" vs chip "Drafted 34"**: two numbers for one word. P2.
- Chips: Shortlisted 52 · Drafted 34 · Approved 0 · Sent 1 · Replied 0 · … (horizontal scroll). Opens on Drafted (no follow-up due) — spec OK.
- Nav badge "1" on Pipeline = Sent count? Reads like a notification. Unexplained. P3.
- Cards: title, score, "Sabre · 0d since last action", "Find contacts →", "Move…" (details). img p2-06.
## Pass 2: owner — Settings (501, read-only)
- 3,138 px tall (~4.7 screens). Cards: Profile · What I'm looking for (Roles, Advanced (custom matching), Where, Experience and pay; **4 separate Save buttons**) · Resume and facts · Daily match alerts · Account (Fetch now, "GMAIL" all-caps label, Drafts go to … · connected today · Reconnect, Download my data, Sign out, Sign out everywhere, Delete my account).
- Advanced copy: "Your matching was carried over as written. While "Title must contain" is set, the role chips above only change searches, not which titles pass." → two overlapping matching systems explained in jargon; chips look editable but may not change results. "Use the role chips instead" clears custom text with no confirm. P2.
- Owner role chips ticked: PA, APM, PM, Founder's Office, Growth Analyst.
- Delete page (GET only): "You're the only admin, so this account can't be deleted." + disabled button → checklist F (owner part) PASS.
- No visible "Jobs up to 7 days old" setting even though the admin user view lists it. CHECK.

## Checklist A "Preference preview" (done on the ROOMMATE to keep the owner untouched; same code path)
- Settings → Where → tick Hyderabad → "Save where" (button sits inline after the Remote checkbox; "Save profile" above is full-width: inconsistent). Boosted POST → page swaps, scrolls to top, preview card in "What I'm looking for": "This hides 0 jobs, brings back 25 and skips 0 drafted applications. [Save] [Cancel]". Clear, good. img p3-01.
  - Copy: "brings back 25" for a newly added city (they were never shown) → "adds 25"; "drafted applications" for a user with no drafts (outreach off).
  - **The URL becomes `/settings/prefs/where` (hx-boost pushes the POST URL); a refresh/back-forward lands on raw JSON `{"detail":"Method Not Allowed"}` (405).** P2. Same likely for every boosted POST that re-renders (e.g. 422 on Settings).
  - First DOM check found nothing because swap finished after my check → the swap gives no busy cue for ~1 s. P3.
- Cancel → back to /settings, Hyderabad unticked, nothing saved. **PASS.** Confirm-Save not exercised (a run was in progress for this user).

## Pass 4/5: landing Lighthouse + PWA (public page only)
- Lighthouse (navigation, mobile and desktop): Accessibility 100, Best Practices 100, Agentic 100, SEO 50 (fails: `is-crawlable` = intended noindex; `meta-description` missing).
- No `<meta name=description>` and no Open Graph tags → the invite link the owner pastes into WhatsApp/Slack previews as a bare URL/"Job Seeker". P3 (cheap trust win for invitees).
- `/favicon.ico` → 404 (JSON body); no `<link rel=icon>` → blank browser-tab icon. P3.
- Manifest (`/static/manifest.webmanifest`): name/short_name "Job Seeker", start_url /today, standalone, **theme_color #2563eb and background_color #fafafa = pre-redesign colours** (tokens now accent #3B5BF5, light #FBFBF9, dark #0B1120) → light splash flash for dark-mode users, wrong status-bar tint on Android. Only 180 and 512 icons; no 192, no `purpose: maskable`. P3.
- App icon (img p5-icon-512.png): blocky white briefcase on old blue #2563eb; the in-app brand is a "J" lettermark tile in the new accent → two different brand marks. P3.
- **Fonts served with no Cache-Control and `Content-Type: application/octet-stream`** (should be `font/woff2`, `immutable`, fingerprinted) → confirms the per-page revalidation round trips in the baseline. Manifest also has no Cache-Control. P2 (perf, cheap).
- /healthz 200 `no-store`. OK.

## Pass 4: colour tokens and contrast (ui.css, both themes; computed WCAG ratios)
Theme follows `prefers-color-scheme` only (no in-app switch). Light tokens per spec; dark derived.
| Pair | Light | Dark |
|---|---|---|
| --text on surface | 17.85 | 14.57 |
| --text-2 (muted) on surface | 7.58 | 7.93 |
| **--text-3 (faint) on surface / bg** | **2.56 / 2.47 FAIL** | **3.92 / 4.16 fail for small text** |
| accent on surface | 5.25 | 5.56 |
| **white on accent (primary buttons)** | 5.25 | **3.19 FAIL (14 px text)** |
| tier pills strong/good/weak | 7.3 / 6.8 / 7.6 | 9.7 / 10.1 / 8.4 |
| **neutral pill (status pills)** | **4.34 (just under)** | 7.12 |
| **--line / --line-strong vs surface (input & card borders)** | **1.24 / 1.48** | **1.34 / 1.71** (non-text needs 3:1) |
- --text-3 is used for `.faint`, chip counts (11 px), sidebar count badges, placeholders → fails AA in light. P2.
- Dark primary buttons (Continue, Finish, Go to Jobs, Save, Approve) are white on #6F87FF = 3.19:1. Darken dark-mode accent for fills (e.g. #4F6BFA ≈ 4.6:1) or use dark text. P2.
- Inputs: fill #1A2232 on card #111827 (dark) and a 1.2–1.7:1 border → fields barely visible as fields (seen on onboarding step 3). P2 (WCAG 1.4.11).
- Landing light (img p4-01): clean; card edge faint; large empty gap between the invite note and the privacy text (both themes); no product name/logo on the page itself. P3.

## Pass 4: responsive sweep (owner pages in same-origin iframes at 820×1180 and 390×844)
| Page | 820: h-scroll / height / small targets (<44 px tall) | 390: h-scroll / height / small targets |
|---|---|---|
| /today | no / 1,176 / 1 of 20 | no / 1,307 / 2 of 19 |
| / (Jobs) | no / **8,560** / **235 of 296** | no / **15,225** / 118 of 295 |
| /applications/10 | no / 4,474 / 8 of 65 | no / 2,140 / 5 of 45 |
| /pipeline | board scrolls sideways (spec allows) / 7,700 / **299 of 354** | stat tiles overflow right / 5,686 / 71 of 149 |
| /settings | no / 2,770 / 23 of 65 | no / 3,264 / 24 of 64 |
| /admin | no / 1,176 / 2 of 17 | **yes (603 px wide)** / 1,302 / 3 of 16 |
| /admin/users/4 | no / 1,917 / 1 of 7 | no / 2,625 / 2 of 6 |
- **Jobs renders every row server-side with no paging**: 15,225 px tall on a phone (86 cards in Apply; All has 185) and 186 KB HTML. P2 (perf + scroll fatigue); paginate or "show 20 more".
- Tablet 820 (img p4-02): icon-only sidebar with no labels/tooltips; count badges overlap icons. Table drops the **Why** column (✓/⚠) → tablet users lose the reasons phone users get. Skip/Snooze are small text links (~22 px tall); meta line raw "pm · linkedin · needs contacts". P2.
- Pipeline at 820: 299/354 small targets (Move… summaries, card links).
## Pass 4: keyboard
- Jobs j/k moves a `.sel` row highlight (works), but focus stays on <body> → screen readers don't follow; Enter/s/z act on a row the AT can't perceive. P2. (s/z not pressed on owner.)
- Tab focus: `:focus-visible` 2 px accent outline + 2 px offset on buttons/links/summary: GOOD. Inputs only change border colour (weak). No skip link; ~300 controls before content ends on Jobs. P3.
- Filter `<details>` menus: no Esc / outside-click close (see pass 2).
