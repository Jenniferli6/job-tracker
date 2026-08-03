#!/usr/bin/env python3
"""
Merge companies_discovered.json (output of discover_ats.py) into
companies.json, in the format poller.py expects.

Companies that weren't matched are still included, marked as "ats": "TODO"
so they're easy to find and fix by hand (check their careers page manually,
or set "ats": "custom" with a "url").

Usage: python merge_discovered.py
"""

import json
from pathlib import Path

NAMES_FILE = Path("company_names.json")
DISCOVERED_FILE = Path("companies_discovered.json")
OUT_FILE = Path("companies.json")


def main():
    raw = json.loads(NAMES_FILE.read_text())
    all_names = [r["Company"] if isinstance(r, dict) else r for r in raw]

    discovered = json.loads(DISCOVERED_FILE.read_text()) if DISCOVERED_FILE.exists() else []
    by_name = {d["name"]: d for d in discovered}

    result = []
    for name in all_names:
        if name in by_name:
            d = by_name[name]
            result.append({"name": name, "ats": d["ats"], "slug": d["slug"]})
        else:
            result.append({
                "name": name,
                "ats": "TODO",
                "notes": "Not auto-matched — check careers page manually, "
                         "then set ats to greenhouse/lever/ashby+slug, or "
                         "custom+url",
            })

    OUT_FILE.write_text(json.dumps(result, indent=2))
    matched = sum(1 for r in result if r["ats"] != "TODO")
    print(f"Wrote {OUT_FILE} — {matched}/{len(result)} auto-matched, "
          f"{len(result) - matched} need manual follow-up.")


if __name__ == "__main__":
    main()
