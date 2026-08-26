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
import re
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
import requests

from json_cache import load_json_cache, save_json_cache

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

# Cross-edition dedup: event URLs collected by previous SENT editions. The
# 8-day lookback with a 7-day cron cadence guarantees ~1 day of overlap,
# which produced a repeat slot every week without this.
#
# Two-file design: collection (--apply) only writes candidates to the PENDING
# file; the cache itself is committed by a separate --commit-seen invocation
# that run_newsletter.sh makes right after the send step succeeds. A run that
# fails anywhere before the send therefore never burns its events — the
# documented "fix and re-run" recovery re-collects them all.
SEEN_EVENTS_FILE = os.path.join(os.path.dirname(__file__), "github_seen_events.json")
SEEN_EVENTS_PENDING_FILE = os.path.join(os.path.dirname(__file__), "github_seen_events_pending.json")
SEEN_EVENTS_MAX_AGE_DAYS = 30

# Push events without head/before hashes fall back to a per-repo+branch
# commits URL that is identical for every such push — caching one would
# filter all future fallback pushes to that branch for 30 days.
_NON_UNIQUE_URL_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/commits/[^/]+$")


def is_cacheable_url(url):
    """Only durable, per-event-unique URLs may become 30-day cache keys."""
    return bool(url) and not _NON_UNIQUE_URL_RE.match(url)


def save_seen_events(cache):
    """Save the seen-events cache (atomic), pruning entries older than max age."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_EVENTS_MAX_AGE_DAYS)).date().isoformat()
    pruned = {url: seen for url, seen in cache.items() if seen >= cutoff}
    save_json_cache(SEEN_EVENTS_FILE, pruned, "seen-events cache")


def commit_seen_events():
    """Merge the pending file (written by the last --apply collection) into the
    seen-events cache. Called by run_newsletter.sh after a successful send."""
    if not os.path.exists(SEEN_EVENTS_PENDING_FILE):
        print(f"ERROR: No pending seen-events file ({SEEN_EVENTS_PENDING_FILE}) — "
              "was the collection step run with --apply?")
        sys.exit(1)
    pending = load_json_cache(SEEN_EVENTS_PENDING_FILE, "pending seen-events")
    cache = load_json_cache(SEEN_EVENTS_FILE, "seen-events cache")
    added = 0
    for url, first_seen in pending.items():
        if url not in cache:
            cache[url] = first_seen
            added += 1
    save_seen_events(cache)
    os.remove(SEEN_EVENTS_PENDING_FILE)
    print(f"Committed {added} new event URL(s) to the seen-events cache "
          f"({len(pending)} pending, cache now {len(cache)} before pruning)")


# Non-rate-limit 403s (token permission problem, org gone private, abuse
# block without headers). Surfaced per-URL during the run, listed in the
# summary, and — because a couple of oddball sources must not kill the weekly
# send while a systemic token problem must — the run aborts only when several
# accumulate (decision 2026-08-26: surface + systemic abort, not abort-on-any).
FORBIDDEN_403S = []
FORBIDDEN_403S_ABORT_THRESHOLD = 6

API_CALLS = [0]  # module-level so pagination helpers count too


def github_get(url, params=None):
    """Make a GitHub API request with rate limit handling.

    403/429 with Retry-After (secondary rate limit) or an exhausted primary
    quota waits and retries. A 403 that is NOT rate limiting is recorded in
    FORBIDDEN_403S and returned as-is (callers treat non-200 as no data);
    main() surfaces the list and aborts if it grows past the threshold.
    """
    for attempt in range(3):
        API_CALLS[0] += 1
        resp = requests.get(url, params=params, headers=GITHUB_HEADERS, timeout=30)
        if resp.status_code == 401:
            # Bad/expired token. Abort loudly — silent 401s previously produced
            # newsletters with 0 GitHub events.
            raise SystemExit(
                f"GitHub API returned 401 (Bad credentials) for {url}. "
                "Check GITHUB_TOKEN — likely expired, revoked, or missing scopes."
            )
        if resp.status_code not in (403, 429):
            return resp

        retry_after = resp.headers.get("Retry-After")
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if retry_after:
            # Secondary rate limit: GitHub says exactly how long to back off.
            wait = int(retry_after) + 1
            print(f"  Secondary rate limit (HTTP {resp.status_code})! Waiting {wait}s...")
        elif remaining == "0":
            # Primary quota exhausted: wait until the reset timestamp.
            reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            wait = max(reset - time.time(), 0) + 2
            print(f"  Rate limited! Waiting {wait:.0f}s...")
        else:
            # 403 with quota left and no Retry-After: not rate limiting —
            # permissions/visibility problem. Surface it, don't retry.
            FORBIDDEN_403S.append(url)
            print(f"  WARNING: GitHub returned 403 (not rate-limited) for {url} — "
                  "token permissions or source visibility problem")
            return resp
        time.sleep(wait)

    raise SystemExit(
        f"GitHub rate limit did not clear after 3 waits for {url} — aborting "
        "so the pipeline retries instead of shipping a thin edition."
    )


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
            headers={"Authorization": f"Token {BASEROW_TOKEN}"},
            timeout=30,
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
            headers={"Authorization": f"Token {BASEROW_TOKEN}"},
            timeout=30,
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
                headers={"Authorization": f"Token {BASEROW_TOKEN}"},
                timeout=30,
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


def collect_new_repos(org_login, cutoff_date, max_pages=3):
    """Find repos created after cutoff_date for an org.

    Paginated (created-desc, so we stop at the first repo older than the
    cutoff): the old per_page=10 single fetch meant an org creating >10
    repos in a week — or forks padding the first 10 — silently hid the rest.
    """
    items = []
    for page in range(1, max_pages + 1):
        resp = github_get(f"{GITHUB_API}/orgs/{org_login}/repos",
                          {"sort": "created", "direction": "desc",
                           "per_page": 100, "page": page})
        if resp.status_code != 200:
            return items

        repos = resp.json()
        for repo in repos:
            created = repo.get("created_at", "")
            if not created:
                continue
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if created_dt < cutoff_date:
                return items  # Sorted by created desc, so no more new ones
            if repo.get("fork"):
                continue

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

        if len(repos) < 100:
            return items  # last page

    return items


def _extract_event(event, org_label, cutoff_date, repo_override=None):
    """Turn a GitHub event into a release/push item, or None if not noteworthy.

    Shared by collect_events (org/user feed) and collect_repo_events (single-repo
    feed); repo_override pins the repo name for the single-repo case.
    """
    event_date = event.get("created_at", "")
    if not event_date:
        return None
    event_dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
    if event_dt < cutoff_date:
        return None

    actor = event.get("actor", {}).get("login", "")
    if actor in BOT_AUTHORS:
        return None

    event_type = event.get("type")
    payload = event.get("payload", {})
    repo_name = repo_override or event.get("repo", {}).get("name", "")

    if event_type == "ReleaseEvent" and payload.get("action") == "published":
        release = payload.get("release", {})
        return {
            "org": org_label,
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
        }

    if event_type == "PushEvent":
        ref = payload.get("ref", "")
        # Only default branches
        if not any(ref.endswith(b) for b in ("/main", "/master", "/develop")):
            return None
        commits = payload.get("commits", [])
        num_commits = payload.get("size", len(commits))
        # Skip trivial pushes (1 commit that's a merge or CI)
        if num_commits <= 1 and commits:
            msg = commits[0].get("message", "")
            if msg.startswith("Merge ") or msg.startswith("chore:"):
                return None

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

        return {
            "org": org_label,
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
        }

    return None


def _paged_events(endpoint, cutoff_date, max_pages=3):
    """Fetch an events feed page by page until it reaches the cutoff date.

    per_page=100 with date-based continuation replaces the old single
    per_page=30 fetch, where a burst of bot events (dependabot etc.) could
    fill the window and hide real activity — the stop decision is now the
    timestamp of the last event on the page, never the item count. GitHub
    caps event feeds at 300 events / 3 pages at this page size.
    """
    events = []
    for page in range(1, max_pages + 1):
        resp = github_get(endpoint, {"per_page": 100, "page": page})
        if resp.status_code != 200:
            break  # 404/410 (no events, gone) tolerated; 403 surfaced in github_get
        page_events = resp.json()
        if not page_events:
            break
        events.extend(page_events)
        last_date = page_events[-1].get("created_at", "")
        if last_date and datetime.fromisoformat(last_date.replace("Z", "+00:00")) < cutoff_date:
            break  # feed is newest-first; the rest is older than the window
        if len(page_events) < 100:
            break  # last page
    return events


def collect_events(org_login, cutoff_date, is_individual=False):
    """Fetch org/user events and extract releases and significant pushes."""
    # Use different endpoint for individuals vs organizations
    if is_individual:
        endpoint = f"{GITHUB_API}/users/{org_login}/events/public"
    else:
        endpoint = f"{GITHUB_API}/orgs/{org_login}/events"

    items = []
    for event in _paged_events(endpoint, cutoff_date):
        item = _extract_event(event, org_login, cutoff_date)
        if item:
            items.append(item)
    return items


def collect_repo_events(repo_full_name, entity_login, cutoff_date):
    """Fetch events for a specific repo and extract releases and significant pushes."""
    items = []
    for event in _paged_events(f"{GITHUB_API}/repos/{repo_full_name}/events", cutoff_date):
        item = _extract_event(event, entity_login, cutoff_date, repo_override=repo_full_name)
        if item:
            items.append(item)
    return items


def main():
    parser = argparse.ArgumentParser(description="Collect GitHub activity from tracked sources")
    parser.add_argument("--days", type=int, default=30, help="Look back N days (default: 30)")
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "github_activity.json"),
                        help="Output JSON file (default: scripts/github_activity.json)")
    parser.add_argument("--apply", action="store_true",
                        help="Record collected event URLs to the pending seen-events file "
                             "(committed to the cache by --commit-seen after a successful "
                             "send; default: dry-run records nothing)")
    parser.add_argument("--commit-seen", action="store_true",
                        help="Commit the pending seen-events file into the cache and exit "
                             "(run by the pipeline after the send step succeeds)")
    args = parser.parse_args()

    if args.commit_seen:
        commit_seen_events()
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"Collecting GitHub activity from the last {args.days} days (since {cutoff.strftime('%Y-%m-%d')})")

    # Get all tracked sources from Baserow
    sources = get_sources()
    technologies = get_technologies()

    all_activity = []
    sources_with_activity = 0
    technologies_with_activity = 0

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
        else:
            # Org-wide mode (or user-wide for individuals): fetch all repos + events
            new_repos = collect_new_repos(login, cutoff) if not is_individual else []
            events = collect_events(login, cutoff, is_individual=is_individual)
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
                items.extend(collect_repo_events(repo, repo_owner, cutoff))

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

    # Non-rate-limit 403s: surface every affected URL, and abort (before any
    # output or pending-cache write) if enough accumulated to look systemic —
    # a bad token scope 403s everything, and shipping "0 events" silently is
    # exactly the failure mode this pipeline is built to refuse.
    if FORBIDDEN_403S:
        print(f"\n{'!'*60}")
        print(f"WARNING: {len(FORBIDDEN_403S)} GitHub URL(s) returned non-rate-limit 403:")
        for url in FORBIDDEN_403S:
            print(f"  {url}")
        print("Check token permissions / source visibility for these.")
        print(f"{'!'*60}")
        if len(FORBIDDEN_403S) >= FORBIDDEN_403S_ABORT_THRESHOLD:
            raise SystemExit(
                f"{len(FORBIDDEN_403S)} forbidden responses (threshold "
                f"{FORBIDDEN_403S_ABORT_THRESHOLD}) — looks systemic (token "
                "permissions?). Aborting so the pipeline is retried."
            )

    # Cross-edition dedup: drop events already collected by a previously SENT
    # edition (the lookback window overlaps the weekly cadence by ~1 day).
    # Only cacheable URLs are ever in the cache, but guard anyway so an empty
    # or fallback URL can never match a cache key.
    seen_events = load_json_cache(SEEN_EVENTS_FILE, "seen-events cache")
    before_cross = len(all_activity)
    all_activity = [item for item in all_activity
                    if not (is_cacheable_url(item["url"]) and item["url"] in seen_events)]
    if before_cross != len(all_activity):
        print(f"\nFiltered {before_cross - len(all_activity)} event(s) already "
              f"collected by a previous edition")

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

    # Record this run's candidates to the PENDING file — from the pre-collapse
    # list (all_activity), not `deduped`: a push superseded by push_best in
    # this run must still be cached, or it resurfaces and wins next week's
    # uncontested election as a stale repeat. Cache commit happens only after
    # the send succeeds (--commit-seen), so a failed run burns nothing; and
    # only on --apply, so a dry run can't hide events from the next real run.
    if args.apply:
        today = datetime.now(timezone.utc).date().isoformat()
        pending = {item["url"]: today for item in all_activity
                   if is_cacheable_url(item["url"])}
        save_json_cache(SEEN_EVENTS_PENDING_FILE, pending, "pending seen-events")
        print(f"\nRecorded {len(pending)} event URL(s) to the pending seen-events file")
    else:
        print("\n[DRY RUN] Not recording pending seen-events")

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
    print(f"API calls made: {API_CALLS[0]}")
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
