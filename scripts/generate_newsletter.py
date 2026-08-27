#!/usr/bin/env python3
"""
Generate an HTML newsletter from scored museum tech GitHub activity.

Produces two files per edition:
  - Full version (archive): newsletter_YYYY-MM-DD.html
  - Email version (truncated pushes): newsletter_email_YYYY-MM-DD.html

Usage:
  python generate_newsletter.py [--input scored_newsletter_content.json] [--test] [--apply]

Default is dry-run: writes newsletter_test.html / newsletter_email_test.html and
skips latest_news.json + Baserow registration. --apply writes the dated edition
files and registers the edition.

No environment variables needed (except for Baserow registration in non-test mode).
"""

import sys
import io
import os
import re
import json
import argparse
from datetime import date, datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

try:
    from jinja2 import Environment, FileSystemLoader
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


def prepare_individual_events(scored_events):
    """Filter and prepare events from individual contributors (Tier 1-2)."""
    # Filter for individual contributors with tier 1 or 2
    individual_events = []

    for event in scored_events:
        # Check if this is from an individual (entity_type field or source metadata)
        # The entity_type field ID is field_7225, with individual = 3090
        # We need to check the enrichment data or source metadata
        source_type = event.get("source_type", "source")

        # For now, we'll need to check if the org_name matches an individual in Baserow
        # This requires the entity_type to be passed through from collection
        # Let's add a simpler check: look for events from known individuals

        score = event.get("score", {})
        tier = score.get("tier", 3)

        # Only tier 1 and 2
        if tier > 2:
            continue

        # Check if this is from an individual source
        # This will be set during collection if we track entity_type
        entity_type = event.get("entity_type")
        if entity_type == "individual":
            individual_events.append(event)

    # Deduplicate by repo, keeping highest relevance
    seen = {}
    for event in individual_events:
        repo = event.get("repo", "")
        relevance = event.get("score", {}).get("relevance", 0)
        if repo not in seen or relevance > seen[repo].get("score", {}).get("relevance", 0):
            seen[repo] = event

    individual_events = list(seen.values())

    # Sort: tier 1 before tier 2, then by relevance
    individual_events.sort(key=lambda e: (e["score"]["tier"], -e["score"]["relevance"]))

    return individual_events


def get_source_stats():
    """Get source counts from Baserow — same logic as /sources page."""
    try:
        import requests
        baserow_url = os.environ.get("BASEROW_URL")
        baserow_token = os.environ.get("BASEROW_TOKEN")
        sources_table_id = os.environ.get("SOURCES_TABLE_ID")

        if not all([baserow_url, baserow_token, sources_table_id]):
            return {"total_sources": 0, "total_countries": 0}

        from baserow_config import SOURCES_FIELDS
        from baserow_client import list_rows

        rows = list_rows(
            sources_table_id,
            filters={f"filter__{SOURCES_FIELDS['github']}__not_empty": "true"},
            user_field_names=False,
        )
        countries = set()
        for row in rows:
            country = row.get(SOURCES_FIELDS["country"]) or ""
            if isinstance(country, dict):
                country = country.get("value", "")
            if country:
                countries.add(country)

        return {"total_sources": len(rows), "total_countries": len(countries)}
    except Exception as e:
        print(f"Warning: Could not fetch source stats: {e}")
        return {"total_sources": 0, "total_countries": 0}


def prepare_news_articles(news_articles, cap=None):
    """Filter and prepare news articles by tier. Max 1 per source. Cap if specified."""
    # Defense-in-depth: collect_news refuses non-http(s) URLs at the source,
    # but older JSON files may predate that guard — never let one become an
    # <a href> in the rendered newsletter or the landing-page JSON.
    news_articles = [a for a in news_articles
                     if str(a.get("url", "")).startswith(("http://", "https://"))]
    tier1 = [a for a in news_articles if a.get("score", {}).get("tier") == 1]
    tier2 = [a for a in news_articles if a.get("score", {}).get("tier") == 2]

    # Sort by relevance score (descending)
    tier1.sort(key=lambda a: a.get("score", {}).get("relevance", 0), reverse=True)
    tier2.sort(key=lambda a: a.get("score", {}).get("relevance", 0), reverse=True)

    # Combine tier 1 and tier 2, filter to max 1 per source
    all_news = tier1 + tier2
    seen_sources = set()
    filtered_news = []

    for article in all_news:
        source = article.get("source_name", "")
        if source not in seen_sources:
            seen_sources.add(source)
            filtered_news.append(article)

    newsletter = filtered_news[:cap] if cap else filtered_news
    return {
        "newsletter": newsletter,
        "total": len(filtered_news)
    }


def build_context(data, section_cap=None, news_data=None, source_stats=None):
    """Assemble full template context from scored newsletter data.

    section_cap: if set, caps every variable-size section to this many items
                 (new_repos/releases/pushes/news via the template's loop cap;
                 individual_events and tool_watch sliced here) and shows
                 "see all" links. None = full/archive version (no cap).
    source_stats: pass a pre-fetched stats dict to avoid re-hitting Baserow
                  (the 102KB auto-tighten loop rebuilds the context per cap).
    """
    sections = prepare_sections(data["scored_events"])
    tool_watch = data.get("tool_watch", {})
    individual_events = prepare_individual_events(data["scored_events"])

    if source_stats is None:
        source_stats = get_source_stats()

    # Prepare news articles if provided
    news_articles = {"newsletter": [], "total": 0}
    if news_data:
        news_articles = prepare_news_articles(news_data, cap=section_cap)

    # Get total counts for sections (for "see all" links)
    total_new_repos = len(sections["new_repos"])
    total_releases = len(sections["releases"])
    total_pushes = len(sections["pushes"])

    # Individual creators and tool watch have no in-template loop cap, so the
    # 102KB auto-tighten gate must bound them here or it could never converge
    # on a week where those sections dominate the size. The full/archive
    # version (section_cap=None) is untouched.
    total_individual_events = len(individual_events)
    total_tool_events = sum(len(events) for events in tool_watch.values())
    if section_cap:
        individual_events = individual_events[:section_cap]
        tool_watch = {parent: events[:section_cap]
                      for parent, events in list(tool_watch.items())[:section_cap]}
    shown_tool_events = sum(len(events) for events in tool_watch.values())

    ctx = {
        "generation_date": date.today().strftime("%B %d, %Y"),
        "generation_date_iso": date.today().isoformat(),
        "stats": data["stats"],
        "most_active": data["most_active"],
        "spotlight": data["spotlight"],
        "sections": sections,
        "total_new_repos": total_new_repos,
        "total_releases": total_releases,
        "total_pushes": total_pushes,
        "has_new_repos": total_new_repos > 0,
        "has_releases": total_releases > 0,
        "has_pushes": total_pushes > 0,
        "has_tool_watch": len(tool_watch) > 0,
        "tool_watch": tool_watch,
        "total_tool_events": total_tool_events,
        "shown_tool_events": shown_tool_events,
        "individual_events": individual_events,
        "has_individual_events": len(individual_events) > 0,
        "total_individual_events": total_individual_events,
        "news_articles": news_articles,
        "has_news": len(news_articles["newsletter"]) > 0,
        "section_cap": section_cap,
        "source_stats": source_stats,
    }
    return ctx


_template = None


def render_newsletter(context):
    """Render the Jinja2 template with the given context."""
    global _template
    if _template is None:
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        # autoescape=True (not select_autoescape(["html"])) because the template is
        # named newsletter.html.j2 — select_autoescape matches on the final extension
        # (".j2"), so it would leave escaping OFF and render RSS titles / AI summaries
        # raw. Literal HTML in the template is unaffected; "What's new" opts back out
        # with an explicit | safe.
        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _template = env.get_template("newsletter.html.j2")
    return _template.render(context)


def find_edition_row(baserow_url, headers, edition_table_id, edition_date):
    """Return the row id of an existing edition row for this date, or None."""
    import requests
    # Server-side filter: one GET instead of paging the whole editions table.
    resp = requests.get(
        f"{baserow_url}/api/database/rows/table/{edition_table_id}/",
        params={
            "size": 10,
            "user_field_names": "true",
            "filter__edition_date__equal": edition_date,
        },
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None


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

    # Re-runs on the same day must update the existing row, not add a duplicate.
    # A failed lookup must not cancel registration though: fall through to POST —
    # a possible duplicate row is far more recoverable than a silently missing
    # archive entry.
    try:
        existing_id = find_edition_row(baserow_url, headers, edition_table_id,
                                       context["generation_date_iso"])
    except Exception as e:
        print(f"\nWARNING: Edition lookup failed ({e}) — registering a new row anyway")
        existing_id = None

    try:
        if existing_id:
            url = f"{baserow_url}/api/database/rows/table/{edition_table_id}/{existing_id}/"
            resp = requests.patch(url, json=row_data, params={"user_field_names": "true"}, headers=headers, timeout=10)
            resp.raise_for_status()
            print(f"\nEdition already registered for {context['generation_date_iso']} — updated row {existing_id}")
        else:
            url = f"{baserow_url}/api/database/rows/table/{edition_table_id}/"
            resp = requests.post(url, json=row_data, params={"user_field_names": "true"}, headers=headers, timeout=10)
            resp.raise_for_status()
            print(f"\nEdition registered in Baserow (row {resp.json().get('id')})")
    except Exception as e:
        print(f"\nWARNING: Failed to register edition in Baserow: {e}")


def main():
    script_dir = os.path.dirname(__file__)
    editions_dir = os.path.join(script_dir, "editions")
    os.makedirs(editions_dir, exist_ok=True)
    today_iso = date.today().isoformat()

    parser = argparse.ArgumentParser(description="Generate HTML newsletter from scored content")
    parser.add_argument("--input", default=os.path.join(script_dir, "scored_newsletter_content.json"),
                        help="Input scored JSON (default: scripts/scored_newsletter_content.json)")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: write to newsletter_test.html, skip Baserow registration")
    parser.add_argument("--apply", action="store_true",
                        help="Write dated edition files, latest_news.json, and register the "
                             "edition in Baserow (default: dry-run — test filenames, no "
                             "registration, no latest_news.json)")
    args = parser.parse_args()

    # One boolean gates every real side effect (dated files, latest_news.json,
    # Baserow registration). --test wins over --apply, and no --apply is a
    # dry-run: both write test filenames and touch nothing else.
    apply = args.apply and not args.test
    if not args.apply and not args.test:
        print("\n⚠️  DRY RUN MODE - Use --apply to write dated edition files and register the edition\n")

    # Load scored data
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded scored data from {args.input}")
    print(f"  Events: {len(data['scored_events'])}")
    print(f"  Stats: {data['stats']}")

    # Load optional news articles
    news_path = os.path.join(script_dir, "news_articles_scored.json")
    news_articles = []
    if os.path.exists(news_path):
        with open(news_path, "r", encoding="utf-8") as f:
            news_articles = json.load(f)
        print(f"  News articles: {len(news_articles)}")
    else:
        print("  No news articles found (news_articles_scored.json missing)")

    # Load optional "What's new" items
    whats_new_path = os.path.join(script_dir, "whats_new.txt")
    whats_new = []
    if os.path.exists(whats_new_path):
        with open(whats_new_path, "r", encoding="utf-8") as f:
            whats_new = [line.strip() for line in f if line.strip()]

    # Fetch source stats ONCE — the 102KB auto-tighten loop below rebuilds the
    # email context per cap, and each build_context would otherwise re-page the
    # whole Baserow sources table (and a mid-loop blip would ship an email whose
    # stats tiles contradict the whats_new text substituted here).
    source_stats = get_source_stats()
    if source_stats["total_sources"] == 0:
        print("  Warning: source stats unavailable (BASEROW credentials missing?) — the corpus footnote line will be omitted from the newsletter")

    # Build context — full/archive version (no cap)
    context = build_context(data, news_data=news_articles, source_stats=source_stats)

    # Substitute source stats into whats_new lines (supports {{ total_sources }}
    # and {{ total_countries }}). A line is dropped when a stat it needs is
    # unavailable — better no line than "0 sources". Any anchor without an
    # inline style then gets the email link style (paired with the card
    # What's-new box background per the CLAUDE.md rule), since email clients
    # that need inlining ignore the <style> block.
    link_style = "color:#080229;background-color:#FAF9F6;text-decoration:underline;text-underline-offset:2px;"
    token_values = {
        "{{ total_sources }}": source_stats.get("total_sources", 0),
        "{{ total_countries }}": source_stats.get("total_countries", 0),
    }

    def style_anchor(match):
        attrs = match.group(1).strip()
        if "style=" in attrs:
            return match.group(0)
        return f'<a {attrs} style="{link_style}">'

    processed = []
    for line in whats_new:
        missing = [tok for tok, val in token_values.items() if tok in line and not val]
        if missing:
            print(f"  Skipping whats_new line ({missing[0]} unavailable): {line[:60]}")
            continue
        for tok, val in token_values.items():
            line = line.replace(tok, str(val))
        line = re.sub(r"<a\s+([^>]+?)\s*>", style_anchor, line)
        processed.append(line)
    whats_new = processed
    context["whats_new"] = whats_new

    print(f"\nSections:")
    print(f"  New Repos: {len(context['sections']['new_repos'])} events")
    print(f"  Releases:  {len(context['sections']['releases'])} events")
    print(f"  Pushes:    {len(context['sections']['pushes'])} events")
    if context['has_tool_watch']:
        total_tool_events = sum(len(events) for events in context['tool_watch'].values())
        print(f"  Tool Watch: {len(context['tool_watch'])} groups, {total_tool_events} events")
    if context['has_individual_events']:
        print(f"  Individual Creators: {len(context['individual_events'])} events")
    if context['has_news']:
        print(f"  News: {len(context['news_articles']['newsletter'])} articles (total {context['news_articles']['total']})")

    # --- Full version (archive) ---
    full_html = render_newsletter(context)

    if apply:
        full_path = os.path.join(editions_dir, f"newsletter_{today_iso}.html")
    else:
        full_path = os.path.join(script_dir, "newsletter_test.html")

    with open(full_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    full_kb = os.path.getsize(full_path) / 1024
    print(f"\nFull newsletter written to {full_path}")
    print(f"  Size: {full_kb:.1f} KB")

    # --- Truncated version (email) ---
    # Gmail clips messages over ~102KB — and it clips from the bottom, so the
    # footer/unsubscribe link is what disappears. Auto-tighten the per-section
    # cap until the email fits; if even the tightest cap is still over, abort
    # loudly (non-zero exit -> ERR trap -> admin failure email) instead of
    # sending a clipped edition. Nothing is registered/sent past this point
    # on failure: latest_news.json and Baserow registration come after.
    GMAIL_CLIP_KB = 102
    for cap in (4, 3, 2, 1):
        email_context = build_context(data, section_cap=cap, news_data=news_articles,
                                      source_stats=source_stats)
        email_context["whats_new"] = whats_new
        email_html = render_newsletter(email_context)
        email_kb = len(email_html.encode("utf-8")) / 1024
        if email_kb < GMAIL_CLIP_KB:
            if cap < 4:
                print(f"\n  Note: section cap tightened to {cap} to stay under {GMAIL_CLIP_KB}KB "
                      f"({email_kb:.1f} KB) — the 'see all' links cover the cut items")
            break
        print(f"\n  Email version is {email_kb:.1f} KB at section cap {cap} — over the {GMAIL_CLIP_KB}KB Gmail clip limit")
    else:
        print(f"\nERROR: email version still {email_kb:.1f} KB at section cap 1 — refusing to "
              f"generate an edition Gmail would clip (the unsubscribe footer goes first)")
        sys.exit(1)

    if apply:
        email_path = os.path.join(editions_dir, f"newsletter_email_{today_iso}.html")
    else:
        email_path = os.path.join(script_dir, "newsletter_email_test.html")

    with open(email_path, "w", encoding="utf-8") as f:
        f.write(email_html)

    print(f"Email newsletter written to {email_path}")
    print(f"  Size: {email_kb:.1f} KB (OK)")

    # Write latest_news.json for the landing page (only on a real --apply run).
    # URL-scheme filtering already happened in prepare_news_articles, which
    # feeds this list — so everything here is http(s).
    if apply:
        latest_news_path = os.path.join(script_dir, "latest_news.json")
        # Fixed cap, independent of the email's auto-tightened section_cap —
        # shrinking the email for Gmail must not shrink the website's news box.
        latest_articles = prepare_news_articles(news_articles, cap=4)["newsletter"]
        with open(latest_news_path, "w", encoding="utf-8") as f:
            json.dump({
                "date": today_iso,
                "articles": [
                    {
                        "title": a.get("score", {}).get("ai_title") if a.get("language") != "en" and a.get("score", {}).get("ai_title") else a["title"],
                        "url": a["url"],
                        "source_name": a.get("source_name", ""),
                        "language": a.get("language", "en"),
                        "published_date": a.get("published_date", ""),
                    }
                    for a in latest_articles
                ]
            }, f, ensure_ascii=False, indent=2)
        print(f"\nLatest news written to {latest_news_path} ({len(latest_articles)} articles)")

    # Register edition in Baserow (only on a real --apply run) — archive version only
    if apply:
        register_edition(context, os.path.basename(full_path))
    elif args.test:
        print("\nTest mode: skipping Baserow registration")
    else:
        print("\nDry run: skipping latest_news.json and Baserow registration")


if __name__ == "__main__":
    main()
