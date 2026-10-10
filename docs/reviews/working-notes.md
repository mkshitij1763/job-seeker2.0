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

## Keys added on Railway (manager, deploy 858166ad 05:14 IST): Find contacts now ENABLED on /applications/188 (verified 05:19).
- Keep as finding: before the keys, Find contacts was `disabled` with a dev tooltip "Add TAVILY_API_KEY to .env" (invisible on touch, dev wording). Recommendation: when a service is missing, show a visible user-facing line ("Contact search is off on this server; ask Kshitij") and hide the Find-contacts chips/next-step on cards.

## Find contacts — the review's ONE run (owner, user OK'd directly 05:19 IST), /applications/169 Groww APM (score 92)
Timeline: click 05:20:2x → POST /applications/169/contacts/find 200 → boosted reload to top → People card "Finding contacts… (searching, ranking and verifying emails, about half a minute)" polling `/contacts/card` every 3 s → results 05:21:08 (**~48 s**, copy promises "about half a minute").
- **No feedback where the user tapped**: the step-card button gives no busy state; the page reloads to the top and the progress text lives in the People card, below the fold on desktop (on phone it's the default tab, OK). P2.
- **P1 stale step card**: after results arrive, the top card still shows "① Find contacts" with an enabled primary "Find contacts" button (only #people-card is swapped). Pressing it starts a fresh paid search (claim_find only blocks *concurrent* runs). A manual reload shows the right state: "✓ Find contacts → ② Approve · Review and approve ↓ · Approve creates Gmail drafts for Anandh Rajan and Satvik Bansal. Nothing is sent until you press Send in Gmail." Same root cause as the onboarding Finish bug: polling swaps a fragment, dependent UI outside it goes stale. img p2-08.
- Results card: "Found 3 people, 0 verified emails. Email checks aren't available on this server; emails are best guesses unless Apify or Hunter found them." (server/vendor wording; say "We couldn't verify these emails; they're our best guess").
  - #1 Anandh Rajan · hiring manager · email now · "Product Manager at Groww" · anandh.rajan@groww.in · likely — good pick.
  - #2 Satvik Bansal · team lead · email now · headline "**Product @ slice** | Groww | IIT Kharagpur" → appears to work at **slice now**; email guessed @groww.in.
  - #3 Vineet Shukla · peer · follow-up · "**Stealth** | **Ex-PM at Groww** | IITK'21" → left Groww; email guessed @groww.in.
  - **P1 contact quality: 2 of 3 are not current Groww employees, yet get @groww.in guesses; #2 is in wave 1, so Approve would draft to a likely-dead address.** The ranker should drop "ex-"/"former"/other-company-first headlines, or label "May have left Groww".
- Labels: role chip (hiring manager/team lead/peer), timing chip ("email now"/"follow-up"), status "likely" (amber mono pill). No legend for "likely" vs "verified"; "email now"/"follow-up" chips are unexplained.
- Quota line moved: Tavily 32→36, Apify $0.24→$0.27, Hunter 4→5 (one find ≈ 4 Tavily calls + ~$0.03 Apify + 1 Hunter).
- Approve NOT pressed. Nothing sent.

## Fetch now — owner (user OK'd directly), 05:22 IST
- First click landed before the page was interactive → nothing happened, no feedback (P3: the slot is hx-loaded after the page, so the button can be dead for ~300 ms).
- Second click → flash "Queued: starts after the current run" while the status line says "Queued, starts in a few minutes" (two different messages for one state; the first is correct, the roommate's run holds the lock). Button disappears.
- Edge: POST /fetch-now again while queued → flash "Already queued", status unchanged, no new row. **PASS.** (Shown in a green "ok" flash although it's a refusal: P3.)
- Roommate run: "Running since 05:07" still at 05:22 — 15+ min with no progress, no ETA, no "you can close this page".

## **P1 CONFIRMED: validation errors on boosted pages are invisible (HTMX 2 does not swap 4xx)**
- Roommate Settings → Replace resume → `fake.pdf` (%PDF header, not a real PDF) → Upload → `POST /settings/resume` **422**, but the page does not change at all: no error text, same DOM length, the bad file still selected, no flash. The user sees a dead Upload button.
- Same mechanism covers every 422/403 re-render on boosted pages: `settings.py:75` (preferences validation), `:98/:113/:121` (resume / facts errors), `:155` delete "The email doesn't match", `:159` "You're the only admin", plus the CSRF 403 "Request blocked". Onboarding is unaffected (bare.html not boosted).
- Fix: `htmx.config.responseHandling = [{code:"204", swap:false},{code:"[23]..", swap:true},{code:"4..", swap:true, error:false},{code:"...", swap:false, error:true}]` (or `hx-boost="false"` on these forms), and an htmx:responseError toast for 5xx.

## Edge: data isolation and error pages (roommate session, GETs)
- Owner's /applications/10, /applications/169, /applications/188/contacts/card, /admin, /admin/users/1 → **404 for the roommate: no data leak. PASS.** (Sequential integer IDs are safe because every query is user-scoped.)
- **Every 404 (and 405 seen earlier) is a raw JSON page `{"detail":"Not Found"}`** — no layout, no nav, no "Back to Today". Hit by stale links (e.g. a job removed by Settings, the admin link in a shared screenshot, /settings/prefs/where after refresh). P2.
- /onboarding/roles after onboarding → redirect (good). /onboarding/done stays reachable and still shows the first-run card (harmless).

## People card interactions (owner, /applications/169, nothing saved)
- Copy note (real click): button → "Copied ✓". GOOD. But the LinkedIn note (199 chars, "Hi Anandh, I admire Groww's mission…") is in a **hidden** textarea → user copies text they can't read first; and the failure toast ("Couldn't copy. Select the text and copy it manually.") points at text that isn't visible → dead end when the clipboard is blocked (seen with a scripted click; can happen in in-app browsers). P2: show the note (collapsed preview) and make the fallback select a visible field.
- Edit / remove (per person): name, email, status select [unverified/verified/bounced] + Save; "Remove & use next candidate". **Vocabulary mismatch: pill says "likely", the select says "unverified"** for the same email. User can set "verified" by hand (word implies the system checked). No confirm on Remove. P2/P3.
- "Find contacts again" (paid search) and Remove: no confirmation, no cost hint. P2.
- Add someone myself: name, role, LinkedIn URL, email, status; nothing required. P3.
- img p2-09.

## Sign out (roommate)
- Sign out → lands directly on **Google's account chooser** ("Sign in with Google · Choose an account") — no "You're signed out" page, no way back to the landing page. Feels like the app is asking to sign in again; on a shared device the next person sees the account list. P2: land on the public landing with "You're signed out." (and for Delete: "Your account is deleted.").
- (My first click didn't register — tooling; the second navigated. So sign-out works, unlike Delete's silent no-op. Not re-tested: Sign out everywhere.)
- Settings → Daily match alerts for a new user: "Tell me once a day when there are new strong matches" checkbox **pre-ticked** + "Add Job Seeker to your Home Screen first…" → it looks on, but can't be on until installed. P3.
- Settings → Account shows the Fetch now slot as "Running since 05:07" (a pill), between Account header and Download my data — no label that this is Fetch now. P3.

## Reliability: a deploy killed the roommate's Fetch now; the UI kept saying "Running" (devops-lead2, 05:27 IST)
- Roommate run actually started ~05:12 IST (the UI said "Running since 05:07" = request time, not start time) and was **killed at 05:15 by the env-var redeploy** (container restart, no SIGTERM handler). The run lock was orphaned; every 5-min tick since logs "busy". Lock times out after 15 min of silence → expected takeover ~05:30–05:35, roommate request marked failed, owner's queued run starts. Peak memory 223 MB.
- **User-facing: for 20+ minutes the roommate saw "Running since 05:07" for a run that no longer existed**, and the owner saw "Queued: starts after the current run" behind a dead run. No timeout message, no "something went wrong, try again", no ETA. P1 (reliability + honesty of status). Fix proposed by devops (release lock on SIGTERM); UX side: show "started at", elapsed, and a stale-run message after N minutes; deploys should refuse/wait during runs (deploy.sh does on GCP, Railway redeploys don't).
- TO CHECK after takeover: what the roommate's status says when the request is marked failed, and whether the failed run counts against "Next possible at" (2 h) / 6 per day.
- Recovery (devops-lead2 via manager): stale-lock takeover at 05:30 IST; owner's queued Fetch now ran from ~05:31. So the dead run cost the owner ~9 min of queue and the roommate its request.

## Data completeness: Naukri returns nothing on Railway (devops-lead2 via manager, 05:3x IST)
- In the owner's 05:31 run every Naukri search failed with HTTP 406 (13×) → **Naukri contributes 0 jobs on Railway**, vs 148 Naukri jobs fetched on the Mac on 2026-10-09. Landing page promises "LinkedIn, Naukri, Indeed and company career pages".
- **Invisible to users**: only in server logs; the Source filter still lists "naukri"; no run note (run notes only show stats/errors that explain_run maps). P1 (data completeness on India's largest job board; silent). Being re-checked after the Singapore move. Recommendation: surface source failures as a run note ("Naukri couldn't be searched today") and on /admin.

## User-run checks (2026-10-10 ~05:30–05:35 IST)
- **D2 Not invited is refused: PASS.** Uninvited Google account → landing card with "This app is invite-only. Ask Kshitij for an invite." in place of the button (screenshot from user). No account created (not visible in /admin). Note: same big empty gap above the privacy text; no "Try another account" link (user must find their way back to Google's chooser). P3.
- **D9 Turn outreach on: PASS (owner side).** Banner: "Outreach on. 1. Add horizon.1763@gmail.com as a test user in Google Cloud → OAuth consent screen. 2. Ask them to open Settings → Connect Gmail". Roommate side confirmed: Today switches to 4 tiles (New today, Ready to approve, Need contacts, Send in Gmail); Settings → Account gains a Gmail card: "Not connected. Approving a draft puts it in your Gmail drafts; nothing is sent for you. Google will warn that this app isn't verified. It's Kshitij's personal app: tap Advanced → Continue. [Connect Gmail]". Good, honest copy.
- **C1 Add to Home Screen: PASS with a catch.** Opens full screen, dark status bar matches, icon fine. **User was signed out inside the home-screen app** (iOS gives standalone web apps their own cookie jar) and had to sign in again. Expected iOS behaviour, but nothing warns the user. P3: say "You'll sign in once more in the Home Screen app" in the install hint. img c1-iphone-pwa-today.png.
- **C4 Daily match alerts: PASS.** From the PWA: "On for this device", Send a test → "Sent. Check your notifications." and a notification "Test alert from Job Seeker · Alerts work on this device." arrived. img c4-iphone-alerts-test.png.
- **Owner has no way to reach Admin on the phone / PWA.** Admin link only in the desktop sidebar footer (`base.html:47`); the phone tab bar has 4 tabs; Settings has no Admin link; the PWA has no address bar → /admin unreachable from the installed app. P2 (owner). Fix: an "Admin" row at the top of Settings for admins (or a 5th tab for admins only).
- Owner's PWA Settings showed "Running since 05:22" = the time the request was **made**; devops says the run started ~05:31. The label claims a start time it doesn't know. P2 (honest status).
- After the owner's run: Jobs badge 86 → 90, New today 62 → 66.
- Roommate status after the killed run: plain "Fetch now" button again, **no failed/stale message** → the request silently vanished from the user's view. A replacement Fetch now (roommate) was queued 05:35:26 ("Queued: starts after the current run"); the killed run did NOT block it (no "Next possible at"). Replacement used because the original produced nothing (user asked for a full QA pass).

## Pass 2: owner Pipeline + a Sent job (read-only)
- Pipeline now: shortlisted 58, drafted 34, approved 0 ("No Gmail drafts waiting to send."), sent 1 (Zepto PM 97), replied/interview/offer 0, Closed 0.
- **Move… lets a Drafted card jump to "approved"** without creating Gmail drafts (and Shortlisted → "drafted" without drafts for a roommate with outreach off). The status machine allows it, but the board then lies about where drafts are. P2: limit Move to statuses that make sense or label them "Mark as…".
- **No view for Skipped / Snoozed / Not interested**: "Closed 0" while the owner has ~240 applications, most of them skipped (2.5-yr cutoff, Settings re-evaluations). After the 6 s Undo toast, a skipped job can't be found or restored anywhere in the UI. P2.
- Status words raw lowercase in Move menus and columns ("applied via portal", "not interested", "shortlisted 58"). P3.
- /applications/33 (Zepto, sent): step card all ✓ + "Sent. Follow-ups appear in People 5 days after Mark sent if there's no reply." Good, but no date ("on 13 Oct"). More menu still offers **"Mark sent"** and **"Open Gmail drafts ↗"** after sending (stale), plus "Mark followed up (0/2)" (cryptic counter). **No "Mark replied" on the job page** — the only path is Pipeline → Move… → replied; reply tracking is manual by decision, so its button should be the primary action on a Sent job. P2.
- **"1d since last action" for an event on 8 Oct while today is 10 Oct IST** → day maths in UTC (consistent with Admin dates). P2.
- Zepto PM scored 97 with Experience 25/25 again (scorer seniority). 

## Pass 6: roommate run, first matches, outreach ON (fresh session, from 05:43 IST)
- Session restarted; old tab ids gone. New tab 147722987 in Browser 1 (deviceId 4843c5f0…), Settings confirms "horizon.1763@gmail.com · from your Google account".
- 05:43:33 roommate `/fetch-now/status` → "Queued, starts in a few minutes" (request made 05:35:26; owner run started ~05:31). The status line sits inside the **Account** card with no label (between the "Account" heading and GMAIL) — reads like an account state, not a job run.
- **Connect Gmail (roommate), done by the user ~05:44:** user reports it worked ("Gmail connected: drafts go to horizon.1763@gmail.com"). Redirect lands on `/settings?msg=Gmail%20connected…` → green flash at the top. Account card afterwards: "GMAIL · Drafts go to horizon.1763@gmail.com · connected today · Reconnect". img c6-roommate-gmail-connected.jpg.
  - **No Disconnect.** Only "Reconnect"; to revoke, the user must find Google Account → Security → Third-party access. For a roommate who's handing over Gmail compose access to a friend's app, a visible "Disconnect Gmail" (revoke token + delete it) is a trust feature. P2.
  - The flash comes from a `?msg=` query string → stays in the URL; a reload or a bookmark shows "Gmail connected" again. P3 (same pattern elsewhere?).
  - "connected today" — relative date, no time; fine.
