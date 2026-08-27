#!/usr/bin/env python3
"""
Enrich GitHub activity events with detailed metadata.
Takes skeleton events from collect_github_activity.py and adds:
  - Repo metadata (description, language, topics, stars, etc.)
  - Compare view details for push events (commits, files changed)
  - README excerpts for new repos
  - Full release bodies for truncated releases

Usage:
  python enrich_github_activity.py [--input github_activity.json] [--output github_activity_enriched.json]

Requires environment variable: GITHUB_TOKEN
"""

import sys
import io
import os
import json
import time
import re
import base64
import argparse
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"Bearer {GITHUB_TOKEN}",
}

api_calls = 0


def github_get(url, params=None):
    """Make a GitHub API request with rate limit handling."""
    global api_calls
    api_calls += 1
    resp = requests.get(url, params=params, headers=GITHUB_HEADERS, timeout=30)
    if resp.status_code == 401:
        # Bad/expired token — abort loudly, matching collect_github_activity.py
        # (a silent 401 here would just produce un-enriched events).
        raise SystemExit(
            f"GitHub API returned 401 (Bad credentials) for {url}. "
            "Check GITHUB_TOKEN — likely expired, revoked, or missing scopes."
        )
    if resp.status_code == 403:
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset - time.time(), 0) + 2
        print(f"  Rate limited! Waiting {wait:.0f}s...")
        time.sleep(wait)
        resp = requests.get(url, params=params, headers=GITHUB_HEADERS, timeout=30)
    return resp


def fetch_repo_metadata(repo_full_name, cache):
    """Fetch repo metadata, using cache to avoid duplicate calls."""
    if repo_full_name in cache:
        return cache[repo_full_name]

    resp = github_get(f"{GITHUB_API}/repos/{repo_full_name}")
    if resp.status_code != 200:
        print(f"    Repo metadata {resp.status_code} for {repo_full_name}")
        cache[repo_full_name] = None
        return None

    repo = resp.json()
    meta = {
        "description": repo.get("description") or "",
        "language": repo.get("language"),
        "topics": repo.get("topics", []),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "license": (repo.get("license") or {}).get("spdx_id"),
        "homepage": repo.get("homepage") or "",
        "created_at": (repo.get("created_at") or "")[:10],
        "open_issues": repo.get("open_issues_count", 0),
    }
    cache[repo_full_name] = meta
    return meta


def enrich_push(event):
    """Fetch compare view for a push event."""
    url = event.get("url", "")

    # Parse base...head hashes from compare URL
    match = re.search(r'/compare/([0-9a-f]+)\.\.\.([0-9a-f]+)', url)
    if not match:
        # URL is commits/branch format — no hashes available
        return None

    base, head = match.group(1), match.group(2)
    repo = event["repo"]

    resp = github_get(f"{GITHUB_API}/repos/{repo}/compare/{base}...{head}")
    if resp.status_code == 404:
        print(f"    Compare 404 for {repo} (commits may be force-pushed away)")
        return None
    if resp.status_code != 200:
        print(f"    Compare {resp.status_code} for {repo}")
        return None

    data = resp.json()
    commits = []
    for c in data.get("commits", [])[:10]:
        commits.append({
            "message": (c.get("commit", {}).get("message") or "").split("\n")[0][:120],
            "author": (c.get("author") or {}).get("login") or c.get("commit", {}).get("author", {}).get("name", ""),
        })

    return {
        "total_commits": data.get("total_commits", 0),
        "commits": commits,
        "files_changed": len(data.get("files", [])),
        "additions": sum(f.get("additions", 0) for f in data.get("files", [])),
        "deletions": sum(f.get("deletions", 0) for f in data.get("files", [])),
    }


def enrich_new_repo(event):
    """Fetch README for a new repo."""
    repo = event["repo"]
    resp = github_get(f"{GITHUB_API}/repos/{repo}/readme")
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        print(f"    README {resp.status_code} for {repo}")
        return None

    data = resp.json()
    content_b64 = data.get("content", "")
    try:
        content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except Exception:
        return None

    return {
        "readme_excerpt": content[:2000],
    }


def enrich_release(event):
    """Fetch full release body if it was truncated."""
    # The collector's explicit flag is the only truth source. No legacy
    # length heuristic: github_activity.json is transient per-run output
    # (collected and enriched inside the same run_newsletter.sh invocation),
    # so pre-flag JSON never reaches this code.
    if not event.get("details", {}).get("description_truncated"):
        return None

    repo = event["repo"]
    tag = event.get("details", {}).get("tag", "")
    if not tag:
        return None

    resp = github_get(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}")
    if resp.status_code != 200:
        print(f"    Release {resp.status_code} for {repo} tag {tag}")
        return None

    body = resp.json().get("body") or ""
    return {
        "release_body_full": body[:2000],
    }


def main():
    script_dir = os.path.dirname(__file__)
    parser = argparse.ArgumentParser(description="Enrich GitHub activity events with API details")
    parser.add_argument("--input", default=os.path.join(script_dir, "github_activity.json"),
                        help="Input JSON file (default: scripts/github_activity.json)")
    parser.add_argument("--output", default=os.path.join(script_dir, "github_activity_enriched.json"),
                        help="Output JSON file (default: scripts/github_activity_enriched.json)")
    args = parser.parse_args()

    # Load events
    with open(args.input, "r", encoding="utf-8") as f:
        events = json.load(f)

    print(f"Loaded {len(events)} events from {args.input}")

    # Count by type
    by_type = {}
    for e in events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")

    repo_cache = {}
    enriched_count = {"repo_meta": 0, "push": 0, "new_repo": 0, "release": 0}

    print(f"\nEnriching events...\n")

    for i, event in enumerate(events):
        repo = event["repo"]
        etype = event["event_type"]
        label = f"  [{i+1}/{len(events)}] {etype:10s} {repo}"

        # 1. Repo metadata (all events)
        meta = fetch_repo_metadata(repo, repo_cache)
        if meta:
            event["repo_meta"] = meta
            enriched_count["repo_meta"] += 1

        # 2. Event-specific enrichment
        enrichment = {}

        if etype == "push":
            result = enrich_push(event)
            if result:
                enrichment.update(result)
                enriched_count["push"] += 1
                label += f" -> {result['total_commits']} commits, {result['files_changed']} files"

        elif etype == "new_repo":
            result = enrich_new_repo(event)
            if result:
                enrichment.update(result)
                enriched_count["new_repo"] += 1
                label += f" -> README {len(result['readme_excerpt'])} chars"

        elif etype == "release":
            result = enrich_release(event)
            if result:
                enrichment.update(result)
                enriched_count["release"] += 1
                label += " -> full body fetched"

        if enrichment:
            event["enrichment"] = enrichment

        print(label)

    # Save
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'='*60}")
    print("ENRICHMENT SUMMARY")
    print(f"{'='*60}")
    print(f"Events processed: {len(events)}")
    print(f"Unique repos: {len(repo_cache)}")
    print(f"Repo metadata added: {enriched_count['repo_meta']}")
    print(f"Push events enriched: {enriched_count['push']}")
    print(f"New repos with README: {enriched_count['new_repo']}")
    print(f"Releases with full body: {enriched_count['release']}")
    print(f"API calls made: {api_calls}")

    try:
        resp = requests.get(f"{GITHUB_API}/rate_limit", headers=GITHUB_HEADERS, timeout=10)
        if resp.status_code == 200:
            rate = resp.json().get("rate", {})
            print(f"Rate limit: {rate.get('remaining', '?')}/{rate.get('limit', '?')} remaining")
    except Exception:
        pass

    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
