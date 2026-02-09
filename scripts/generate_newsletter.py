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
from datetime import date

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


def main():
    script_dir = os.path.dirname(__file__)
    default_output = os.path.join(script_dir, f"newsletter_{date.today().isoformat()}.html")

    parser = argparse.ArgumentParser(description="Generate HTML newsletter from scored content")
    parser.add_argument("--input", default=os.path.join(script_dir, "scored_newsletter_content.json"),
                        help="Input scored JSON (default: scripts/scored_newsletter_content.json)")
    parser.add_argument("--output", default=default_output,
                        help="Output HTML file (default: scripts/newsletter_YYYY-MM-DD.html)")
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


if __name__ == "__main__":
    main()
