# Hands-on testing checklist (live server)

Use this after the server is live (`https://<sub>.duckdns.org`) and the data move is done. Tick each box as you go. Each item says what you should see. **If anything doesn't match, stop and tell `manager`**: what you did, what you saw, and a screenshot if you can. Don't try to fix it on the server.

You'll need: your phone, a laptop, and a second Google account for the "roommate" tests (a spare Gmail of your own is fine). For section F, use a throwaway Google account, **never your own**.

---

## A. Owner: sign-in, your data, Settings, Admin

- [ ] **Sign in.** Open the site and tap **Continue with Google** with your own account.
  Expected: you land on **Today**, greeted by your first name. No onboarding, because your old profile was imported.
  If it fails, tell `manager`.
- [ ] **Your data came across.** Open **Jobs** and **Pipeline** and compare them with what you remember from the Mac.
  Expected: the same jobs, scores and applications. In total there are about **242 applications** and **5,487 jobs** (`manager` can show you the exact counts from the move).
  If it fails, tell `manager`.
- [ ] **Open a job you know.** Open one job from Jobs.
  Expected: the same score, job description, drafts and People as on the Mac.
  If it fails, tell `manager`.
- [ ] **The first save works.** Settings → **Profile** → change nothing → **Save profile**.
  Expected: it saves. If you get **403 "Request blocked"**, `BASE_URL` on the server doesn't exactly match the site address.
  If it fails, tell `manager`.
- [ ] **Preference preview.** Settings → **What I'm looking for** → add or remove one role or city → Save.
  Expected: before anything changes, a preview says "This hides N jobs, brings back M and skips K…". Confirm or Cancel works. Put it back the way it was afterwards.
  If it fails, tell `manager`.
- [ ] **Advanced matching.** Under the roles, open **Advanced (custom matching)**.
  Expected: your old custom role text is there, because your old setup used it. Don't press "Use the role chips instead" unless you mean to; it clears the custom text.
  If it fails, tell `manager`.
- [ ] **Resume and facts.** Settings → **Resume and facts**.
  Expected: your resume is listed, and your facts (roles, achievements, skills) are filled in and editable.
  If it fails, tell `manager`.
- [ ] **Admin page.** Go to `/admin` (it's also in the sidebar on a laptop).
  Expected: three cards, **Invites**, **Users** (you, as admin, with Outreach: on) and **Usage**, plus a **Backups** card.
  If it fails, tell `manager`.

## B. Outreach (your own account)

- [ ] **Connect Gmail.** Settings → **Account** → **Connect Gmail**.
  Expected: Google warns that the app isn't verified. Tap **Advanced → Continue**, then allow **"Manage drafts and send emails"** (tick the box if Google shows one). You're sent back to Settings, which shows your Gmail address as connected.
  If it fails, tell `manager`. ("Access blocked" means your address isn't a test user in Google Cloud.)
- [ ] **Find contacts.** Open a job with no people yet → **Find contacts**.
  Expected: "Finding contacts…" for about half a minute, then up to 3 people, each with a reason, an email status, **Copy note** and **LinkedIn ↗**.
  If it fails, tell `manager`.
- [ ] **Approve → draft in Gmail.** On a job with drafts, review them → **Approve → Gmail draft**.
  Expected: a success message, and the draft(s) appear in **Gmail → Drafts** addressed to #1 (and #2), with your resume attached. **Nothing is sent.** Delete the drafts in Gmail if this was only a test.
  If it fails, tell `manager`.
- [ ] **Reconnect flow.** In your Google account (myaccount.google.com → Security → Third-party connections), remove the app's access. Then Approve another job.
  Expected: the message "Gmail needs reconnecting" with a **Reconnect Gmail** button. Tapping it takes you through Google again and back to the same job; Approve then works.
  If it fails, tell `manager`.
- [ ] **Mark sent.** After sending a real email from Gmail yourself, tap **Mark sent** on that job.
  Expected: the job moves on in **Pipeline**, and the job page says follow-ups appear 5 days after Mark sent if there's no reply.
  If it fails, tell `manager`.
- [ ] **Email #3 after 5 days** (check back later). Five days after Mark sent with no reply:
  Expected: Pipeline shows **⚠ Email #3: <name>**, and the job page offers a follow-up to #1 and #2 or an email to #3.
  If it fails, tell `manager`.

## C. Phone

- [ ] **Add to Home Screen.** In Safari: Share → **Add to Home Screen**, then open it from the icon.
  Expected: it opens full screen like an app, without Safari's address bar, and you're still signed in.
  If it fails, tell `manager`.
- [ ] **Four tabs.** Look at the bottom bar.
  Expected: **Today, Jobs, Pipeline, Settings**, and each one opens.
  If it fails, tell `manager`.
- [ ] **Swipe and Undo.** In **Jobs**, swipe a card **left**, then tap **Undo**. Swipe another card **right**, then tap **Undo**.
  Expected: left shows "Skipped" and right shows "Snoozed 3 days", each with **Undo** for about 6 seconds. Undo puts the card back.
  If it fails, tell `manager`.
- [ ] **Daily match alerts.** From the home-screen app: Settings → **Daily match alerts** → **Turn on alerts** → allow notifications → **Send a test**.
  Expected: it says "On for this device" and a test notification arrives. (On iPhone this works only from the home-screen app, iOS 16.4 or later.)
  If it fails, tell `manager`.

## D. Roommate (use your second Google account)

- [ ] **Invite.** As yourself: `/admin` → Invites → enter the second address → **Invite**. Send yourself the site link (invites send no email).
  Expected: the address is listed under Invites, with nothing under Accepted yet.
  If it fails, tell `manager`.
- [ ] **Not invited is refused.** In a private window, sign in with a third account that wasn't invited.
  Expected: "This app is invite-only. Ask <your first name> for an invite." No account is created.
  If it fails, tell `manager`.
- [ ] **Sign in and onboard.** In a private window, sign in with the invited account.
  Expected: onboarding in 4 steps: roles → where → experience and pay → your resume. Leaving halfway and coming back resumes at the same step.
  If it fails, tell `manager`.
- [ ] **Resume step, both ways.** Upload a PDF resume.
  Expected: "Reading your resume…", then **Check what we read** with editable facts. (Also try **Enter my skills myself** once: you can type skills by hand and Finish without a resume being read.)
  If it fails, tell `manager`.
- [ ] **Finish.**
  Expected: **You're set.**, with a note that the first scores arrive with the next run, and **Go to Jobs**.
  If it fails, tell `manager`.
- [ ] **Their own jobs only.** After the next run (or a Fetch now), look at their Jobs and Pipeline.
  Expected: only jobs matched to *their* preferences, none of your applications, and none of your Pipeline.
  If it fails, tell `manager`.
- [ ] **No outreach for them.** Open one of their jobs.
  Expected: **Open job posting ↗** and **Mark applied**, with no People, no drafts, no Approve and no Find contacts. Settings has no Gmail card. Today shows "New today" and "Shortlisted" only.
  If it fails, tell `manager`.
- [ ] **Mark applied.** Tap **Mark applied** on one of their jobs.
  Expected: it moves to their Pipeline as applied.
  If it fails, tell `manager`.
- [ ] **Turn outreach on for them.** First add their Gmail address as a **test user** in Google Cloud (OAuth consent screen). Then, as yourself: `/admin` → Users → **Turn outreach on** for them.
  Expected: the admin page reminds you of the two steps. On their side, Settings → Account now shows **Connect Gmail**, and their job pages get People and drafts. (Turn it back off afterwards if they shouldn't have it yet.)
  If it fails, tell `manager`.

## E. Background jobs

- [ ] **The daily run.** The morning after going live, check Today after **11:15 IST**.
  Expected: new jobs under "New today" (if any were posted), and the run in Admin's usage. If Healthchecks.io is set up, it got a ping.
  If it fails, tell `manager`.
- [ ] **Fetch now, and its limit.** On Today, tap **Fetch now**, then tap it again straight away.
  Expected: "Queued, starts in a few minutes", then "Running since <time>", then new jobs. A second tap within 2 hours says "Next possible at <time>". After the day's limit it says "Fetch now is used up for today".
  If it fails, tell `manager`.
- [ ] **Nightly backup.** The day after going live: `/admin` → **Backups**.
  Expected: a row for the day with a size and **Off-site** filled in (not "Not uploaded"). In Backblaze B2 the bucket has `daily/jobseeker-<date>.tar.gz.enc`.
  If it fails, tell `manager`.
- [ ] **Uptime check.** Open `https://<sub>.duckdns.org/healthz` in a browser, and check the UptimeRobot dashboard.
  Expected: the page answers (status 200), and UptimeRobot shows the site **Up**.
  If it fails, tell `manager`.

## F. Account (export: any account; delete: a test account only)

- [ ] **Download my data.** Settings → Account → **Download my data**.
  Expected: a zip with `profile.json` (preferences and facts), `applications.json` (with their drafts and contacts), `job_verdicts.csv`, `blocklist.json`, `gmail.json` (address and connection date only, never a token) and `resume.pdf`.
  If it fails, tell `manager`.
- [ ] **Delete account (TEST ACCOUNT ONLY).** Sign in as the throwaway test account (invite it first) → Settings → Account → **Delete my account** → type its email → confirm.
  Expected: it's signed out and can't get back in without a new invite. In `/admin` it's gone from Users, while its usage still counts in the totals. **Your own account's button is disabled** ("You're the only admin…"), which is correct.
  If it fails, tell `manager`.

---

When everything is ticked, tell `manager` "testing checklist passed", with the date. Anything left unticked goes in the same message.
