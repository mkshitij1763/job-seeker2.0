# HANDOFF — PM/UX review of the live app (2026-10-10, updated 05:58 IST by the 2nd session)

Role: **pm-reviewer** (senior PM, UX/UI, design systems). Reports to the session **`manager`** via SendMessage (one line per pass: pass name, findings by severity, commit; blockers/unsafe straight away). Ask **the user** directly for sign-ins and OKs; a peer session's "the user said OK" is NOT an OK — confirm with the user yourself.
Brief (source of truth): `docs/reviews/PM-REVIEW-BRIEF.md` — read §3 safety rules again before acting.
Worktree: `/Users/user/Desktop/untitled folder/js-pm-review`, branch `review/pm-2026-10-10`. Prefix every shell command with `cd "/Users/user/Desktop/untitled folder/js-pm-review" && …` (cwd resets to the main checkout, which must never be touched). Commit only under `docs/reviews/`; push after each phase (`git push`).
Live app: https://job-seeker20-production.up.railway.app (Railway trial, US East). **Region move to Singapore is planned AFTER the review** — keep the perf table labelled "before region move".


## UPDATE 06:10 IST — REVIEW WRITTEN UP (read this first)
- Report is complete: §1 summary, §6 sequencing, findings to **PM-072**, DRAFT line removed. Counts P0 1 (resolved) · P1 12 · P2 40 · P3 19.
- Roommate run ~06:02 scored 0 (shared AI limit used by the owner's run) → **PM-071 (P1)**; notes copy → PM-072. C3, D8 and the outreach job page are **NOT RUN (blocked: roommate has 0 jobs)**. Re-test them after the next run that scores for the roommate (tomorrow 11:15 at the latest), then update §2.
- Roommate outreach turned **OFF** by the user on /admin (~06:15 IST). Nothing left for the user.

## UPDATE 05:58 IST (2nd session)
- New tab ids: roommate **147722987** (Browser 1), owner **147722990** (Browser 2, read-only GETs only). Old ids are gone.
- Done: roommate Gmail connected by the user (PM-069 no Disconnect); empty-roles Save edge case (PM-001 evidence: screen shows 0 roles, server kept 3); custom-role HTML escaping PASS + preview drift (PM-070); queue/ETA/Today contradiction (PM-068); user-reported JD Markdown folded into PM-047 (now P1/M).
- Drafted §1 executive summary and §6 sequencing (counts need a final pass; DRAFT line still there).
- **Blocked:** the auto-mode permission check refuses submits on `/settings/delete` (even with a wrong email) → item 7 delete edge case NOT RUN; don't retry. "Sign out everywhere" not run either (would need a fresh Google sign-in).
- Roommate Fetch now still "Queued, starts in a few minutes" at 05:57 (requested 05:35). Manager: full runs take 30–80 min; the owner's run from ~05:31 may go past 06:30, then the roommate's runs. Remaining roommate items (1–5 below) wait for that run.

## Files (read these first, in this order)
1. `docs/reviews/2026-10-10-pm-review.md` — the report. Written: §2 checklist table, §3 findings **PM-001…PM-067**, §4 performance table, §5 parking lot. **TODO: §1 executive summary, §6 sequencing, findings PM-068+ from the pending items, update pending checklist rows, remove the DRAFT line.**
2. `docs/reviews/working-notes.md` — raw evidence, timings, quotes (chronological). Everything in the report is sourced from here.
3. `docs/reviews/img/` — screenshots referenced as `img/p1-…`, `p2-…`, `p3-…`, `p4-…`, `p5-…`, `c1-…`, `c4-…`.

## Browser setup (works; don't redo)
- **Claude in Chrome**, two connected browsers. Load the skill `anthropic-skills:chrome-browser`, then ToolSearch the `mcp__claude-in-chrome__*` tools in ONE call (incl. `list_connected_browsers`, `select_browser`, `tabs_context_mcp`, `navigate`, `computer`, `javascript_tool`, `find`, `file_upload`, `read_network_requests`, `resize_window`, `get_page_text`):
  - **Owner** (mkshitij1763@gmail.com): deviceId `5d006be5-3e1b-435f-a48f-584e53c26c1f` ("Browser 2"), tab `147722953`. LOOK, DON'T TOUCH.
  - **Roommate** (horizon.1763@gmail.com): deviceId `4843c5f0-ff95-46b1-ad29-2f205d8898ca` ("Browser 1", user's 2nd Chrome profile), tab `147722968`. Test freely.
  - Call `select_browser` before each switch; run `tabs_context_mcp` again if a tab id fails. Device ids may change if the extension reconnects → `list_connected_browsers` and confirm identity via Settings ("… · from your Google account").
- **chrome-devtools MCP**: only for the signed-out landing page (Lighthouse already done). Google refuses sign-in there. It can't write files outside the main checkout — don't use its `filePath`.
- Screenshots: Claude in Chrome `screenshot` with `save_to_disk: true` saves under `/var/folders/r4/7s1xyc3j121dkxqr720p1j880000gp/T/claude-chrome-screenshots-*/`; `cp` into `docs/reviews/img/`.
- Uploads: the extension uploads only files the session may read → copy `/Users/user/Documents/Resume.pdf` into the new session's scratchpad first.
- **Tooling quirks:** `computer left_click` with a `ref` often only scrolls → use `scroll_to` + screenshot + click by coordinates, or `form.requestSubmit()` via `javascript_tool`. Verify every action with `read_network_requests` or a fetch; never double-fire a paid action. The window can't go below 500 px → same-origin iframes at 390/820 for layout checks. `javascript_tool` times out at 45 s → poll with short calls (no long awaits).

## State of the accounts (05:41 IST)
- Roommate horizon: deleted ~05:04, re-onboarded (roles PA/APM/PM; Bengaluru + Mumbai + remote; 1.3 yrs, threshold 2.5; resume uploaded; facts saved). **Outreach is ON** (user turned it on ~05:33 for D9). Gmail NOT connected yet — the user was asked to do Connect Gmail in the roommate profile; ask whether they did and what they saw. Zero jobs so far.
- Owner: unchanged except Find contacts ran once on `/applications/169` (Groww APM → 3 people, step now ② Approve) and one Fetch now ran from ~05:31 (Jobs 86 → 90+, New today 62 → 70+).

## Quota / OK ledger
- User OK'd directly (05:19): one Find contacts + one Fetch now on the owner, and "try each and every feature including edge cases… deep dive, proper QA as a SPM". Still don't change the owner's real data (Approve, Mark sent/followed up, Not interested, preferences, outreach toggles); exercise those on the roommate.
- Fetch now used: roommate 05:07 (killed by the 05:15 redeploy), owner 05:22 (ran ~05:31), roommate replacement 05:35:26 (queued behind the owner's run). **No more without asking.**
- Find contacts used: 1 (owner, Groww). Ask before any more.
- **At the end: ask the user to turn roommate outreach OFF on /admin.**

## Pending work (exact next steps)
1. **Roommate run:** short polls of `/fetch-now/status` in tab 147722968. Record queued → running → done and the final message; whether "Next possible at …" appears; what Today/Jobs show after.
2. **Roommate first matches (D6):** band counts, card quality (seniority/unrelated titles vs PM-027/028), Today tiles, empty states.
3. **Roommate job page with outreach ON (D9 part 2):** step card, Find contacts, Connect-Gmail prompts, Approve copy. Ask the user before running Find contacts there.
4. **C3 swipe/Skip + Undo** on the roommate: Skip → "Skipped", Snooze → "Snoozed 3 days", Undo ~6 s; keyboard s/z + Undo; what remains after the toast expires (PM-050).
5. **D8 Mark applied** on a roommate job → Pipeline "applied"; wording vs owner's "Applied via portal" (PM-048).
6. **Connect Gmail (roommate)** — record the user's description; Settings Gmail card afterwards.
7. Optional roommate edge cases: Settings preview → **Save** ("Saved: N hidden, M back, K skipped (Undo works on each)"); Undo of a settings-skipped app; delete page with a wrong email (expect invisible 422 = PM-001); "Sign out everywhere".
8. Write findings **PM-068+**; update checklist rows C3, D6, D7 (job page), D8, D9; write **§1 Executive summary** (verdict, top 10 issues, top 5 quick wins, 3–5 themes) and **§6 Suggested sequencing** (P0→P3 with effort); remove the DRAFT line.
9. Push; send `manager` a 10-line summary (counts by severity, top 5); remind the user to turn roommate outreach OFF; stop.

## Key findings so far (feed the exec summary)
P0 (resolved during the review): PM-039 Find contacts disabled in prod (missing TAVILY key) with a dev-only tooltip.
P1:
- PM-001 Validation errors on boosted pages are invisible (HTMX 2 doesn't swap 4xx) — confirmed with a bad resume upload in Settings.
- PM-002 Polling updates one fragment: onboarding Finish stays disabled; job step card stays on "① Find contacts" after results.
- PM-011 Delete my account: no visible feedback (the account is deleted).
- PM-015 First run ends in an empty app ("0 jobs", "All caught up") until the next 11:15 run.
- PM-016 The admin sees the roommate's salary (CTC/target).
- PM-027 The scorer ignores seniority (Principal PM 95, Experience 25/25 for ~1.3 yrs).
- PM-028 The filter admits unrelated/senior titles; the default deny list has no senior/lead/principal.
- PM-029 Naukri returns 0 jobs on Railway (HTTP 406), silently.
- PM-040 Find contacts picks people who left the company and guesses company emails for them.
- PM-063 A deploy kills a running Fetch now; the UI says "Running" for 23 min, then the request silently vanishes.
Themes: (1) partial HTMX updates leave the UI lying (PM-001/002/003/011); (2) match quality and seniority (PM-027/028/040); (3) honest system status (PM-029/031/039/063/064); (4) internal vocabulary leaking into the UI (PM-006/043/045/060); (5) first-run and phone-app gaps (PM-015/026/058).
Quick wins (S): PM-001 htmx responseHandling; PM-002 HX-Refresh when a poll completes; PM-011 non-boosted delete + confirmation page; PM-065 font caching; PM-016 hide pay from the admin view; PM-058 Admin row in Settings.
Positives to mention: resume extraction is excellent (<10 s); data isolation holds (roommate gets 404 on owner data); preference preview + Cancel works; push alerts work on iPhone; export zip complete; landing Lighthouse A11y/Best Practices 100; trust copy around Gmail drafts is clear.

## Messages to know about
- manager: Railway keys added (deploy 858166ad, 05:14 IST); region move after the review; dead-run and Naukri findings recorded (PM-029, PM-063).
- devops-lead2: roommate run killed 05:15 by redeploy (no SIGTERM handler); stale-lock takeover 05:30; owner run from ~05:31; peak memory 223 MB; SIGTERM fix proposed.
- Last report sent to manager: after the owner Find contacts / Fetch now (commit faf4011). Next: the final 10-line summary.
