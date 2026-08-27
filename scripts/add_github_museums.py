#!/usr/bin/env python3
"""
Add curated GitHub museum organizations to Baserow.
- Skips orgs already in the database (matched by github login, case-insensitive)
- Adds new rows for the rest
"""

import sys
import io
import json
import time
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import baserow_client
from baserow_config import SOURCES_TABLE_ID as TABLE_ID, SOURCES_FIELDS as FIELDS

# Fail fast on missing credentials (baserow_client reads them per call)
BASEROW_URL = os.environ["BASEROW_URL"]
BASEROW_TOKEN = os.environ["BASEROW_TOKEN"]

CURATED_FILE = os.path.join(os.path.dirname(__file__), "github_museums_curated.json")

# Map GitHub location strings to normalized country names
COUNTRY_MAP = {
    "copenhagen": "Denmark", "aarhus": "Denmark", "denmark": "Denmark",
    "san francisco": "United States", "berkeley": "United States",
    "new york": "United States", "manhattan": "United States",
    "chicago": "United States", "pittsburgh": "United States",
    "boston": "United States", "seattle": "United States",
    "denver": "United States", "oakland": "United States",
    "milwaukee": "United States", "washington": "United States",
    "santa fe": "United States", "rhode island": "United States",
    "raleigh": "United States", "waterville": "United States",
    "los angeles": "United States", "princeton": "United States",
    "monticello": "United States", "springfield": "United States",
    "bardstown": "United States", "united states": "United States",
    "cambridge": "United Kingdom", "london": "United Kingdom",
    "bloomsbury": "United Kingdom", "united kingdom": "United Kingdom",
    "den haag": "Netherlands", "netherlands": "Netherlands",
    "arnhem": "Netherlands", "gent": "Belgium",
    "berlin": "Germany", "germany": "Germany", "stuttgart": "Germany",
    "hamburg": "Germany",
    "helsinki": "Finland", "finland": "Finland",
    "stockholm": "Sweden", "sweden": "Sweden", "falun": "Sweden",
    "vienna": "Austria", "austria": "Austria",
    "lausanne": "Switzerland", "switzerland": "Switzerland",
    "zurich": "Switzerland", "bern": "Switzerland",
    "jerusalem": "Israel", "tel aviv": "Israel",
    "ireland": "Ireland",
    "luxembourg": "Luxembourg",
    "rome": "Italy", "italy": "Italy",
    "france": "France",
    "oslo": "Norway", "norway": "Norway",
    "kolding": "Denmark",
    "buenos aires": "Argentina", "argentina": "Argentina",
    "colombia": "Colombia",
    "adelaide": "Australia", "tasmania": "Australia", "australia": "Australia",
    "canada": "Canada",
    "dunedin": "New Zealand", "new zealand": "New Zealand",
    "india": "India", "bengaluru": "India",
    "mexico": "Mexico",
    "singapore": "Singapore",
    "taiwan": "Taiwan",
    "costa rica": "Costa Rica",
    "poland": "Poland",
    "ukraine": "Ukraine",
    "russia": "Russia", "russian": "Russia", "moscow": "Russia",
    "uae": "United Arab Emirates",
}


def guess_country(location):
    """Try to map a location string to a country."""
    if not location:
        return ""
    loc_lower = location.lower()
    for key, country in COUNTRY_MAP.items():
        if key in loc_lower:
            return country
    return ""


def get_existing_github_logins():
    """Get all GitHub logins already in Baserow."""
    print("Fetching existing GitHub logins from Baserow...")
    rows = baserow_client.list_rows(TABLE_ID, user_field_names=False, timeout=30)
    logins = {row[FIELDS["github"]].lower()
              for row in rows if row.get(FIELDS["github"])}
    print(f"Found {len(logins)} existing GitHub logins in Baserow")
    return logins


def main():
    dry_run = "--apply" not in sys.argv

    if dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No changes will be made")
        print("Run with --apply to actually add to Baserow")
        print("=" * 60)

    # Load curated list
    with open(CURATED_FILE, "r", encoding="utf-8") as f:
        curated = json.load(f)
    print(f"Loaded {len(curated)} curated orgs")

    # Get existing logins
    existing = get_existing_github_logins()

    # Filter to only new ones
    to_add = []
    skipped = []
    for org in curated:
        if org["login"].lower() in existing:
            skipped.append(org["login"])
        else:
            to_add.append(org)

    print(f"\nAlready in Baserow: {len(skipped)}")
    print(f"New to add: {len(to_add)}")

    if not to_add:
        print("\nNothing new to add!")
        return

    if dry_run:
        print(f"\n=== DRY RUN - Would ADD {len(to_add)} museums ===\n")
        for org in to_add:
            country = guess_country(org.get("location", ""))
            name = org["name"] if org["name"] != org["login"] else org["login"]
            print(f"  {name} -> github.com/{org['login']} [{country or '?'}] ({org['public_repos']} repos)")
        return

    print(f"\n=== Adding {len(to_add)} museums ===\n")
    success = 0
    failed = 0

    for i, org in enumerate(to_add):
        country = guess_country(org.get("location", ""))
        name = org["name"] if org["name"] != org["login"] else org["login"]
        website = org.get("blog", "") or ""

        row_data = {
            FIELDS["name"]: name,
            FIELDS["country"]: country,
            FIELDS["website"]: website,
            FIELDS["github"]: org["login"],
            FIELDS["github_url"]: f"https://github.com/{org['login']}",
        }

        try:
            baserow_client.create_row(TABLE_ID, row_data,
                                      user_field_names=False, timeout=30)
            success += 1
            print(f"  [{i+1}/{len(to_add)}] Added: {name} [{country}]")
            time.sleep(0.1)
        except Exception as ex:
            failed += 1
            print(f"  [{i+1}/{len(to_add)}] FAILED: {name} - {ex}")

    print(f"\nComplete: {success} added, {failed} failed")


if __name__ == "__main__":
    main()
