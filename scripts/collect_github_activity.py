#!/usr/bin/env python3
"""
Collect recent GitHub activity from museums, cultural heritage orgs, and individuals.
Monitors 130+ GitHub accounts for:
  - New repos created
  - New releases published
  - Significant pushes to default branches

Supports two modes per entity:
  - Org-wide monitoring (default): tracks all repos via /orgs/{login}/events
  - Tracked repos: monitors only specific repos listed in tracked_repos field

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
TECHNOLOGIES_TABLE_ID = os.environ.get("TECHNOLOGIES_TABLE_ID")  # Optional

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
}

FIELDS = {
    "name": "field_7191",
    "github": "field_7222",
    "tracked_repos": "field_7261",
    "entity_type": "field_7225",
}

# Technology table field names (to be mapped to field IDs once table is created)
TECH_FIELDS = {
    "name": None,  # Will be set once table is created
    "parent": None,
    "tracked_repos": None,
    "active": None,
}

# Bot authors to skip
BOT_AUTHORS = {"dependabot[bot]", "dependabot-preview[bot]", "renovate[bot]",
               "github-actions[bot]", "snyk-bot", "codecov[bot]", "greenkeeper[bot]"}


def github_get(url, params=None):
    """Make a GitHub API request with rate limit handling."""
    resp = requests.get(url, params=params, headers=GITHUB_HEADERS)
    if resp.status_code == 401:
        # Bad/expired token. Abort loudly — silent 401s previously produced
        # newsletters with 0 GitHub events.
        raise SystemExit(
            f"GitHub API returned 401 (Bad credentials) for {url}. "
            "Check GITHUB_TOKEN — likely expired, revoked, or missing scopes."
        )
    if resp.status_code == 403:
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset - time.time(), 0) + 2
        print(f"  Rate limited! Waiting {wait:.0f}s...")
        time.sleep(wait)
        resp = requests.get(url, params=params, headers=GITHUB_HEADERS)
    return resp


def get_sources():
    """Fetch all GitHub-tracked entities from Baserow."""
    print("Fetching GitHub accounts from Baserow...")
    sources = []
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
            tracked_repos_raw = row.get(FIELDS["tracked_repos"]) or ""
            tracked_repos = [r.strip() for r in tracked_repos_raw.strip().splitlines() if r.strip()]
            entity_type = row.get(FIELDS["entity_type"], {})
            entity_type_value = entity_type.get("value") if isinstance(entity_type, dict) else None
            if github_login:
                sources.append({
                    "login": github_login,
                    "name": name,
                    "tracked_repos": tracked_repos,
                    "entity_type": entity_type_value
                })

        if not data["next"]:
            break
        page += 1

    print(f"Found {len(sources)} sources with GitHub accounts")
    return sources


def get_technologies():
    """Fetch active technologies from Baserow (if configured)."""
    if not TECHNOLOGIES_TABLE_ID:
        return []

    print("Fetching technologies from Baserow...")
    technologies = []
    page = 1

    # First, fetch table schema to get field IDs
    try:
        schema_resp = requests.get(
            f"{BASEROW_URL}/api/database/fields/table/{TECHNOLOGIES_TABLE_ID}/",
            headers={"Authorization": f"Token {BASEROW_TOKEN}"}
        )
        schema_resp.raise_for_status()
        fields = schema_resp.json()

        # Map field names to IDs
        field_map = {}
        for field in fields:
            field_name = field.get("name", "").lower()
            field_id = field.get("id")
            if field_name in ["name", "parent", "tracked_repos", "active"]:
                field_map[field_name] = f"field_{field_id}"

        if "name" not in field_map or "tracked_repos" not in field_map:
            print("  WARNING: Technologies table missing required fields (name, tracked_repos)")
            return []

    except Exception as e:
        print(f"  WARNING: Could not fetch technologies table schema: {e}")
        return []

    # Now fetch rows
    while True:
        try:
            response = requests.get(
                f"{BASEROW_URL}/api/database/rows/table/{TECHNOLOGIES_TABLE_ID}/",
                params={
                    "size": 200,
                    "page": page,
                },
                headers={"Authorization": f"Token {BASEROW_TOKEN}"}
            )
            response.raise_for_status()
            data = response.json()

            for row in data["results"]:
                # Check if active (default to True if field doesn't exist)
                active = True
                if "active" in field_map:
                    active = row.get(field_map["active"], True)

                if not active:
                    continue

                name = row.get(field_map["name"], "").strip()
                tracked_repos_raw = row.get(field_map["tracked_repos"]) or ""
                tracked_repos = [r.strip() for r in tracked_repos_raw.strip().splitlines() if r.strip()]

                if name and tracked_repos:
                    parent = ""
                    if "parent" in field_map:
                        parent = row.get(field_map["parent"], "").strip()

                    technologies.append({
                        "name": name,
                        "parent": parent,
                        "tracked_repos": tracked_repos,
                    })

            if not data["next"]:
                break
            page += 1

        except Exception as e:
            print(f"  WARNING: Error fetching technologies: {e}")
            break

    print(f"Found {len(technologies)} active technologies")
    return technologies


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


def collect_events(org_login, cutoff_date, is_individual=False):
    """Fetch org/user events and extract releases and significant pushes."""
    items = []
    # Use different endpoint for individuals vs organizations
    if is_individual:
        endpoint = f"{GITHUB_API}/users/{org_login}/events/public"
    else:
        endpoint = f"{GITHUB_API}/orgs/{org_login}/events"

    resp = github_get(endpoint, {"per_page": 30})
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


def collect_repo_events(repo_full_name, entity_login, cutoff_date):
    """Fetch events for a specific repo and extract releases and significant pushes."""
    items = []
    resp = github_get(f"{GITHUB_API}/repos/{repo_full_name}/events", {"per_page": 30})
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

        if event_type == "ReleaseEvent" and payload.get("action") == "published":
            release = payload.get("release", {})
            items.append({
                "org": entity_login,
                "event_type": "release",
                "repo": repo_full_name,
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
            if not any(ref.endswith(b) for b in ("/main", "/master", "/develop")):
                continue
            commits = payload.get("commits", [])
            num_commits = payload.get("size", len(commits))
            if num_commits <= 1 and commits:
                msg = commits[0].get("message", "")
                if msg.startswith("Merge ") or msg.startswith("chore:"):
                    continue

            branch = ref.split("/")[-1]
            commit_msgs = [c.get("message", "").split("\n")[0][:80] for c in commits[:5]]

            head = payload.get("head", "")
            before = payload.get("before", "")
            if head and before:
                url = f"https://github.com/{repo_full_name}/compare/{before[:7]}...{head[:7]}"
            else:
                url = f"https://github.com/{repo_full_name}/commits/{branch}"

            title = f"{num_commits} commit(s) to {branch}" if num_commits > 0 else f"Push to {branch}"

            items.append({
                "org": entity_login,
                "event_type": "push",
                "repo": repo_full_name,
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
    parser = argparse.ArgumentParser(description="Collect GitHub activity from tracked sources")
    parser.add_argument("--days", type=int, default=30, help="Look back N days (default: 30)")
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "github_activity.json"),
                        help="Output JSON file (default: scripts/github_activity.json)")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"Collecting GitHub activity from the last {args.days} days (since {cutoff.strftime('%Y-%m-%d')})")

    # Get all tracked sources from Baserow
    sources = get_sources()
    technologies = get_technologies()

    all_activity = []
    sources_with_activity = 0
    technologies_with_activity = 0
    api_calls = 0

    print(f"\nScanning {len(sources)} sources...\n")

    for i, src in enumerate(sources):
        login = src["login"]
        src_name = src["name"] or login
        tracked_repos = src["tracked_repos"]
        entity_type = src.get("entity_type")
        is_individual = (entity_type == "individual")

        if tracked_repos:
            # Tracked repos mode: only fetch events for specific repos
            items = []
            for repo in tracked_repos:
                items.extend(collect_repo_events(repo, login, cutoff))
                api_calls += 1
        else:
            # Org-wide mode (or user-wide for individuals): fetch all repos + events (2 API calls)
            new_repos = collect_new_repos(login, cutoff) if not is_individual else []
            events = collect_events(login, cutoff, is_individual=is_individual)
            api_calls += 2 if not is_individual else 1
            items = new_repos + events

        if items:
            sources_with_activity += 1
            for item in items:
                item["org_name"] = src_name
                item["source_type"] = "source"
                if entity_type:
                    item["entity_type"] = entity_type
            all_activity.extend(items)

        # Progress
        if (i + 1) % 20 == 0 or items:
            status = f"  [{i+1}/{len(sources)}] {login}"
            if tracked_repos:
                status += f" (tracked repos: {len(tracked_repos)})"
            if items:
                status += f" -> {len(items)} event(s)"
            print(status)

    # Collect from technologies
    if technologies:
        print(f"\nScanning {len(technologies)} technologies...\n")

        for i, tech in enumerate(technologies):
            tech_name = tech["name"]
            tech_parent = tech["parent"]
            tracked_repos = tech["tracked_repos"]
            items = []

            for repo in tracked_repos:
                # Use repo owner as the "login" for API calls
                repo_owner = repo.split("/")[0] if "/" in repo else repo
                repo_events = collect_repo_events(repo, repo_owner, cutoff)
                api_calls += 1
                items.extend(repo_events)

            if items:
                technologies_with_activity += 1
                for item in items:
                    # Extract org name from repo if not already set
                    if "org_name" not in item or not item["org_name"]:
                        item["org_name"] = item["repo"].split("/")[0] if "/" in item["repo"] else ""
                    item["source_type"] = "technology"
                    item["technology_name"] = tech_name
                    item["technology_parent"] = tech_parent
                all_activity.extend(items)

            # Progress
            if (i + 1) % 10 == 0 or items:
                status = f"  [{i+1}/{len(technologies)}] {tech_name}"
                if tech_parent:
                    status += f" (part of {tech_parent})"
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
    print(f"Sources scanned: {len(sources)}")
    print(f"Sources with activity: {sources_with_activity}")
    if technologies:
        print(f"Technologies scanned: {len(technologies)}")
        print(f"Technologies with activity: {technologies_with_activity}")
    print(f"API calls made: {api_calls}")
    print(f"Total events found: {len(deduped)}")

    by_type = {}
    by_source_type = {}
    for item in deduped:
        by_type[item["event_type"]] = by_type.get(item["event_type"], 0) + 1
        source_type = item.get("source_type", "source")
        by_source_type[source_type] = by_source_type.get(source_type, 0) + 1

    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")

    if len(by_source_type) > 1:
        print(f"\nBy source type:")
        for t, c in sorted(by_source_type.items()):
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
