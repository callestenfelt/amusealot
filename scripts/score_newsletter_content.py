#!/usr/bin/env python3
"""
Score and categorize enriched GitHub activity for the museum tech newsletter.
Sends events to Groq/Llama 3.3 for relevance scoring, summarization, and
newsletter section assignment. Also computes stats and most-active repos.

Usage:
  python score_newsletter_content.py [--input github_activity_enriched.json] [--output scored_newsletter_content.json]

Requires environment variable: GROQ_API_KEY
"""

import sys
import io
import os
import json
import time
import argparse
from datetime import datetime, timezone
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DELAY_BETWEEN_CALLS = 3  # seconds
MAX_RETRIES = 3
PUSH_BATCH_SIZE = 5

SCORING_SYSTEM_PROMPT = """You are a museum technology analyst scoring GitHub activity for a newsletter.

Museum tech domains: IIIF, collection management (Specify, CollectiveAccess), digital preservation, Darwin Core, biodiversity informatics, linked open data, web archives, 3D digitization, accessibility, metadata standards (Dublin Core, MODS, EAD).

Scoring criteria:
- Relevance to museum professionals (1-10)
- Newsworthiness vs routine activity
- Reusability by other museums

Tier definitions:
- Tier 1: Clear museum-tech value, reusable, newsworthy
- Tier 2: Moderately interesting, worth a mention
- Tier 3: Routine (automated updates, CI config, data dumps, trivial patches)"""


def groq_request(messages, json_mode=True):
    """Make a Groq API request with retry on 429."""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2000,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(GROQ_URL, headers=headers, json=body, timeout=30)

            if resp.status_code == 429:
                wait = (attempt + 1) * 10  # 10s, 20s, 30s
                print(f"    Rate limited (429), waiting {wait}s...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if json_mode:
                return json.loads(content), None
            return content, None

        except json.JSONDecodeError as e:
            return None, f"JSON parse error: {e}"
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                continue
            return None, "Timeout"
        except Exception as e:
            return None, str(e)[:200]

    return None, "Max retries exceeded"


def compute_stats(events):
    """Compute pure-count stats from events (no LLM)."""
    orgs = set()
    repos = set()
    pushes = 0
    new_projects = 0
    releases = 0

    for e in events:
        orgs.add(e.get("org", ""))
        repos.add(e.get("repo", ""))
        etype = e["event_type"]
        if etype == "push":
            pushes += 1
        elif etype == "new_repo":
            new_projects += 1
        elif etype == "release":
            releases += 1

    return {
        "active_orgs": len(orgs),
        "total_pushes": pushes,
        "unique_repos": len(repos),
        "new_projects": new_projects,
        "releases": releases,
    }


def compute_most_active(events, top_n=5):
    """Rank repos by total_commits + files_changed from enrichment data."""
    repo_stats = {}

    for e in events:
        if e["event_type"] != "push":
            continue
        repo = e["repo"]
        enrichment = e.get("enrichment", {})
        commits = enrichment.get("total_commits", 0)
        files = enrichment.get("files_changed", 0)

        if repo not in repo_stats:
            repo_stats[repo] = {
                "repo": repo,
                "pushes": 0,
                "total_commits": 0,
                "files_changed": 0,
                "description": (e.get("repo_meta") or {}).get("description", ""),
            }
        repo_stats[repo]["pushes"] += 1
        repo_stats[repo]["total_commits"] += commits
        repo_stats[repo]["files_changed"] += files

    ranked = sorted(repo_stats.values(),
                    key=lambda r: r["total_commits"] + r["files_changed"],
                    reverse=True)
    return ranked[:top_n]


def build_event_summary(event):
    """Build a compact dict for sending to the LLM (strip bulky fields)."""
    summary = {
        "repo": event["repo"],
        "org_name": event.get("org_name", ""),
        "title": event.get("title", ""),
        "description": event.get("description", ""),
        "date": event.get("date", ""),
        "event_type": event["event_type"],
    }

    meta = event.get("repo_meta")
    if meta:
        summary["repo_meta"] = {
            "description": meta.get("description", ""),
            "language": meta.get("language"),
            "topics": meta.get("topics", []),
            "stars": meta.get("stars", 0),
        }

    enrichment = event.get("enrichment")
    if enrichment:
        # Include relevant enrichment based on type
        if event["event_type"] == "push":
            summary["enrichment"] = {
                "total_commits": enrichment.get("total_commits", 0),
                "files_changed": enrichment.get("files_changed", 0),
                "commits": enrichment.get("commits", []),
            }
        elif event["event_type"] == "new_repo":
            readme = enrichment.get("readme_excerpt", "")
            if readme:
                summary["enrichment"] = {"readme_excerpt": readme[:1000]}
        elif event["event_type"] == "release":
            body = enrichment.get("release_body_full", "")
            if body:
                summary["enrichment"] = {"release_body": body[:1000]}

    details = event.get("details")
    if details:
        summary["details"] = details

    return summary


def score_batch(events, event_type):
    """Send a batch of events to the LLM for scoring."""
    summaries = []
    for i, e in enumerate(events):
        s = build_event_summary(e)
        s["index"] = i
        summaries.append(s)

    user_prompt = f"""Score these {event_type} events. Respond with JSON: {{"scores": [...]}}.

{json.dumps(summaries, indent=2, ensure_ascii=False)}

For each event return:
{{"index": N, "relevance": 1-10, "summary": "1-2 sentences", "tier": 1-3, "skip_reason": "reason or null"}}"""

    messages = [
        {"role": "system", "content": SCORING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    result, error = groq_request(messages)
    if error:
        return None, error

    scores = result.get("scores", [])
    return scores, None


def generate_spotlight(event):
    """Generate a 3-4 sentence spotlight writeup for the top event."""
    full_summary = build_event_summary(event)
    # Include full enrichment for spotlight
    if event.get("enrichment"):
        full_summary["enrichment"] = event["enrichment"]

    user_prompt = f"""Write a 3-4 sentence spotlight for a museum tech newsletter about this GitHub activity. Explain what the project does, why it matters for the museum community, and who can benefit. Present tense, active voice, no markdown. Respond with JSON: {{"writeup": "..."}}.

{json.dumps(full_summary, indent=2, ensure_ascii=False)}"""

    messages = [
        {"role": "system", "content": SCORING_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    result, error = groq_request(messages)
    if error:
        return None, error

    return result.get("writeup", ""), None


def assign_section(event_type, tier):
    """Assign newsletter section based on event type and tier."""
    if tier >= 3:
        return None
    return {
        "new_repo": "new_repos",
        "release": "releases",
        "push": "pushes",
    }.get(event_type)


def main():
    script_dir = os.path.dirname(__file__)
    parser = argparse.ArgumentParser(description="Score GitHub activity for newsletter")
    parser.add_argument("--input", default=os.path.join(script_dir, "github_activity_enriched.json"),
                        help="Input JSON (default: scripts/github_activity_enriched.json)")
    parser.add_argument("--output", default=os.path.join(script_dir, "scored_newsletter_content.json"),
                        help="Output JSON (default: scripts/scored_newsletter_content.json)")
    args = parser.parse_args()

    # Load events
    with open(args.input, "r", encoding="utf-8") as f:
        events = json.load(f)

    print(f"Loaded {len(events)} events from {args.input}")

    # Group by type, tracking global index for each event
    by_type = {"push": [], "new_repo": [], "release": []}
    global_index = {}  # id(event) -> index in events list
    for i, e in enumerate(events):
        global_index[id(e)] = i
        etype = e["event_type"]
        if etype in by_type:
            by_type[etype].append(e)

    for t, items in by_type.items():
        print(f"  {t}: {len(items)}")

    # --- Phase 1: Computed sections (no LLM) ---
    print(f"\n{'='*60}")
    print("COMPUTED SECTIONS")
    print(f"{'='*60}")

    stats = compute_stats(events)
    print(f"Stats: {stats}")

    most_active = compute_most_active(events)
    print(f"Most active repos ({len(most_active)}):")
    for r in most_active:
        print(f"  {r['repo']}: {r['total_commits']} commits, {r['files_changed']} files")

    # --- Phase 2: LLM scoring ---
    print(f"\n{'='*60}")
    print("LLM SCORING")
    print(f"{'='*60}")

    api_calls = 0
    scores_map = {}  # index in events list -> score dict

    # Score push events in batches of 5
    push_events = by_type["push"]
    for batch_start in range(0, len(push_events), PUSH_BATCH_SIZE):
        batch = push_events[batch_start:batch_start + PUSH_BATCH_SIZE]
        batch_num = batch_start // PUSH_BATCH_SIZE + 1
        total_batches = (len(push_events) + PUSH_BATCH_SIZE - 1) // PUSH_BATCH_SIZE
        print(f"\n  Push batch {batch_num}/{total_batches} ({len(batch)} events)...")

        scores, error = score_batch(batch, "push")
        api_calls += 1

        if error:
            print(f"    ERROR: {error}")
            # Assign default tier 3 on error
            for e in batch:
                scores_map[global_index[id(e)]] = {"relevance": 1, "summary": "", "tier": 3, "skip_reason": "scoring_error"}
        else:
            for s in scores:
                event_idx_in_batch = s.get("index", 0)
                if event_idx_in_batch < len(batch):
                    global_idx = global_index[id(batch[event_idx_in_batch])]
                    scores_map[global_idx] = s
                    tier_label = f"T{s.get('tier', '?')}"
                    print(f"    [{tier_label}] {batch[event_idx_in_batch]['repo']}: {s.get('summary', '')[:80]}")

        time.sleep(DELAY_BETWEEN_CALLS)

    # Score new_repo events (single batch)
    if by_type["new_repo"]:
        print(f"\n  New repos batch ({len(by_type['new_repo'])} events)...")
        scores, error = score_batch(by_type["new_repo"], "new_repo")
        api_calls += 1

        if error:
            print(f"    ERROR: {error}")
            for e in by_type["new_repo"]:
                scores_map[global_index[id(e)]] = {"relevance": 1, "summary": "", "tier": 3, "skip_reason": "scoring_error"}
        else:
            for s in scores:
                event_idx_in_batch = s.get("index", 0)
                if event_idx_in_batch < len(by_type["new_repo"]):
                    global_idx = global_index[id(by_type["new_repo"][event_idx_in_batch])]
                    scores_map[global_idx] = s
                    tier_label = f"T{s.get('tier', '?')}"
                    print(f"    [{tier_label}] {by_type['new_repo'][event_idx_in_batch]['repo']}: {s.get('summary', '')[:80]}")

        time.sleep(DELAY_BETWEEN_CALLS)

    # Score release events (single batch)
    if by_type["release"]:
        print(f"\n  Releases batch ({len(by_type['release'])} events)...")
        scores, error = score_batch(by_type["release"], "release")
        api_calls += 1

        if error:
            print(f"    ERROR: {error}")
            for e in by_type["release"]:
                scores_map[global_index[id(e)]] = {"relevance": 1, "summary": "", "tier": 3, "skip_reason": "scoring_error"}
        else:
            for s in scores:
                event_idx_in_batch = s.get("index", 0)
                if event_idx_in_batch < len(by_type["release"]):
                    global_idx = global_index[id(by_type["release"][event_idx_in_batch])]
                    scores_map[global_idx] = s
                    tier_label = f"T{s.get('tier', '?')}"
                    print(f"    [{tier_label}] {by_type['release'][event_idx_in_batch]['repo']}: {s.get('summary', '')[:80]}")

        time.sleep(DELAY_BETWEEN_CALLS)

    # --- Phase 3: Section assignment ---
    scored_events = []
    for i, event in enumerate(events):
        score_data = scores_map.get(i, {"relevance": 1, "summary": "", "tier": 3, "skip_reason": "unscored"})
        tier = score_data.get("tier", 3)
        section = assign_section(event["event_type"], tier)

        event["score"] = {
            "relevance": score_data.get("relevance", 1),
            "summary": score_data.get("summary", ""),
            "tier": tier,
            "section": section,
        }
        skip = score_data.get("skip_reason")
        if skip:
            event["score"]["skip_reason"] = skip

        scored_events.append(event)

    # --- Phase 4: Spotlight ---
    print(f"\n{'='*60}")
    print("SPOTLIGHT")
    print(f"{'='*60}")

    # Pick highest-scored event
    best = max(scored_events, key=lambda e: e["score"]["relevance"])
    print(f"  Selected: {best['repo']} (relevance {best['score']['relevance']})")

    spotlight_writeup, error = generate_spotlight(best)
    api_calls += 1

    if error:
        print(f"  Spotlight ERROR: {error}")
        spotlight_writeup = ""
    else:
        print(f"  Writeup: {spotlight_writeup[:120]}...")

    # --- Build output ---
    tier_counts = {"tier_1": 0, "tier_2": 0, "tier_3": 0}
    for e in scored_events:
        t = e["score"]["tier"]
        if t == 1:
            tier_counts["tier_1"] += 1
        elif t == 2:
            tier_counts["tier_2"] += 1
        else:
            tier_counts["tier_3"] += 1

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_file": args.input,
        "model": GROQ_MODEL,
        "stats": stats,
        "most_active": most_active,
        "scored_events": scored_events,
        "spotlight": {
            "event": build_event_summary(best),
            "writeup": spotlight_writeup,
        },
        "summary": {
            "total_events": len(scored_events),
            **tier_counts,
        },
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # --- Summary ---
    print(f"\n{'='*60}")
    print("SCORING SUMMARY")
    print(f"{'='*60}")
    print(f"Events scored: {len(scored_events)}")
    print(f"  Tier 1 (featured): {tier_counts['tier_1']}")
    print(f"  Tier 2 (mentioned): {tier_counts['tier_2']}")
    print(f"  Tier 3 (skipped): {tier_counts['tier_3']}")
    print(f"API calls made: {api_calls}")
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
