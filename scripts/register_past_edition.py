#!/usr/bin/env python3
"""
Register a past edition in Baserow (for editions generated locally that missed auto-registration).

Usage:
  python register_past_edition.py 2026-03-11

After running, also copy the HTML file to the VPS:
  scp -i ~/.ssh/id_ed25519 scripts/editions/newsletter_2026-03-11.html root@77.42.40.207:/opt/musemaniac/scripts/editions/

Requires environment variables:
  BASEROW_URL, BASEROW_TOKEN, EDITION_TABLE_ID
"""

import sys
import os
import requests
from datetime import datetime, timezone

BASEROW_URL = os.environ["BASEROW_URL"]
BASEROW_TOKEN = os.environ["BASEROW_TOKEN"]
EDITION_TABLE_ID = os.environ["EDITION_TABLE_ID"]

BASEROW_HEADERS = {
    "Authorization": f"Token {BASEROW_TOKEN}",
    "Content-Type": "application/json",
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python register_past_edition.py YYYY-MM-DD")
        sys.exit(1)

    edition_date = sys.argv[1]

    try:
        dt = datetime.strptime(edition_date, "%Y-%m-%d")
    except ValueError:
        print(f"ERROR: Invalid date format: {edition_date} (expected YYYY-MM-DD)")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_name = f"newsletter_{edition_date}.html"
    file_path = os.path.join(script_dir, "editions", file_name)

    if not os.path.exists(file_path):
        print(f"WARNING: {file_path} not found locally — registering anyway")
        print("  Make sure to copy the HTML file to the VPS manually.")

    row_data = {
        "edition_label": f"Edition — {edition_date}",
        "edition_date": edition_date,
        "spotlight_repo": "",
        "spotlight_org": "",
        "spotlight_summary": "",
        "stats_active_orgs": 0,
        "stats_total_pushes": 0,
        "stats_unique_repos": 0,
        "stats_new_projects": 0,
        "stats_releases": 0,
        "file_name": file_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Refuse to create a duplicate row for a date that is already registered
    # (this script writes empty stats, so updating would clobber a real row).
    page = 1
    while True:
        resp = requests.get(
            f"{BASEROW_URL}/api/database/rows/table/{EDITION_TABLE_ID}/",
            params={"size": 200, "page": page, "user_field_names": "true"},
            headers=BASEROW_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for row in data.get("results", []):
            if row.get("edition_date") == edition_date:
                print(f"Edition {edition_date} is already registered (Baserow row {row['id']}) — nothing to do.")
                sys.exit(0)
        if not data.get("next"):
            break
        page += 1

    print(f"Registering edition {edition_date} in Baserow (table {EDITION_TABLE_ID})...")
    url = f"{BASEROW_URL}/api/database/rows/table/{EDITION_TABLE_ID}/"
    resp = requests.post(url, json=row_data, params={"user_field_names": "true"}, headers=BASEROW_HEADERS, timeout=10)
    resp.raise_for_status()
    row = resp.json()
    print(f"  Done — Baserow row {row.get('id')}")
    print(f"\nNext: copy the HTML to the VPS:")
    print(f"  scp -i ~/.ssh/id_ed25519 scripts/editions/{file_name} root@77.42.40.207:/opt/musemaniac/scripts/editions/")


if __name__ == "__main__":
    main()
