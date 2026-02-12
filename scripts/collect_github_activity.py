#!/usr/bin/env python3
"""
Collect recent GitHub activity from museum organizations.
Monitors 133+ museum GitHub accounts for:
  - New repos created
  - New releases published
  - Significant pushes to default branches

Usage:
  python collect_github_activity.py [--days 14] [--output github_activity.json]

Requires environment variables: BASEROW_URL, BASEROW_TOKEN, GITHUB_TOKEN
"""

import sys
import io
import os
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# Configuration from environment
BASEROW_URL = os.environ["BASEROW_URL"]
BASEROW_TOKEN = os.environ["BASEROW_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
TABLE_ID = 745

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
}

FIELDS = {
    "name": "field_7191",
    "github": "field_7222",
}

# Bot authors to skip
BOT_AUTHORS = {"dependabot[bot]", "dependabot-preview[bot]", "renovate[bot]",
               "github-actions[bot]", "snyk-bot", "codecov[bot]", "greenkeeper[bot]"}


def github_get(url, params=None):
    """Make a GitHub API request with rate limit handling."""
    resp = requests.get(url, params=params, headers=GITHUB_HEADERS)
    if resp.status_code == 403:
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset - time.time(), 0) + 2
        print(f"  Rate limited! Waiting {wait:.0f}s...")
        time.sleep(wait)
        resp = requests.get(url, params=params, headers=GITHUB_HEADERS)
    return resp


def get_museum_orgs():
    """Fetch all museum GitHub logins from Baserow."""
    print("Fetching museum GitHub accounts from Baserow...")
    orgs = []
    page = 1

    while True:
        response = requests.get(
            f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/",
            params={
                "size": 200,
                "page": page,
                "filter__field_7222__not_empty": "true",
            },
            headers={"Authorization": f"Token {BASEROW_TOKEN}"}
        )
        response.raise_for_status()
        data = response.json()

        for row in data["results"]:
            github_login = row.get(FIELDS["github"], "").strip()
            name = row.get(FIELDS["name"], "")
            if github_login:
                orgs.append({"login": github_login, "name": name})

        if not data["next"]:
            break
        page += 1

    print(f"Found {len(orgs)} museums with GitHub accounts")
    return orgs


def collect_new_repos(org_login, cutoff_date):
    """Find repos created after cutoff_date for an org."""
    items = []
    resp = github_get(f"{GITHUB_API}/orgs/{org_login}/repos",
                      {"sort": "created", "direction": "desc", "per_page": 10})
    if resp.status_code != 200:
        return items

    for repo in resp.json():
        if repo.get("fork"):
            continue
        created = repo.get("created_at", "")
        if not created:
            continue
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created_dt < cutoff_date:
            break  # Sorted by created desc, so no more new ones

        items.append({
            "org": org_login,
            "event_type": "new_repo",
            "repo": repo["full_name"],
            "title": repo["name"],
            "description": (repo.get("description") or "")[:200],
            "url": repo["html_url"],
            "date": created[:10],
            "details": {
                "language": repo.get("language"),
                "stars": repo.get("stargazers_count", 0),
                "topics": repo.get("topics", []),
            }
        })

    return items


def collect_events(org_login, cutoff_date):
    """Fetch org events and extract releases and significant pushes."""
    items = []
    resp = github_get(f"{GITHUB_API}/orgs/{org_login}/events", {"per_page": 30})
    if resp.status_code != 200:
        return items

    for event in resp.json():
        event_date = event.get("created_at", "")
        if not event_date:
            continue
        event_dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
        if event_dt < cutoff_date:
            continue

        actor = event.get("actor", {}).get("login", "")
        if actor in BOT_AUTHORS:
            continue

        event_type = event.get("type")
        payload = event.get("payload", {})
        repo_name = event.get("repo", {}).get("name", "")

        if event_type == "ReleaseEvent" and payload.get("action") == "published":
            release = payload.get("release", {})
            items.append({
                "org": org_login,
                "event_type": "release",
                "repo": repo_name,
                "title": release.get("name") or release.get("tag_name", ""),
                "description": (release.get("body") or "")[:300],
                "url": release.get("html_url", ""),
                "date": event_date[:10],
                "details": {
                    "tag": release.get("tag_name"),
                    "prerelease": release.get("prerelease", False),
                }
            })

        elif event_type == "PushEvent":
            ref = payload.get("ref", "")
            # Only default branches
            if not any(ref.endswith(b) for b in ("/main", "/master", "/develop")):
                continue
            commits = payload.get("commits", [])
            num_commits = payload.get("size", len(commits))
            # Skip trivial pushes (1 commit that's a merge or CI)
            if num_commits <= 1 and commits:
                msg = commits[0].get("message", "")
                if msg.startswith("Merge ") or msg.startswith("chore:"):
                    continue

            branch = ref.split("/")[-1]
            commit_msgs = [c.get("message", "").split("\n")[0][:80] for c in commits[:5]]

            # Build compare URL if we have before/after hashes
            head = payload.get("head", "")
            before = payload.get("before", "")
            if head and before:
                url = f"https://github.com/{repo_name}/compare/{before[:7]}...{head[:7]}"
            else:
                url = f"https://github.com/{repo_name}/commits/{branch}"

            title = f"{num_commits} commit(s) to {branch}" if num_commits > 0 else f"Push to {branch}"

            items.append({
                "org": org_login,
                "event_type": "push",
                "repo": repo_name,
                "title": title,
                "description": "; ".join(commit_msgs) if commit_msgs else "",
                "url": url,
                "date": event_date[:10],
                "details": {
                    "branch": branch,
                    "commit_count": num_commits,
                    "distinct_count": payload.get("distinct_size", 0),
                }
            })

    return items


def main():
    parser = argparse.ArgumentParser(description="Collect GitHub activity from museum orgs")
    parser.add_argument("--days", type=int, default=14, help="Look back N days (default: 14)")
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "github_activity.json"),
                        help="Output JSON file (default: scripts/github_activity.json)")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"Collecting GitHub activity from the last {args.days} days (since {cutoff.strftime('%Y-%m-%d')})")

    # Get museum orgs from Baserow
    orgs = get_museum_orgs()

    all_activity = []
    orgs_with_activity = 0
    api_calls = 0

    print(f"\nScanning {len(orgs)} organizations...\n")

    for i, org in enumerate(orgs):
        login = org["login"]
        org_name = org["name"] or login

        # Fetch repos + events (2 API calls per org)
        new_repos = collect_new_repos(login, cutoff)
        events = collect_events(login, cutoff)
        api_calls += 2

        items = new_repos + events
        if items:
            orgs_with_activity += 1
            for item in items:
                item["org_name"] = org_name
            all_activity.extend(items)

        # Progress
        if (i + 1) % 20 == 0 or items:
            status = f"  [{i+1}/{len(orgs)}] {login}"
            if items:
                status += f" -> {len(items)} event(s)"
            print(status)

    # Deduplicate: for push events, keep only the latest per repo+branch
    push_best = {}  # key: (repo, branch) -> most recent push
    deduped = []
    seen_urls = set()
    for item in all_activity:
        if item["url"] in seen_urls:
            continue
        seen_urls.add(item["url"])

        if item["event_type"] == "push":
            key = (item["repo"], item["details"].get("branch", ""))
            if key not in push_best or item["date"] > push_best[key]["date"]:
                push_best[key] = item
        else:
            deduped.append(item)

    deduped.extend(push_best.values())

    # Sort by date descending
    deduped.sort(key=lambda x: x["date"], reverse=True)

    # Save
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'='*60}")
    print("COLLECTION SUMMARY")
    print(f"{'='*60}")
    print(f"Organizations scanned: {len(orgs)}")
    print(f"Organizations with activity: {orgs_with_activity}")
    print(f"API calls made: {api_calls}")
    print(f"Total events found: {len(deduped)}")

    by_type = {}
    for item in deduped:
        by_type[item["event_type"]] = by_type.get(item["event_type"], 0) + 1
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")

    print(f"\nSaved to {args.output}")

    if deduped:
        print(f"\n{'='*60}")
        print("HIGHLIGHTS")
        print(f"{'='*60}")
        for item in deduped[:15]:
            emoji = {"new_repo": "NEW", "release": "REL", "push": "PUSH"}.get(item["event_type"], "???")
            print(f"\n  [{emoji}] {item['org_name']} / {item['title']}")
            print(f"    {item['date']} | {item['url']}")
            if item["description"]:
                print(f"    {item['description'][:120]}")


if __name__ == "__main__":
    main()
