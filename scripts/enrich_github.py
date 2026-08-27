#!/usr/bin/env python3
"""
Populate museums with GitHub accounts from Wikidata into Baserow.
- Updates existing museums (matched by QID) with GitHub data
- Adds new rows for museums not yet in the database
Uses Wikidata property P2037 (GitHub username).
"""

import sys
import io
import os
import time
import requests
from collections import defaultdict

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from baserow_config import SOURCES_TABLE_ID as TABLE_ID, SOURCES_FIELDS as FIELDS

# Configuration
BASEROW_URL = os.environ["BASEROW_URL"]
BASEROW_TOKEN = os.environ["BASEROW_TOKEN"]


def query_wikidata():
    """Query Wikidata for all museums worldwide with GitHub accounts."""
    print("Querying Wikidata for all museums with GitHub accounts (worldwide)...")

    query = """
    SELECT ?qid ?museum ?museumLabel ?github ?countryLabel ?website WHERE {
      ?museum wdt:P31/wdt:P279* wd:Q33506.
      ?museum wdt:P2037 ?github.
      BIND(STRAFTER(STR(?museum), 'entity/') AS ?qid)
      OPTIONAL { ?museum wdt:P17 ?country. }
      OPTIONAL { ?museum wdt:P856 ?website. }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    """

    response = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query},
        headers={"Accept": "application/json", "User-Agent": "MusemaniacBot/1.0"},
        timeout=120,  # worldwide SPARQL query — slow, but must not hang forever
    )
    response.raise_for_status()

    data = response.json()

    # Process results - group by QID
    wikidata_museums = {}
    for binding in data["results"]["bindings"]:
        qid = binding["qid"]["value"]
        github = binding["github"]["value"]
        uri = binding["museum"]["value"]
        name = binding.get("museumLabel", {}).get("value", "Unknown")
        country = binding.get("countryLabel", {}).get("value", "Unknown")
        website = binding.get("website", {}).get("value", "")
        wikidata_museums[qid] = {
            "github": github,
            "name": name,
            "uri": uri,
            "country": country,
            "website": website,
        }

    print(f"Found {len(wikidata_museums)} museums with GitHub in Wikidata (worldwide)")
    return wikidata_museums


def get_all_baserow_qids():
    """Get all QIDs currently in Baserow (all countries)."""
    print("Fetching all museum QIDs from Baserow...")

    qid_to_row = {}
    page = 1

    while True:
        response = requests.get(
            f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/",
            params={"size": 200, "page": page},
            headers={"Authorization": f"Token {BASEROW_TOKEN}"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        for row in data["results"]:
            qid = row[FIELDS["qid"]]
            if qid:
                qid_to_row[qid] = row

        if not data["next"]:
            break
        page += 1
        if page % 20 == 0:
            print(f"  Fetched page {page}, QIDs so far: {len(qid_to_row)}")

    print(f"Found {len(qid_to_row)} museums with QIDs in Baserow")
    return qid_to_row


def categorize_museums(wikidata_museums, baserow_qid_map):
    """Split into museums to update vs museums to add."""
    to_update = []
    to_add = []

    for qid, wiki_data in wikidata_museums.items():
        if qid in baserow_qid_map:
            row = baserow_qid_map[qid]
            # Only update if github field is empty
            if not row[FIELDS["github"]]:
                to_update.append({
                    "row_id": row["id"],
                    "name": row[FIELDS["name"]],
                    "qid": qid,
                    "updates": {
                        FIELDS["github"]: wiki_data["github"],
                        FIELDS["github_url"]: f"https://github.com/{wiki_data['github']}",
                    }
                })
        else:
            to_add.append({
                "qid": qid,
                "name": wiki_data["name"],
                "uri": wiki_data["uri"],
                "country": wiki_data["country"],
                "website": wiki_data["website"],
                "github": wiki_data["github"],
            })

    return to_update, to_add


def apply_updates(to_update, dry_run=True):
    """Update existing Baserow rows with GitHub data."""
    if not to_update:
        print("\nNo existing museums to update.")
        return

    if dry_run:
        print(f"\n=== DRY RUN - Would UPDATE {len(to_update)} existing museums ===\n")
        for e in to_update:
            print(f"  {e['name']} ({e['qid']})")
            print(f"    + github: {e['updates'][FIELDS['github']]}")
            print(f"    + github_url: {e['updates'][FIELDS['github_url']]}")
        return

    print(f"\n=== Updating {len(to_update)} existing museums ===\n")
    success = 0
    failed = 0

    for i, e in enumerate(to_update):
        try:
            response = requests.patch(
                f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/{e['row_id']}/",
                json=e['updates'],
                headers={
                    "Authorization": f"Token {BASEROW_TOKEN}",
                    "Content-Type": "application/json"
                },
                timeout=30,
            )
            response.raise_for_status()
            success += 1
            print(f"  [{i+1}/{len(to_update)}] Updated: {e['name']}")
        except Exception as ex:
            failed += 1
            print(f"  [{i+1}/{len(to_update)}] FAILED: {e['name']} - {ex}")

    print(f"\nUpdates complete: {success} success, {failed} failed")


def apply_additions(to_add, dry_run=True):
    """Add new museum rows to Baserow."""
    if not to_add:
        print("\nNo new museums to add.")
        return

    if dry_run:
        print(f"\n=== DRY RUN - Would ADD {len(to_add)} new museums ===\n")
        for m in to_add:
            print(f"  {m['name']} ({m['qid']}) [{m['country']}]")
            print(f"    github: {m['github']}")
            print(f"    website: {m['website'] or '-'}")
        return

    print(f"\n=== Adding {len(to_add)} new museums ===\n")
    success = 0
    failed = 0

    for i, m in enumerate(to_add):
        row_data = {
            FIELDS["name"]: m["name"],
            FIELDS["museum_uri"]: m["uri"],
            FIELDS["qid"]: m["qid"],
            FIELDS["country"]: m["country"],
            FIELDS["website"]: m["website"] or "",
            FIELDS["github"]: m["github"],
            FIELDS["github_url"]: f"https://github.com/{m['github']}",
        }

        try:
            response = requests.post(
                f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/",
                json=row_data,
                headers={
                    "Authorization": f"Token {BASEROW_TOKEN}",
                    "Content-Type": "application/json"
                },
                timeout=30,
            )
            response.raise_for_status()
            success += 1
            print(f"  [{i+1}/{len(to_add)}] Added: {m['name']} [{m['country']}]")
            time.sleep(0.1)  # Be gentle to the API
        except Exception as ex:
            failed += 1
            print(f"  [{i+1}/{len(to_add)}] FAILED: {m['name']} - {ex}")

    print(f"\nAdditions complete: {success} added, {failed} failed")


def main():
    dry_run = "--apply" not in sys.argv

    if dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No changes will be made")
        print("Run with --apply to actually update Baserow")
        print("=" * 60)

    # Get data from both sources
    wikidata_museums = query_wikidata()

    # Show all museums with GitHub worldwide
    print(f"\n{'='*60}")
    print("ALL MUSEUMS WITH GITHUB IN WIKIDATA")
    print(f"{'='*60}")
    by_country = defaultdict(list)
    for qid, data in wikidata_museums.items():
        by_country[data["country"]].append((qid, data))

    for country in sorted(by_country.keys()):
        print(f"\n  {country}:")
        for qid, data in sorted(by_country[country], key=lambda x: x[1]["name"]):
            print(f"    {data['name']} ({qid}) -> github.com/{data['github']}")

    # Fetch all existing QIDs from Baserow
    baserow_qid_map = get_all_baserow_qids()

    # Categorize: update existing vs add new
    to_update, to_add = categorize_museums(wikidata_museums, baserow_qid_map)

    # Summary
    print(f"\n{'='*60}")
    print("ACTION SUMMARY")
    print(f"{'='*60}")
    print(f"Museums with GitHub in Wikidata: {len(wikidata_museums)}")
    print(f"Already in Baserow (will UPDATE github fields): {len(to_update)}")
    print(f"Not in Baserow (will ADD as new rows): {len(to_add)}")

    already_have = len(wikidata_museums) - len(to_update) - len(to_add)
    if already_have > 0:
        print(f"Already have GitHub data (skip): {already_have}")

    # Apply
    apply_updates(to_update, dry_run=dry_run)
    apply_additions(to_add, dry_run=dry_run)


if __name__ == "__main__":
    main()
