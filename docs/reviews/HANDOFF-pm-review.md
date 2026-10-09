# HANDOFF — PM/UX review of the live app (2026-10-10)

Role: **pm-reviewer**, reporting to `manager`. Brief: `docs/reviews/PM-REVIEW-BRIEF.md` (the source of truth; §3 safety rules are firm).
Worktree: `/Users/user/Desktop/untitled folder/js-pm-review`, branch `review/pm-2026-10-10`. Commit only under `docs/reviews/`.
Live app: https://job-seeker20-production.up.railway.app · Report: `docs/reviews/2026-10-10-pm-review.md` (not started).

## Status
| Phase | State | Notes |
|---|---|---|
| §1 Reading | done | README, HANDOFF §1–3 + §8, TESTING-CHECKLIST, specs (UI redesign in full; mu-* onboarding/landing/Fetch-now sections) |
| Sign-in plan agreed with user | done | Owner: user's main Chrome profile via Claude in Chrome. Roommate: a **second Chrome profile** with Claude in Chrome (switch with select_browser). The chrome-devtools automation browser was dropped: Google refuses sign-in there ("This browser or app may not be secure"). |
| Pass 1 — roommate first-time journey | in progress | deleted + re-invited + onboarded (05:00–05:06 IST); first-run empty state reviewed; Fetch now queued 05:07 IST — check result, then review first matches + daily use |
| Pass 2 — owner power-user journey | not started | look, don't touch |
| Pass 3 — testing checklist | not started | |
| Pass 4 — heuristic audit (390 / 820 / 1440, dark) | not started | |
| Pass 5 — performance & reliability | baseline done | 'before region move' table in working-notes.md (region move to Singapore is planned AFTER the review) |

Findings so far (raw, in working-notes.md, not yet numbered): ~5 P1, ~12 P2, many P3.

## Quota/OK ledger (max 1 each for the whole review)
- Find contacts: not used.
- Fetch now: **USED** on roommate 05:07 IST 2026-10-10 (user OK). None left.
- Roommate delete + re-invite: **DONE 2026-10-10** (OK'd by user) (delete in roommate Settings → owner re-invites on /admin → user signs in → upload /Users/user/Documents/Resume.pdf).
- Roommate outreach ON: not requested.

## Early notes (to verify live)
- Docs say the host is a GCP e2-micro + DuckDNS; the live app is on Railway (trial, 0.5 GB, US). TESTING-CHECKLIST mixes both (`<sub>.duckdns.org` and a Railway backup step). Copy/docs consistency finding candidate.

## Tooling notes
- chrome-devtools MCP can only write files inside the main checkout (not allowed). Screenshots taken inline land in the session's `tool-results/` folder; copy them to `docs/reviews/img/` with `cp`. Use it only for the signed-out landing page (Lighthouse, screenshots).

## Exact next step
Roommate profile (deviceId 4843c5f0…): check /today for the Fetch now result (queued 05:07 IST), record queued→running→done times, then review first matches (Jobs, a Job detail with outreach off, Mark applied on one job, Pipeline). Meanwhile/after: Pass 2 owner (deviceId 5d006be5…, look don't touch).
