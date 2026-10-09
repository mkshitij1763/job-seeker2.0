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
