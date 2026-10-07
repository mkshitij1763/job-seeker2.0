# job-seeker2.0: mobile access (design)

**Date:** 2026-10-07
**Status:** Sections 1–3 approved in brainstorming. Revised after the user's review: designed for the iPhone 15, plus swipe gestures (§4.7) and interaction polish (§4.8) from a ui-ux-pro-max review. Sections 1 and 3 (access and setup) are already done and committed (`7b609b3`). This spec records them and specifies Section 2, the phone layout, which is the remaining build. Awaiting the user's review of this written spec.
**Builds on:** `2026-10-07-job-seeker-mvp-design.md` and `2026-10-07-job-discovery-design.md`.

## 1. Goal

The user can work through applications from an iPhone whenever the MacBook is awake (normally 11:00–23:59). That covers:
- reading a job's description, score and drafts,
- editing drafts,
- finding and entering the contact,
- approving (which creates a Gmail draft),
- triaging and updating the pipeline.

Everything that works on the laptop keeps working the same way there.

**Success criteria:**
1. At iPhone width (393 px, iPhone 15), no page needs horizontal scrolling or zooming to read or tap anything.
2. The phone flow is: inbox → job → read the draft → enter the contact → **Approve**. Approve stays one tap away while reading, with no hunting through the page.
3. The desktop layout and every existing route behave as before. All existing tests pass unchanged, apart from the copy-button change in §4.4.
4. The dashboard is still reachable only from the user's own Tailscale devices, and the app still binds to `127.0.0.1`.

## 2. Access and always-on (done: Sections 1 and 3)

- **Tailscale Serve:** `tailscale serve --bg 8000` publishes the dashboard at `https://delulu.tail1c97dd.ts.net` with an automatic HTTPS certificate. It is reachable only from devices signed in to the user's tailnet: the MacBook `delulu` and `iphone-15`. The app still binds to `127.0.0.1:8000` (`cli.py`, enforced by `tests/test_safety.py`).
- **Always-on:** launchd agent `com.kshitij.jobseeker.web` runs `jobseeker serve` at login, with `KeepAlive` set so it restarts if it stops. Logs go to `data/logs/web.log` and `data/logs/web.err.log`. Both agents are installed by `scripts/install_launchd.sh`.
- **Daily run:** moved from 07:30 to **11:15**, when the Mac is normally open. launchd runs a missed run on wake.
- **No app-level login.** Access control is the tailnet. A person holding the unlocked phone can approve drafts, which is the same exposure as the Gmail app. Nothing is ever sent automatically.
- **Undo:** `tailscale serve --bg off`, and uninstall Tailscale.

## 3. Approach

**One responsive dashboard, not separate mobile pages.** The existing templates gain a phone layout through CSS media queries, plus small markup changes where CSS alone can't reorder or fold content.

**Target device: iPhone 15.**
- Viewport: 393 × 852 CSS px, device pixel ratio 3.
- Safe areas: top inset about 59 px (Dynamic Island), bottom inset 34 px (home indicator).
- It runs in Safari, and as a full-screen home-screen web app.
- Every check in §5 runs at 393 × 852.

**Width rule:**
- **Phone:** `max-width: 640px`. This also covers other phones.
- **Touch:** `hover: none`, used only to hide keyboard hints.

**JavaScript:** a little is added to `static/keys.js`, with no new dependency:
- on phone width, close the `<details>` sections that are open by default on desktop (filters, JD, empty pipeline columns);
- show "Copied ✓" feedback after a copy.

## 4. Phone layout (the build)

### 4.1 Every page (`base.html`, `app.css`)

- **Header:** stays sticky and compact. The brand shrinks to "Job Seeker"; **Inbox** and **Pipeline** links; the "last run: N errors" badge stays, but shows only the count.
- **Flash messages** sit at the top of the content and span the full width.
- **Touch targets:**
  - Buttons, inputs, selects and summary rows are at least **44 px** tall.
  - Inputs and textareas use **16 px** text, which stops iOS Safari from zooming when a field is focused.
- **Keyboard hint:** the "j/k move · enter open …" text is hidden on touch devices.
- **Home-screen app:**
  - `<link rel="manifest" href="/static/manifest.webmanifest">` with `name`/`short_name` "Job Seeker", `display: standalone`, `start_url: "/"`, and theme and background colours from the existing palette.
  - `<link rel="apple-touch-icon" href="/static/icon-180.png">`, a 180×180 PNG generated once and committed.
  - `<meta name="apple-mobile-web-app-capable" content="yes">` and `<meta name="theme-color" …>`.
  - Viewport: `width=device-width, initial-scale=1, viewport-fit=cover`.
  - Safe-area padding (`env(safe-area-inset-bottom)`) for the sticky action bar.

### 4.2 Inbox (`inbox.html`)

- **Rows become cards.** At phone width the table is hidden and a card list (`<ul class="cards">`, rendered from the same rows) is shown instead. On desktop the list is hidden. A swipe needs a moving card in front of a fixed coloured panel, which table rows can't provide. Each card is `<li class="swipe-card" data-app-id data-swipe>`, holding an `aria-hidden` `.swipe-bg` panel and a `.card-body`. Card layout:
  - **Line 1:** score badge (the existing hi/mid/lo colours) and the title as a link. The whole card is tappable through the title link's enlarged hit area.
  - **Line 2:** company · city · age · source.
  - **Line 3:** the role-family tag, the status tag, and up to two ✓ matches and one ✗ gap.
  - **Line 4:** **Skip** and **Snooze**, each half the card width.
- **Filters** go inside `<details class="filters-box" open><summary>Filters</summary>…</details>`. On desktop the summary is hidden and the box is always open, so it looks the same as today. On phone width `keys.js` removes `open`, so the filters fold behind one "Filters" row.
- **Empty state:** unchanged.

### 4.3 Job page (`application.html`)

The markup is split into blocks so the phone can reorder them with CSS `order` on a single-column flex container. On desktop the two-column grid stays exactly as today.

**Blocks:**
- **`head`:** title, meta line, "Open posting ↗", status tag, and the score box.
- **`drafts`:** the drafts card.
- **`contact`:** the contact card.
- **`jd`:** a `<details class="jd-box" open>` whose summary is "Job description" plus the matched-skill count. It holds the highlighted JD. On phone width it starts closed.
- **`notes`, `history`:** history becomes a `<details>`, closed on phone width.
- **`actions`:** the action buttons.

**Phone order:** head → drafts → contact → jd → notes → history, with **actions** pinned as a sticky bottom bar.

**Desktop order:** unchanged. Left column: head, jd. Right column: contact, drafts, actions, notes, history.

**Sticky action bar (phone width only):**
- `position: sticky; bottom: 0`, with a background and a top border, and safe-area padding.
- **Approve → Gmail draft** is the full-width primary button. When the contact's email is unverified, the "Email is unverified, draft anyway" checkbox sits directly above it in the bar. The existing "a Gmail draft already exists" warning shows in the bar too.
- **More:** a `<details class="more">` holds the other actions:
  - Mark sent, Applied via portal, Skip, Snooze 3d;
  - Mark followed up, when the status is `sent`;
  - Not interested, with "also block company";
  - Regenerate all;
  - Open Gmail drafts ↗, when a draft id exists.
  
  On desktop the More summary is hidden and its contents are always shown, so the actions card looks as it does today.

**Drafts card:**
- The email `<details>` is open; the LinkedIn note and DM are closed. This is unchanged.
- Textareas are full width.
- The email textarea gets more rows on phone width.
- Word and character counters are unchanged.

### 4.4 Copy and Open LinkedIn (both layouts)

iOS Safari blocks a `window.open` that follows an asynchronous clipboard write. The single "Copy & open LinkedIn" button therefore becomes two controls:
- **Copy note:** copies the note, then shows "Copied ✓".
- **Open LinkedIn ↗:** a plain link with `target="_blank"` to the contact's LinkedIn URL, or the people-search URL if there is none. On iPhone this opens the LinkedIn app via universal links.

The `data-open` behaviour is removed from `keys.js`. The DM keeps its single **Copy** button.

### 4.5 Contact card

- **Field types:** the email input keeps `type="email"`, and the LinkedIn URL input becomes `type="url"`. Both get `autocapitalize="off"` and `autocorrect="off"`, so the phone keyboard doesn't change what's typed.
- **Layout:** at phone width the two-column field grid becomes a single column.

### 4.6 Pipeline (`pipeline.html`)

- **Columns become collapsible sections.** Each column becomes `<details class="col" open data-count="N">` with the summary "Status · count". Every column is rendered open, because the server doesn't know the screen width.
  - **Desktop:** the summary is styled like today's column heading, so the board looks unchanged.
  - **Phone:** columns stack vertically, and `keys.js` closes those with `data-count="0"`.
- **Phone width:** the kanban grid switches to a single vertical column with no horizontal scroll. Cards are full width. The **Move** select and button get 44 px targets. The **follow up** badge is unchanged.
- **Stats strip:** wraps into two columns of tiles at phone width.

### 4.7 Swipe gestures and Undo (inbox cards only)

**Gestures**
- **Swipe left** on an inbox card: **Skip**. A red panel saying "Skip" shows behind the card.
- **Swipe right**: **Snooze 3 days**. An amber panel saying "Snooze".
- Both reuse the existing `POST /applications/{id}/status` (`status=skipped`) and `POST /applications/{id}/snooze` routes.

**Recognising a swipe**
- Cards use `touch-action: pan-y`, so vertical scrolling stays native.
- A gesture locks horizontal only after it has moved 10 px, with |dx| > 1.5 × |dy|. Otherwise it is a scroll.
- It commits when |dx| ≥ 35 % of the card width, or a fast flick (≥ 0.5 px/ms over at least 40 px). Below that, the card springs back.
- Touches that start within **24 px of the left screen edge** are ignored, so iOS Safari's edge-swipe "back" gesture keeps working.
- Only one gesture region exists: inbox cards. The job page and pipeline have no swipes.

**After a swipe commits**
1. The card slides out: `transform` only, 180 ms ease-out. With Reduce Motion on, it is removed instantly.
2. The action is sent with `fetch` and the result read from the final redirected URL: `?msg=` means success, `?err=` means failure.
3. **Success:** a toast says "Skipped · **Undo**" or "Snoozed 3 days · **Undo**" for 6 s.
4. **Failure:** the card slides back and the toast shows the server's error text.
5. **No connection:** the same, with "Couldn't reach the Mac".

**Undo**
- A new route, `POST /applications/{id}/undo`, reverts the application's **most recent status change**:
  - It applies only if the current status still equals that event's `to`.
  - A snooze is undone by restoring `snoozed_from` and clearing `snoozed_until`.
  - Undo is **not** allowed after `not_interested`, because blocklist entries were created. The change is then refused with a message.
  - It writes an `undo` event (`{"from", "to"}`) and redirects with `?msg=` or `?err=`. It bypasses `can_transition`, because it restores a state the app was already in.
- The toast's Undo calls this route, then reloads the inbox so the card comes back.
- The same route powers an **"Undo last change"** button on the job page, in both layouts. It is shown when the latest event is a reversible status change, and lives in the More menu on phones.

**Accessibility:** every swipe action keeps its visible button on the card (Skip, Snooze), so swiping is never the only way (WCAG 2.2, 2.5.7 Dragging Movements).

**Code structure:** `static/swipe.js` holds three pure functions, loaded in the browser as `window.JobSwipe` and in Node via `module.exports`:
- `decide(start, current) → {mode: "none"|"scroll"|"swipe"}`: is the gesture a scroll or a swipe?
- `release(start, end, cardWidth) → "skip"|"snooze"|null`: commit or snap back?
- `parseOutcome(finalUrl, ok, status) → {ok, message}`: read the server's redirect.

The browser wiring (touch events, the `.card-body` transform, fetch, toast) is a thin layer around them.

### 4.8 Interaction polish (from the ui-ux-pro-max checklist)

- **Pressed feedback:** every button, link-button and card shows a pressed state on `:active` within about 100 ms: `opacity: .7` plus `transform: scale(.98)`. Bounds don't move, so the layout doesn't jitter.
- **Toast:** a single toast region with `role="status" aria-live="polite"`, sitting above the sticky bar and the home indicator. It is reused for swipe results. Page-load flash messages keep the existing banner.
- **Reduced motion:** under `@media (prefers-reduced-motion: reduce)`, transitions and transforms are off; swipes act on release without animation.
- **Safe areas:**
  - The header uses `padding-top: env(safe-area-inset-top)` in standalone mode.
  - The sticky action bar and toast use `env(safe-area-inset-bottom)`.
  - Page content gets bottom padding equal to the bar height, so nothing hides behind it.
- **Contrast:** the swipe panels use `--err` and `--warn` with text at ≥ 4.5:1, checked separately in light and dark mode. New colours are added only as tokens in `:root` and its dark override.
- **Labels:** buttons keep their visible text labels. The More `<summary>` has `aria-label="More actions"`. Swipe panels are `aria-hidden` (they're decorative; the buttons carry the meaning).
- **Focus:** sticky UI never covers the focused field. When a textarea is focused on a phone, the sticky bar hides.

**Considered and not used:** the separately suggested `mblode/agent-skills` ui-animation skill would mean installing third-party code. ui-ux-pro-max, already installed, covers the motion rules this needs: timing, exit faster than enter, reduced motion.

## 5. Testing

**Automated** (pytest, no network). New file `tests/test_web_mobile.py`. Each test checks real rendered markup:
- `base.html` includes the manifest link, the apple-touch-icon, `viewport-fit=cover` and the theme-color meta.
- `/static/manifest.webmanifest` is served with JSON containing `"display": "standalone"` and `"start_url": "/"`.
- `/static/icon-180.png` is served as a PNG that is 180×180.
- The inbox wraps its filters in `details.filters-box`.
- The job page renders, with the expected class hooks:
  - the blocks `head`, `drafts`, `contact`, `jd-box`, `history` and `actions`;
  - the `details.more` menu, containing Mark sent, Skip and Not interested;
  - Approve outside `details.more`.
- The job page renders **Copy note** and a separate **Open LinkedIn** link pointing to the people-search URL when no contact URL exists. There is no `data-open` attribute.
- The pipeline renders each status as an open `details.col` with the right `data-count`, including `data-count="0"` for empty columns.
- **Undo** (`tests/test_web_undo.py`):
  - reverts skipped → drafted;
  - reverts a snooze, restoring `snoozed_from` and clearing `snoozed_until`;
  - refuses after `not_interested`;
  - refuses when the status has moved on since the event;
  - writes an `undo` event;
  - the job page shows "Undo last change" only when it applies.
- **Swipe logic** (`tests/js/swipe.test.mjs`, run by `node --test` from `tests/test_js.py`, skipped if Node is missing). Cases:
  - a vertical move is a scroll;
  - a horizontal move past the threshold commits skip or snooze;
  - a short move snaps back;
  - a fast flick commits;
  - an edge start (< 24 px) is ignored;
  - the direction lock happens at 10 px.
- **Inbox cards** carry `data-app-id` plus the Skip and Snooze buttons, and the page has a `role="status"` toast region.
- All existing web tests pass. The copy-button assertion in an existing test, if any, is updated as part of §4.4.

**Visual check (before claiming done):** use Chrome DevTools device emulation at **393×852, DPR 3, touch, iPhone user agent** (iPhone 15) against the live dashboard (`http://127.0.0.1:8000`). For the inbox, a job page and the pipeline:
- take screenshots;
- confirm there is no horizontal scroll (`document.documentElement.scrollWidth <= innerWidth`);
- confirm the sticky bar is visible at the bottom of the job page;
- confirm the JD is closed and the filters are folded.

Then:
- run a synthetic touch swipe on an inbox card, in emulation, against a **test copy of the database**. Confirm the card leaves, the toast shows Undo, and Undo brings the card back.
- re-check at **1280 px** to confirm the desktop layout is unchanged.
- work through the ui-ux-pro-max pre-delivery checklist items that apply (touch targets, pressed states, safe areas, contrast in both themes, reduced motion, gesture conflicts, alternatives to swipes).

**No real Gmail draft is created during verification.** Approve is covered by the existing route tests with the fake Gmail. The user does the first real phone approval themselves.

**On the device:** after the build, the user opens `https://delulu.tail1c97dd.ts.net` on the iPhone and adds it to the home screen.

## 6. Out of scope

- An app-level login or PIN. Access control is the tailnet (§2).
- Offline use, push notifications, background refresh.
- A native app.
- Swipes outside the inbox, such as on the job page or pipeline.
- Haptics (not available to web apps on iOS Safari).
- Keeping the Mac awake while the lid is closed, or hosting in the cloud. The dashboard is reachable only while the Mac is awake.
- Redesigning the desktop layout.
