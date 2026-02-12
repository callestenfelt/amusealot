#!/usr/bin/env python3
"""
Generate an HTML newsletter from scored museum tech GitHub activity.

Usage:
  python generate_newsletter.py [--input scored_newsletter_content.json] [--output newsletter_YYYY-MM-DD.html]

No environment variables needed.
"""

import sys
import io
import os
import json
import argparse
from datetime import date, datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    print("ERROR: jinja2 is required. Install with: pip install jinja2")
    sys.exit(1)


def prepare_sections(scored_events):
    """Group T1/T2 events by section, deduplicate per repo, sorted by relevance."""
    sections = {"new_repos": [], "releases": [], "pushes": []}

    for event in scored_events:
        score = event.get("score", {})
        tier = score.get("tier", 3)
        section = score.get("section")

        if tier <= 2 and section in sections:
            sections[section].append(event)

    # Deduplicate: keep only the highest-relevance event per repo in each section
    for key in sections:
        seen = {}
        for event in sections[key]:
            repo = event.get("repo", "")
            relevance = event.get("score", {}).get("relevance", 0)
            if repo not in seen or relevance > seen[repo].get("score", {}).get("relevance", 0):
                seen[repo] = event
        sections[key] = list(seen.values())

    # Sort each section: tier 1 before tier 2, then by relevance descending
    for key in sections:
        sections[key].sort(key=lambda e: (e["score"]["tier"], -e["score"]["relevance"]))

    return sections


def build_context(data):
    """Assemble full template context from scored newsletter data."""
    sections = prepare_sections(data["scored_events"])

    return {
        "generation_date": date.today().strftime("%B %d, %Y"),
        "generation_date_iso": date.today().isoformat(),
        "stats": data["stats"],
        "most_active": data["most_active"],
        "spotlight": data["spotlight"],
        "sections": sections,
        "has_new_repos": len(sections["new_repos"]) > 0,
        "has_releases": len(sections["releases"]) > 0,
        "has_pushes": len(sections["pushes"]) > 0,
    }


def render_newsletter(context):
    """Render the Jinja2 template with the given context."""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("newsletter.html.j2")
    return template.render(context)


def register_edition(context, file_name):
    """Register this edition in the Baserow editions table. Gracefully skips if not configured."""
    baserow_url = os.environ.get("BASEROW_URL")
    baserow_token = os.environ.get("BASEROW_TOKEN")
    edition_table_id = os.environ.get("EDITION_TABLE_ID")

    if not all([baserow_url, baserow_token, edition_table_id]):
        print("\nEdition registration skipped (EDITION_TABLE_ID not set)")
        return

    try:
        import requests
    except ImportError:
        print("\nEdition registration skipped (requests not installed)")
        return

    headers = {
        "Authorization": f"Token {baserow_token}",
        "Content-Type": "application/json",
    }

    spotlight = context.get("spotlight", {})
    spotlight_event = spotlight.get("event", {})
    stats = context.get("stats", {})

    row_data = {
        "edition_label": f"Edition — {context['generation_date_iso']}",
        "edition_date": context["generation_date_iso"],
        "spotlight_repo": spotlight_event.get("repo", ""),
        "spotlight_org": spotlight_event.get("org_name", ""),
        "spotlight_summary": spotlight.get("writeup", ""),
        "stats_active_orgs": stats.get("active_orgs", 0),
        "stats_total_pushes": stats.get("total_pushes", 0),
        "stats_unique_repos": stats.get("unique_repos", 0),
        "stats_new_projects": stats.get("new_projects", 0),
        "stats_releases": stats.get("releases", 0),
        "file_name": file_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        url = f"{baserow_url}/api/database/rows/table/{edition_table_id}/"
        resp = requests.post(url, json=row_data, params={"user_field_names": "true"}, headers=headers)
        resp.raise_for_status()
        print(f"\nEdition registered in Baserow (row {resp.json().get('id')})")
    except Exception as e:
        print(f"\nWARNING: Failed to register edition in Baserow: {e}")


def main():
    script_dir = os.path.dirname(__file__)
    editions_dir = os.path.join(script_dir, "editions")
    os.makedirs(editions_dir, exist_ok=True)
    file_name = f"newsletter_{date.today().isoformat()}.html"
    default_output = os.path.join(editions_dir, file_name)

    parser = argparse.ArgumentParser(description="Generate HTML newsletter from scored content")
    parser.add_argument("--input", default=os.path.join(script_dir, "scored_newsletter_content.json"),
                        help="Input scored JSON (default: scripts/scored_newsletter_content.json)")
    parser.add_argument("--output", default=default_output,
                        help="Output HTML file (default: scripts/editions/newsletter_YYYY-MM-DD.html)")
    args = parser.parse_args()

    # Load scored data
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded scored data from {args.input}")
    print(f"  Events: {len(data['scored_events'])}")
    print(f"  Stats: {data['stats']}")

    # Build context and render
    context = build_context(data)

    print(f"\nSections:")
    print(f"  New Repos: {len(context['sections']['new_repos'])} events")
    print(f"  Releases:  {len(context['sections']['releases'])} events")
    print(f"  Pushes:    {len(context['sections']['pushes'])} events")

    html = render_newsletter(context)

    # Write output
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(args.output) / 1024
    print(f"\nNewsletter written to {args.output}")
    print(f"  Size: {size_kb:.1f} KB {'(OK)' if size_kb < 102 else '(WARNING: exceeds Gmail 102KB limit)'}")

    # Register edition in Baserow
    output_file_name = os.path.basename(args.output)
    register_edition(context, output_file_name)


if __name__ == "__main__":
    main()
