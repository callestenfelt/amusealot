# AmuseAlot

A weekly newsletter tracking what museums and cultural heritage organizations are building on GitHub — plus curated news from the sector. Delivered every Wednesday.

**Website:** https://amusealot.com

## How it works

Every Wednesday, the pipeline runs automatically:

1. **Collect GitHub activity** — scans public events from 700+ sources (museums, archives, heritage orgs, individuals) and tracked museum-tech tools
2. **Enrich** — adds repository metadata (language, stars, descriptions)
3. **Collect news** — fetches RSS feeds from cultural heritage institutions across Europe
4. **Score** — AI (GPT-OSS 120B via Groq) scores each GitHub event and news article for relevance to museum technology professionals
5. **Generate** — renders an email-ready HTML newsletter
6. **Send** — delivers to subscribers via Resend
7. **Remind** — sends a reminder to non-openers a few days later

## Newsletter sections

- **New Repos** — recently created repositories from tracked sources
- **Cultural Heritage News** — top news articles scored by AI for relevance
- **Releases** — new software releases and tagged versions
- **Notable Pushes** — noteworthy commits and development activity
- **Tool Watch** — updates to shared museum-sector tools (IIIF, Omeka, etc.)

## Project structure

```
musemaniac/
  scripts/
    collect_github_activity.py     # Fetch GitHub events from tracked sources + technologies
    enrich_github_activity.py      # Enrich events with repo metadata
    collect_news.py                # Fetch and deduplicate RSS news articles
    score_news.py                  # AI scoring and summarization of news articles
    score_newsletter_content.py    # AI scoring of GitHub events
    generate_newsletter.py         # Render HTML newsletter (web + email)
    send_newsletter.py             # Send via Resend API
    send_reminders.py              # Send confirmation reminders to pending subscribers
    run_newsletter.sh              # End-to-end pipeline script
    subscriber_app.py              # Flask web app (subscribe/confirm/unsubscribe/sources/feedback)
    purge_pending_subscribers.py   # Remove stale pending subscribers (bot signups); dry-run by default
    enrich_github.py               # Wikidata → Baserow GitHub enrichment
    search_github_museums.py       # GitHub API org search
    filter_github_museums.py       # Filter candidates to real museums
    add_github_museums.py          # Add curated orgs to Baserow
  docs/
    GITHUB_DATABASE.md             # Sources database schema and field reference
    NEWS_ARTICLES.md               # News feature: tables, scoring, integration
    TOOL_WATCH.md                  # Tool Watch feature: technologies table setup
    NEWSLETTER_PLAN.md             # Original architecture plan
    turnstile-setup.md             # How to enable the Cloudflare Turnstile gate on the subscribe form
```

## Infrastructure

- **Database:** Baserow (self-hosted)
- **GitHub sources:** 700+ organizations and individuals across 50+ countries
- **News sources:** 15+ RSS feeds from European museums and heritage institutions
- **Technologies tracked:** Museum-sector tools (IIIF, Omeka, CollectiveAccess, etc.) via Tool Watch
- **Email delivery:** Resend
- **AI:** Groq / GPT-OSS 120B (free tier) for scoring and summarization
- **Web:** Flask app with Caddy reverse proxy (auto-HTTPS)

## Website

The subscriber app at https://amusealot.com includes:

- **/** — subscription form
- **/sources** — browse all tracked GitHub sources and news feeds
- **/about** — how the pipeline works, data sources, and open-source philosophy
- **/feedback** — rate editions and suggest new sources
- **/archive** — past newsletter editions

## Related

- [heripo-research-radar](https://github.com/heripo-lab/heripo-research-radar) — inspiration: AI-powered newsletter for Korean cultural heritage research
