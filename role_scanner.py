#!/usr/bin/env python3
"""
Scan Greenhouse / Lever / Ashby job boards for open roles matching
roles_config.json title patterns.

Unlike poller.py (target-company diff alerts), this collects a full snapshot
of currently-open matching roles across a broad board list — target companies
plus scan_boards_extra.json.

Outputs roles_snapshot.json (and docs/roles_snapshot.json for GitHub Pages).

Run manually:  python role_scanner.py
Run on schedule via the included GitHub Actions workflow.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from poller import FETCHERS, TIMEOUT

COMPANIES_FILE = Path("companies.json")
EXTRA_BOARDS_FILE = Path("scan_boards_extra.json")
ROLES_CONFIG_FILE = Path("roles_config.json")
SNAPSHOT_FILE = Path("roles_snapshot.json")
DOCS_SNAPSHOT_FILE = Path("docs/roles_snapshot.json")

SHORT_PATTERNS = {"fde", "mle"}


def load_boards():
    """Merge ATS boards from companies.json and scan_boards_extra.json."""
    boards = []
    seen = set()

    for source in (COMPANIES_FILE, EXTRA_BOARDS_FILE):
        if not source.exists():
            continue
        for entry in json.loads(source.read_text()):
            ats = entry.get("ats")
            if ats not in FETCHERS or ats == "custom":
                continue
            slug = entry.get("slug", "").strip()
            if not slug:
                continue
            key = (ats, slug.lower())
            if key in seen:
                continue
            seen.add(key)
            boards.append({
                "name": entry.get("name") or slug,
                "ats": ats,
                "slug": slug,
            })

    return boards


def load_role_patterns():
    config = json.loads(ROLES_CONFIG_FILE.read_text())
    patterns = []
    for item in config.get("title_patterns", []):
        label = item["label"]
        for match in item.get("match", []):
            patterns.append({"label": label, "match": match.lower()})
    return patterns


def match_role(title, patterns):
    t = title.lower()
    for p in patterns:
        m = p["match"]
        if m in SHORT_PATTERNS:
            if re.search(rf"\b{re.escape(m)}\b", t):
                return p["label"]
        elif m in t:
            return p["label"]
    return None


def scan_board(board, patterns):
    fetcher = FETCHERS[board["ats"]]
    jobs = fetcher(board)
    matches = []
    for job in jobs:
        label = match_role(job.get("title", ""), patterns)
        if not label:
            continue
        matches.append({
            "company": board["name"],
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "url": job.get("url", ""),
            "platform": board["ats"],
            "matched_role": label,
            "job_id": job.get("id", ""),
        })
    return matches


def main():
    boards = load_boards()
    patterns = load_role_patterns()
    roles = []
    errors = []

    for board in boards:
        try:
            roles.extend(scan_board(board, patterns))
        except Exception as e:
            errors.append(f"{board['name']} ({board['ats']}/{board['slug']}): {e}")

    roles.sort(key=lambda r: (r["company"].lower(), r["title"].lower()))

    snapshot = {
        "scanned_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "boards_scanned": len(boards) - len(errors),
        "boards_failed": len(errors),
        "open_roles": len(roles),
        "roles": roles,
    }

    SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2))
    DOCS_SNAPSHOT_FILE.parent.mkdir(exist_ok=True)
    DOCS_SNAPSHOT_FILE.write_text(json.dumps(snapshot, indent=2))

    print(
        f"Scanned {snapshot['boards_scanned']} boards, "
        f"found {snapshot['open_roles']} matching roles "
        f"({snapshot['boards_failed']} board errors)."
    )

    if errors:
        print("Errors:\n" + "\n".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
