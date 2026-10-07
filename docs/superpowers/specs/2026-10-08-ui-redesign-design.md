# UI redesign: Stitch look on the existing four pages

Date: 2026-10-08 · Branch: `ui-redesign` (merged into `main` only when the user finalises it)

## Goal

Give the dashboard a modern, calm, trustworthy look based on the Stitch "Kinetic Horizon" design system, without new backend features or invented data. The user found the current UI too basic and the full Stitch/SaaS spec (30 screens, marketing site, onboarding) too complex. This is the agreed middle way.

**Success:** the four pages the user actually uses look and feel like the Stitch designs. The job page explains the match visually and makes the next step obvious. Everything works on the iPhone first and the Mac second. All existing behaviour and tests keep working.

## Scope

In:
- **App shell:** bottom tab bar on the phone, left sidebar on the Mac.
- **Today:** dashboard with stat tiles and the existing action sections.
- **Jobs** (today's Inbox): new cards and chip filters. Swipe and Undo unchanged.
- **Job detail:** decision block (match ring, factor bars, why/watch-out), next-step bar, ⋯ More menu, People/Draft/Job tabs on the phone.
- **Pipeline:** Kanban columns on the Mac; stage chips and a single list on the phone.
- **Visual system:** colour, type, spacing and component tokens taken from Stitch's `DESIGN.md`, plus a dark mode.

Out (decided with the user):
- Contacts and Insights pages (Insights may come after 2–3 weeks of sending, as a separate spec).
- Marketing site, login, onboarding, pricing, Settings page, notification centre, ⌘K search.
- Any data the app does not have: salary bands, logos, company signals, contact response rates, pitch angles, spam/open scores.
- Drag-and-drop on the Kanban board.
- Tailwind, Material Symbols, or any runtime CDN dependency.

## Visual system

From `kinetic_horizon/DESIGN.md`, as CSS custom properties in one stylesheet:

- **Canvas:** `#FBFBF9` background, `#FFFFFF` cards, `#F4F4F0` muted fills, borders `#E5E7EB` / `#CBD5E1`.
- **Text:** `#0F172A` / `#475569` / `#94A3B8`.
- **Accent:** `#3B5BF5`, for main actions, the active tab and the current step only.
- **Tiers:**
  - strong (score ≥ 90): `#065F46` on `#ECFDF5`, border `#A7F3D0`
  - good (70–89): `#92400E` on `#FFFBEB`, border `#FDE68A`
  - weak (< 70): `#991B1B` on `#FEF2F2`, border `#FECACA`
  - neutral: `#64748B` on `#F1F5F9`
- **Type:** Geist (UI) and JetBrains Mono (scores, counts), self-hosted woff2 in `static/fonts/`. Scale: display 36/28, headline 24, title 18/15, body 15/13, label 12, with tabular numbers for all figures.
- **Shape and depth:** cards 16 px radius; controls 8 px; pills fully rounded. Level-1 shadow `0 1px 2px rgba(15,23,42,.04)`; level-3 for menus and popovers.
- **Dark mode:** the same tokens remapped under `prefers-color-scheme: dark`. Stitch defines no dark theme, so it is derived: slate background, raised slate cards, the same tier hues at lower saturation.
- **Icons:** a handful of inline SVGs (today, jobs, pipeline, more, check, warning, external link). No icon font.

## Pages

### Shell (`base.html`)
- **Phone (≤ 640 px):** slim top bar with the brand and the run-notes pill; fixed bottom tab bar Today · Jobs · Pipeline with icon, label and 44 px targets, padded for `env(safe-area-inset-bottom)`. The active tab uses the accent colour.
- **Mac (> 640 px):** 240 px left sidebar with the same three items and counts (Jobs = inbox rows, Pipeline = active applications). Run notes sit at the bottom of the sidebar; content max width 1200 px.
- Flash messages, toast and `hx-boost` behave as now.

### Today (`/today`)
- Greeting by time of day ("Good morning, Kshitij."), the date, and when the last run finished.
- Four stat tiles: New today · Ready to approve · Need contacts · Send in Gmail. Each anchors to its section.
- Sections stay as now (Send in Gmail with Mark sent, Follow-ups due, Ready to approve, Find contacts top 5, new-jobs link), restyled as cards with tiered match pills.
- The empty state ("All caught up") gets the new styling.

### Jobs (`/`)
- Phone cards: tiered match pill, title, company · City · age · source, one ✓ match and one ⚠ gap, next-step chip, small Skip/Snooze buttons. Swipe and Undo as now.
- Filters become a chip row: band (Apply · Review · All), plus role-family and city chips that open their menus. Same query parameters as now.
- Mac: the same data as a restyled table.

### Job detail (`/applications/{id}`)
- **Header:** back link, title, company · location · source · age, status pill, Open posting.
- **Decision block:** match ring (score, tier colour, label Strong/Good/Weak match). Factor bars show each `breakdown` value against its rubric `max`: role fit 30, experience 25, skills 20, company 15, location & pay 10. Two lists: "Why you match" (✓ matches) and "Watch out" (⚠ gaps).
- **Next-step bar:** four steps, ① Find contacts → ② Approve → ③ Send in Gmail → ④ Mark sent. The current step is derived from status and people:
  - drafted without people: ①
  - drafted with people: ②
  - approved: ③ (link to Gmail drafts) and ④
  - sent: done, with the follow-up / #3 actions
  
  One primary button for the current step.
- **⋯ More menu:** Skip, Snooze 3d, Applied via portal, Not interested (with block company), Undo last change, Regenerate drafts, Mark followed up.
- **Approve:** the existing unverified-email checkboxes, plus one line: "Creates Gmail drafts for <names>. Nothing is sent until you press Send in Gmail."
- **Body:**
  - Mac: two columns. Left: job description (skills highlighted) and notes. Right: People, then the Email / LinkedIn note / DM drafts.
  - Phone: tabs People · Draft · Job below the decision block, switched client-side with no reload. Default tab: People when drafted, Draft when approved, Job otherwise.
- "Add someone myself" becomes a link that reveals the existing form.
- History becomes a readable timeline ("Marked sent · 3 Oct"), at the bottom on the Mac and inside the Job tab on the phone.

### Pipeline (`/pipeline`)
- A stat strip from `queries.stats`.
- **Mac:** columns Shortlisted · Drafted · Approved · Sent · Replied · Interview · Offer, plus a collapsed "Closed" group (applied via portal, rejected). Each column has a header with a count badge; cards show title, company, tiered pill, days since last action and the next-step chip. Due follow-ups get an amber card with a "Follow up" / "Email #3" flag. The existing Move menu is styled. The board scrolls sideways if narrow.
- **Phone:** stage chips (with counts) and one list for the selected stage. It opens on Sent if any follow-up is due, else Drafted. Switching is client-side.

## Data and backend

No new routes, tables or behaviour. Template helpers only:
- `tier(score)` returns `strong` / `good` / `weak`.
- `factor_bars(breakdown, rubric)` returns `[(label, value, max, pct)]`. Factor maxima are read from `rubric.yaml` (`Rubric.dimensions`); `create_app` loads the rubric into `app.state.rubric` once. This is the only startup change.
- `next_step(app, people, drafts)` returns the current step for the job page.
- `timeline(events)` returns readable history lines.
- A sidebar/tab count helper.

The existing queries (`inbox`, `today`, `pipeline`, `stats`, `application_detail`, `card_context`) supply everything else.

## Build approach

- Work on `ui-redesign`, one page per commit, in order: tokens + fonts + shell → Today → Jobs → Job detail → Pipeline. Each commit leaves the app fully working.
- One new stylesheet (`static/ui.css`) built on tokens replaces `app.css` and `mobile.css`. `keys.js` and `swipe.js` stay; a small `tabs.js` handles the phone tabs and pipeline chips. All assets keep `asset()` fingerprinting.
- **Preview:** a second launchd agent serves the branch from a separate git worktree on port 8001. `tailscale serve --bg --https=8443 8001` exposes it at `https://delulu.tail1c97dd.ts.net:8443`. It uses the **real database**: actions there act on real applications, and Approve creates real Gmail drafts, as the user chose. `main` keeps serving :8000 unchanged. When the redesign is finalised (merge) or abandoned (delete the branch), the preview agent and worktree are removed.

## Testing

- All existing behaviour tests must stay green.
- Tests that check old markup (class names, exact strings) are updated to the new markup in the same commit, and each changed assertion is listed in the commit message.
- New tests:
  - `tier` / `factor_bars` / `next_step` / `timeline` unit tests
  - the job page renders the ring, bars, step bar and More menu
  - phone tab containers exist
  - the pipeline renders columns and stage chips
  - no external `http` stylesheet or script tags in `base.html`
- Each page is checked in the browser at 393×852 (iPhone) and 1440×900 (Mac), in light and dark mode, with no horizontal scroll at phone width.

## Rollback

- Every page is its own commit, so `git revert` of one commit undoes one page.
- Abandoning the whole redesign: stop the preview agent, remove the worktree, delete the `ui-redesign` branch. `main` is untouched throughout.
