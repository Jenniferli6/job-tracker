#!/usr/bin/env python3
"""
Job posting tracker.

Reads companies.json, checks each company's job board (Greenhouse, Lever,
Ashby, or a generic custom page), diffs against state.json to find newly
posted roles, and sends a notification (email and/or Slack) if anything
new shows up. Updates state.json in place.

Run manually:  python poller.py
Run on a schedule via the included GitHub Actions workflow.
"""

import json
import os
import smtplib
import sys
import hashlib
from email.mime.text import MIMEText
from pathlib import Path

import requests

COMPANIES_FILE = Path("companies.json")
STATE_FILE = Path("state.json")
LOG_FILE = Path("jobs_log.json")
DOCS_LOG_FILE = Path("docs/jobs_log.json")

TIMEOUT = 20
MAX_LOG_ENTRIES = 2000  # trim oldest beyond this so the log/dashboard stays manageable


# ---------- Fetchers: one per ATS, each returns a list of dicts ----------
# Each job dict: {"id": str, "title": str, "url": str, "location": str}

def fetch_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "id": str(j["id"]),
            "title": j.get("title", "Untitled"),
            "url": j.get("absolute_url", ""),
            "location": (j.get("location") or {}).get("name", ""),
        })
    return jobs


def fetch_lever(slug):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for j in data:
        jobs.append({
            "id": str(j.get("id")),
            "title": j.get("text", "Untitled"),
            "url": j.get("hostedUrl", ""),
            "location": (j.get("categories") or {}).get("location", ""),
        })
    return jobs


def fetch_ashby(slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "id": str(j.get("id")),
            "title": j.get("title", "Untitled"),
            "url": j.get("jobUrl", ""),
            "location": j.get("location", ""),
        })
    return jobs


def fetch_custom(url):
    """No structured API — hash the page content so we can at least detect
    'something changed' on the careers page."""
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    digest = hashlib.sha256(r.text.encode("utf-8", "ignore")).hexdigest()
    return [{
        "id": digest,
        "title": "Careers page content changed — check manually",
        "url": url,
        "location": "",
    }]


FETCHERS = {
    "greenhouse": lambda c: fetch_greenhouse(c["slug"]),
    "lever": lambda c: fetch_lever(c["slug"]),
    "ashby": lambda c: fetch_ashby(c["slug"]),
    "custom": lambda c: fetch_custom(c["url"]),
}


# ---------- State handling ----------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


# ---------- Job log (feeds the dashboard) ----------

def append_to_log(new_by_company):
    """Append newly found postings to jobs_log.json (and a copy under
    docs/ for GitHub Pages), newest first, trimmed to MAX_LOG_ENTRIES."""
    import datetime
    today = datetime.date.today().isoformat()

    existing = []
    if LOG_FILE.exists():
        existing = json.loads(LOG_FILE.read_text())

    new_entries = []
    for company, jobs in new_by_company.items():
        for j in jobs:
            new_entries.append({
                "date_found": today,
                "company": company,
                "title": j.get("title", ""),
                "location": j.get("location", ""),
                "url": j.get("url", ""),
            })

    combined = new_entries + existing  # newest first
    combined = combined[:MAX_LOG_ENTRIES]

    LOG_FILE.write_text(json.dumps(combined, indent=2))

    # Keep a copy under docs/ so GitHub Pages can serve it alongside the
    # dashboard HTML (Pages only serves files inside the configured folder).
    DOCS_LOG_FILE.parent.mkdir(exist_ok=True)
    DOCS_LOG_FILE.write_text(json.dumps(combined, indent=2))


# ---------- Notifications ----------

def send_email(subject, body):
    host = os.environ.get("SMTP_HOST")
    port = os.environ.get("SMTP_PORT")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    to_addr = os.environ.get("EMAIL_TO")
    if not all([host, port, user, password, to_addr]):
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    with smtplib.SMTP(host, int(port)) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())
    return True


def send_slack(text):
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        return False
    r = requests.post(webhook, json={"text": text}, timeout=TIMEOUT)
    r.raise_for_status()
    return True


def notify(new_by_company):
    if not new_by_company:
        return

    lines = []
    for company, jobs in new_by_company.items():
        lines.append(f"\n{company}")
        for j in jobs:
            loc = f" ({j['location']})" if j.get("location") else ""
            lines.append(f"  - {j['title']}{loc}\n    {j['url']}")
    body = "New job postings found:\n" + "\n".join(lines)

    sent_email = send_email("New job postings from tracked companies", body)
    sent_slack = send_slack(body)

    if not sent_email and not sent_slack:
        # No notifier configured — at least surface it in the Action log
        print(body)


# ---------- Main ----------

def main():
    companies = json.loads(COMPANIES_FILE.read_text())
    state = load_state()
    new_by_company = {}
    errors = []

    for company in companies:
        name = company["name"]
        ats = company["ats"]
        fetcher = FETCHERS.get(ats)
        if not fetcher:
            errors.append(f"{name}: unknown ats '{ats}'")
            continue

        try:
            jobs = fetcher(company)
        except Exception as e:
            errors.append(f"{name}: fetch failed ({e})")
            continue

        seen_ids = set(state.get(name, []))
        current_ids = {j["id"] for j in jobs}
        new_ids = current_ids - seen_ids

        # Skip the very first run per company — otherwise every existing
        # role looks "new". Only alert once we have a prior snapshot.
        if name in state:
            new_jobs = [j for j in jobs if j["id"] in new_ids]
            if new_jobs:
                new_by_company[name] = new_jobs

        state[name] = list(current_ids)

    save_state(state)
    append_to_log(new_by_company)
    notify(new_by_company)

    if errors:
        print("Errors:\n" + "\n".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
