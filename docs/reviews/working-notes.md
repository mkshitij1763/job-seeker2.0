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
- **HTMX 2.0.4 default does not swap 4xx/5xx**; no `htmx.config.responseHandling` override anywhere. So every 422 re-render (onboarding step validation, "The email doesn't match", resume upload errors) may show nothing. VERIFY in onboarding.
- Signed-out deep link (/settings) goes straight to Google's account chooser with no landing page: acceptable, but a user who just deleted is bounced into sign-in.
