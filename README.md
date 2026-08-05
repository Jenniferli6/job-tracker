# Job Posting Tracker

Polls your target companies' job boards on a schedule and emails/Slacks you
when a new role goes up.

## How it works

- `companies.json` — your list of target companies
- `poller.py` — fetches current open roles for each company, diffs against
  `state.json`, notifies you of anything new, and logs it to `jobs_log.json`
- `.github/workflows/poll.yml` — runs `poller.py` automatically every day
  via GitHub Actions (free for public/private repos within normal limits)
- `docs/index.html` — a browsable dashboard of everything found, hosted
  free via GitHub Pages

## 1. Fill in `companies.json`

**If you have a big list (like the 195-company target list), don't do this
by hand.** Use the auto-discovery script:

```bash
pip install requests pandas openpyxl
python discover_ats.py        # tests each company against Greenhouse/Lever/Ashby APIs
python merge_discovered.py    # writes the final companies.json
```

This needs to run somewhere with normal internet access (your laptop, or a
one-off run in GitHub Codespaces/Actions) — it queries the live ATS APIs
directly for each company, trying common slug variations of the company
name, and keeps whichever one responds. Takes a few minutes for ~200
companies. It prints progress as it goes and flags anything it couldn't
match automatically (companies on custom/non-standard career sites, or
whose slug doesn't match any name variant it tried) with `"ats": "TODO"`
in `companies.json` — go check those by hand and either fill in the right
`ats`+`slug`, or use `"ats": "custom"` with a `"url"`.

`company_names.json` already has your 195-company list extracted from your
spreadsheet (name + category), ready for `discover_ats.py` to use.

For a smaller/manual list, or to fix flagged companies, figure out the ATS
and slug from the company's careers page URL:

| ATS | Careers URL pattern | slug is... |
|---|---|---|
| Greenhouse | `boards.greenhouse.io/{slug}` or `job-boards.greenhouse.io/{slug}` | `{slug}` |
| Lever | `jobs.lever.co/{slug}` | `{slug}` |
| Ashby | `jobs.ashbyhq.com/{slug}` | `{slug}` |

Fastest way to check: open the company's careers page, and look at the URL
it redirects to, or view page source and search for "greenhouse", "lever",
or "ashby".

If a company doesn't use one of these three, use `"ats": "custom"` with a
`"url"` field pointing at their careers page. You'll get a "something
changed" alert instead of specific new-role detail — good enough to know
when to go look.

## 2. Set up notifications

Pick one or both:

**Email** — add these as repo secrets (Settings → Secrets and variables →
Actions → New repository secret):
- `SMTP_HOST`, `SMTP_PORT` (e.g. 587), `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`
- For Gmail: use an [App Password](https://myaccount.google.com/apppasswords)
  (not your regular password), host `smtp.gmail.com`, port `587`.

**Slack** — add a repo secret `SLACK_WEBHOOK_URL` with an
[incoming webhook URL](https://api.slack.com/messaging/webhooks) for a
channel or DM to yourself.

If neither is configured, results just print to the GitHub Actions log —
useful for testing before you wire up notifications.

## 3. Deploy

1. Push this folder to a new GitHub repo (private is fine).
2. Add your secrets (step 2 above).
3. The workflow runs daily at 13:00 UTC. Adjust the cron schedule in
   `.github/workflows/poll.yml` if you want a different time.
4. To test immediately: go to the repo's **Actions** tab → "Job Alert
   Poller" → **Run workflow**.

Note: the **first run** for each company just records a baseline — it
won't alert you on that run, since every currently-open role would look
"new". You'll start getting alerts starting from the second run onward.

## 4. Turn on the dashboard (GitHub Pages)

1. In your repo, go to **Settings → Pages**.
2. Under "Build and deployment" → Source, choose **Deploy from a branch**.
3. Branch: `main`, folder: **`/docs`**. Save.
4. GitHub gives you a URL like `https://<your-username>.github.io/<repo-name>/`
   — that's your dashboard, live within a minute or two.

**Important if your repo is private:** GitHub Pages on a private repo
requires GitHub Pro (or Team/Enterprise) — free-tier accounts can only
publish Pages sites from **public** repos. If you want to keep the repo
private and are on the free plan, either upgrade, or skip Pages and just
open `docs/index.html` locally in a browser after pulling the latest
`docs/jobs_log.json` from the repo (`git pull`) — same dashboard, just not
hosted online.

The dashboard reads `docs/jobs_log.json`, which the workflow updates and
commits every run alongside `state.json`. It's a rolling log (newest
first, capped at the most recent 2000 postings) with search and a company
filter, so it stays usable even once you've been running this a while.

## Running locally (optional, for testing)

```bash
pip install requests
python poller.py
```

Set the same environment variables (`SMTP_HOST`, etc.) in your shell if you
want to test notifications locally.

## 5. Application automation (optional, local only)

`apply.py` works through the dashboard's job list (both "Target Company
Jobs" and "Interested Roles") in batches, newest first, and semi-automates
applying: it opens a real visible browser, attaches your resume, fills in
whatever it can match from `applicant_profile.json`, and stops right
before Submit so you can review and send it yourself. It's local only —
it needs a real browser and you present to answer prompts, so it's not
part of the GitHub Actions workflow.

Setup:

```bash
pip install playwright
playwright install chromium
```

Create `applicant_profile.json` in the repo root (already gitignored —
it holds your contact info and resume path, never commit it):

```json
{
  "first_name": "...", "last_name": "...", "full_name": "...",
  "email": "...", "phone": "...", "location": "City, ST",
  "resume_path": "/absolute/path/to/resume.pdf",
  "linkedin_url": "...", "github_url": "...",
  "work_authorization": "Authorized to work in the US, no sponsorship needed",
  "eeo_response": "decline",
  "salary_expectation": null,
  "learned_answers": {}
}
```

Run:

```bash
python apply.py            # batch of 30, newest first
python apply.py --batch 10
```

For each job it: navigates to the posting, attaches your resume, fills
matching fields (name/email/phone/location/LinkedIn/GitHub/work
authorization), tries to select "decline to answer" on EEO questions, and
pauses in the terminal for anything else required that it can't map —
salary/comp questions always pause fresh since there's no fixed answer,
everything else gets saved to `learned_answers` so it doesn't ask again.

Once a job is filled, review it in the browser, then answer the prompt:
`[Enter]` if you submitted it, `s` if you filled it but didn't submit,
`p` if it needs info you don't have right now, `x` to skip the job, or
`q` to stop the batch. This gets recorded in `application_status.json`
(and a `docs/` copy), which the dashboard reads to show an "Application
Status" column — blank for anything not yet attempted. Already-recorded
jobs are automatically skipped in future batches.

Only Greenhouse, Lever, and Ashby postings are supported — these render
their forms with JavaScript, so the field-matching is best-effort and
markup varies by company; expect occasional pauses for fields it doesn't
recognize on the first run against a new company's form.

Nothing gets committed automatically — `git add`/commit/push
`application_status.json` and `docs/application_status.json` yourself,
same as the other dashboard files.

## Extending

- Add more ATS fetchers (Workday, SmartRecruiters, BambooHR) by writing a
  new `fetch_*` function and registering it in the `FETCHERS` dict.
- Filter by title/location: add a keyword check in `main()` before adding
  to `new_by_company`.
- This could feed directly into your Chrome extension/profile hub —
  e.g., write new postings to a shared file it can read.
