# AmuseAlot

A weekly newsletter tracking what museums and cultural heritage organizations are building on GitHub. Delivered every Wednesday.

**Website:** https://amusealot.com

## How it works

Every Wednesday, the pipeline:
1. **Collects** public GitHub activity from 149+ sources worldwide (museums, archives, heritage orgs, individuals) + tracked technologies (IIIF, Omeka, etc.)
2. **Enriches** events with repository metadata (language, stars, descriptions)
3. **Scores** each event with AI (Llama 3.3 via Groq) for relevance
4. **Generates** an email-ready HTML newsletter with sections: Spotlight, New Repos, Releases, Most Active, Notable Pushes, and Tool Watch
5. **Sends** to subscribers via Resend

## Project Structure

```
musemaniac/
  scripts/
    collect_github_activity.py     # Collect GitHub events from museum orgs
    enrich_github_activity.py      # Enrich with repo metadata
    score_newsletter_content.py    # AI scoring and summarization
    generate_newsletter.py         # Render HTML newsletter
    send_newsletter.py             # Send via Resend API
    run_newsletter.sh              # End-to-end pipeline wrapper
    subscriber_app.py              # Flask web app (subscribe/unsubscribe)
    enrich_github.py               # Wikidata -> Baserow GitHub enrichment
    search_github_museums.py       # GitHub API org search
    filter_github_museums.py       # Filter to real museums
    add_github_museums.py          # Add curated orgs to Baserow
  docs/
    GITHUB_DATABASE.md             # Database documentation
    NEWSLETTER_PLAN.md             # Newsletter architecture plan
```

## Infrastructure

- **Database:** Baserow (self-hosted)
- **Sources tracked:** 149+ GitHub organizations across 31 countries (museums, archives, heritage orgs, individuals)
- **Technologies tracked:** Museum-tech tools and frameworks (IIIF, Omeka, etc.) — optional "Tool Watch" feature
- **Email delivery:** Resend (free tier)
- **AI:** Groq/Llama 3.3 for scoring and summarization
- **Reverse proxy:** Caddy with auto-HTTPS

## Related

- [heripo-research-radar](https://github.com/heripo-lab/heripo-research-radar) - Inspiration: AI-powered newsletter for Korean cultural heritage research
