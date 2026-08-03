#!/usr/bin/env python3
"""
Auto-discover ATS + slug for a list of company names.

Given company_names.json (a list of {"Overall #", "Category", "Company"}
or just plain strings), this tries a set of plausible slug variants for
each company against the Greenhouse, Lever, and Ashby public APIs and
records which one (if any) responds with a valid job board.

Run this from an environment with open internet access (your own machine,
or as a one-off GitHub Actions job) — it needs to reach
boards-api.greenhouse.io, api.lever.co, and api.ashbyhq.com directly.

Usage:
    python discover_ats.py

Outputs:
    companies_discovered.json  — matches found, ready to merge into companies.json
    discovery_report.csv       — every company with its match (or "NOT FOUND")
"""

import json
import re
import time
import csv
from pathlib import Path

import requests

INPUT_FILE = Path("company_names.json")
FOUND_FILE = Path("companies_discovered.json")
REPORT_FILE = Path("discovery_report.csv")

TIMEOUT = 10
SLEEP_BETWEEN = 0.15  # be polite to the APIs


def slug_variants(name):
    """Generate plausible slug candidates from a company name."""
    # Take each "/"-separated alias separately, e.g. "Google / Alphabet"
    parts = [p.strip() for p in name.split("/")]
    variants = set()
    for part in parts:
        base = part.lower()
        base = re.sub(r"[^a-z0-9\s\-&]", "", base)
        base = base.replace("&", "and")
        # common suffixes to strip
        for suffix in [" inc", " labs", " ai", " systems", " technologies",
                       " technology", " holdings", " group", " limited",
                       " corporation", " corp"]:
            if base.endswith(suffix):
                variants.add(base[: -len(suffix)].strip())
        words = base.split()
        no_space = "".join(words)
        dashed = "-".join(words)
        variants.update({base.strip(), no_space, dashed})
    # dedupe, drop empties
    return sorted({v for v in variants if v})


def check_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200 and "jobs" in r.json():
            return True
    except Exception:
        pass
    return False


def check_lever(slug):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200 and isinstance(r.json(), list):
            return True
    except Exception:
        pass
    return False


def check_ashby(slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200 and "jobs" in r.json():
            return True
    except Exception:
        pass
    return False


CHECKS = [("greenhouse", check_greenhouse), ("lever", check_lever), ("ashby", check_ashby)]


def discover(name):
    for slug in slug_variants(name):
        for ats, check_fn in CHECKS:
            if check_fn(slug):
                return {"name": name, "ats": ats, "slug": slug}
            time.sleep(SLEEP_BETWEEN)
    return None


def main():
    raw = json.loads(INPUT_FILE.read_text())
    # support either plain strings or {"Company": "..."} records
    names = [r["Company"] if isinstance(r, dict) else r for r in raw]

    found = []
    report_rows = []

    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name} ...", end=" ", flush=True)
        result = discover(name)
        if result:
            print(f"-> {result['ats']} / {result['slug']}")
            found.append(result)
            report_rows.append([name, result["ats"], result["slug"]])
        else:
            print("-> not found (add manually or use 'custom')")
            report_rows.append([name, "NOT FOUND", ""])

    FOUND_FILE.write_text(json.dumps(found, indent=2))
    with open(REPORT_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Company", "ATS", "Slug"])
        w.writerows(report_rows)

    print(f"\nDone. {len(found)}/{len(names)} matched.")
    print(f"See {FOUND_FILE} and {REPORT_FILE}.")


if __name__ == "__main__":
    main()
