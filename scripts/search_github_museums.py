#!/usr/bin/env python3
"""
Search GitHub for museum-related organizations.
Two modes:
  1. python search_github_museums.py --search   (search for orgs, save candidate list)
  2. python search_github_museums.py --details  (fetch details for saved candidates, resumable)
"""

import sys
import io
import json
import time
import os
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
}
CANDIDATES_FILE = os.path.join(os.path.dirname(__file__), "github_museum_candidates.json")
DETAILS_FILE = os.path.join(os.path.dirname(__file__), "github_museum_details.json")

# Static snapshot of logins that were already in Baserow when this list was
# written — it WILL drift as sources are added/removed there. Drift is
# harmless: it only pre-filters the candidate list, and add_github_museums.py
# dedups against live Baserow before writing anything. Refresh it (or ignore
# the extra candidates) rather than trusting it as current.
KNOWN_GITHUB = {x.lower() for x in [
    "agnsw", "museumofappliedartsandsciences", "museumsvictoria", "nla",
    "NationalMuseumAustralia", "wamuseum", "ONB-RD", "CCA-Public",
    "NationalMuseumofDenmark", "StatensMuseumforKunst", "ina-foss",
    "buchmuseum", "LMWStuttgart", "Museum-Barberini", "MfN-Berlin",
    "MKGHamburg", "Rijksmuseum", "AucklandMuseum", "te-papa",
    "Munchmuseet", "mplusmuseum", "SlovakNationalGallery",
    "racunalniskimuzej", "NationalmuseumSWE", "NordicMuseum", "sapa",
    "Limeishu", "BritishMuseum", "LlGC-NLW", "NaturalHistoryMuseum",
    "vanda", "wellcometrust", "thewarholmuseum", "Art-Institute-of-Chicago",
    "BarnesFoundation", "brooklynmuseum", "cmoa", "brooklynhistory",
    "ClevelandMuseumArt", "cooperhewitt", "DallasMuseumArt",
    "harvardartmuseums", "vhmml", "IMAmuseum", "gettypubs",
    "thejewishmuseum", "metmuseum", "artsmia", "mfahouston",
    "lifeandscience", "MuseumofModernArt", "NationalGalleryOfArt",
    "scimusmn", "smithsonian", "walkerart", "WaltersArtMuseum", "ycba-cia",
]}


def api_get(url, params=None):
    """Make a GitHub API request with rate limit handling."""
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    if resp.status_code == 403:
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset - time.time(), 0) + 2
        print(f"  Rate limited! Waiting {wait:.0f}s...")
        time.sleep(wait)
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    return resp


def search_orgs(query, per_page=100, pages=3):
    """Search for organizations."""
    all_items = []
    for page in range(1, pages + 1):
        resp = api_get(f"{GITHUB_API}/search/users",
                       {"q": f"{query} type:org", "per_page": per_page, "page": page})
        if resp.status_code != 200:
            break
        data = resp.json()
        all_items.extend(data.get("items", []))
        if len(all_items) >= data.get("total_count", 0):
            break
        time.sleep(6)
    return all_items


def do_search():
    """Phase 1: Search for museum orgs and save candidates."""
    all_orgs = {}

    searches = [
        ("museum", "museum"),
        ("gallery art", "gallery art"),
        ("archive cultural", "archive cultural"),
        ("heritage digital", "heritage digital"),
        ("musée", "musée"),
        ("museo", "museo"),
        ("bibliotek", "bibliotek"),
    ]

    print("=" * 60)
    print("SEARCHING GITHUB FOR MUSEUM/CULTURAL ORGANIZATIONS")
    print("=" * 60)

    for query, label in searches:
        print(f"\nSearching: {label}...")
        orgs = search_orgs(query, pages=2)
        new = 0
        for org in orgs:
            key = org["login"].lower()
            if key not in all_orgs:
                all_orgs[key] = {"login": org["login"], "source": label}
                new += 1
        print(f"  Found {len(orgs)} orgs, {new} new")
        time.sleep(7)

    # Filter known
    new_orgs = {k: v for k, v in all_orgs.items() if k not in KNOWN_GITHUB}

    print(f"\nTotal unique orgs: {len(all_orgs)}")
    print(f"Already in Baserow: {len(all_orgs) - len(new_orgs)}")
    print(f"New candidates: {len(new_orgs)}")

    # Save candidates
    candidates = [v for v in sorted(new_orgs.values(), key=lambda x: x["login"].lower())]
    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(candidates)} candidates to {CANDIDATES_FILE}")
    print(f"Now run with --details to fetch org details (takes ~7 min with rate limits)")


def do_details():
    """Phase 2: Fetch details for candidates. Resumable."""
    if not os.path.exists(CANDIDATES_FILE):
        print("No candidates file found. Run with --search first.")
        return

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    # Load existing details if resuming
    existing = {}
    if os.path.exists(DETAILS_FILE):
        with open(DETAILS_FILE, "r", encoding="utf-8") as f:
            for d in json.load(f):
                existing[d["login"].lower()] = d
        print(f"Resuming: {len(existing)} already fetched")

    remaining = [c for c in candidates if c["login"].lower() not in existing]
    print(f"Candidates: {len(candidates)}, remaining to fetch: {len(remaining)}")

    detailed = list(existing.values())

    for i, cand in enumerate(remaining):
        resp = api_get(f"{GITHUB_API}/orgs/{cand['login']}")
        if resp.status_code == 200:
            d = resp.json()
            detailed.append({
                "login": cand["login"],
                "name": d.get("name") or cand["login"],
                "description": (d.get("description") or "")[:150],
                "blog": d.get("blog") or "",
                "location": d.get("location") or "",
                "public_repos": d.get("public_repos", 0),
                "created_at": (d.get("created_at") or "")[:10],
                "source": cand["source"],
            })
        elif resp.status_code == 404:
            # Not an org (might be a user), skip
            detailed.append({
                "login": cand["login"],
                "name": cand["login"],
                "description": "",
                "blog": "",
                "location": "",
                "public_repos": 0,
                "source": cand["source"],
            })

        # Save progress every 20 entries
        if (i + 1) % 20 == 0:
            with open(DETAILS_FILE, "w", encoding="utf-8") as f:
                json.dump(detailed, f, indent=2, ensure_ascii=False)
            print(f"  Progress: {i+1}/{len(remaining)} fetched, saved checkpoint")

        # Check rate limit
        remaining_calls = int(resp.headers.get("X-RateLimit-Remaining", 60))
        if remaining_calls <= 2:
            reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            wait = max(reset - time.time(), 0) + 2
            # Save before waiting
            with open(DETAILS_FILE, "w", encoding="utf-8") as f:
                json.dump(detailed, f, indent=2, ensure_ascii=False)
            print(f"  Rate limit approaching, saved progress. Waiting {wait:.0f}s...")
            time.sleep(wait)

    # Final save
    with open(DETAILS_FILE, "w", encoding="utf-8") as f:
        json.dump(detailed, f, indent=2, ensure_ascii=False)

    # Print results
    active = [d for d in detailed if d["public_repos"] > 0]
    active.sort(key=lambda x: -x["public_repos"])

    print(f"\n{'='*60}")
    print(f"MUSEUM/CULTURAL ORGS WITH PUBLIC REPOS ({len(active)})")
    print(f"{'='*60}\n")

    for d in active:
        print(f"  {d['login']} ({d['public_repos']} repos)")
        if d["name"] != d["login"]:
            print(f"    Name: {d['name']}")
        if d["description"]:
            print(f"    Desc: {d['description']}")
        if d["location"]:
            print(f"    Location: {d['location']}")
        if d["blog"]:
            print(f"    Web: {d['blog']}")
        print(f"    URL: https://github.com/{d['login']}")
        print()

    print(f"Total with repos: {len(active)}")
    print(f"Results saved to {DETAILS_FILE}")


def main():
    if "--search" in sys.argv:
        do_search()
    elif "--details" in sys.argv:
        do_details()
    else:
        print("Usage:")
        print("  python search_github_museums.py --search    Search GitHub for orgs")
        print("  python search_github_museums.py --details   Fetch details (resumable)")


if __name__ == "__main__":
    main()
