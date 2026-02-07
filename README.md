# Musemaniac

A curated newsletter and signal platform tracking technical development activity in the museum sector worldwide.

## Focus

Museums that are active on GitHub and publishing about digital innovation. Tracking 133+ museum GitHub organizations across 20+ countries, from the Met and MoMA to niche computer museums.

## Project Structure

```
musemaniac/
  scripts/              # Data collection and enrichment scripts
    enrich_github.py           # Wikidata -> Baserow GitHub enrichment
    search_github_museums.py   # GitHub API org search
    filter_github_museums.py   # Filter to real museums
    add_github_museums.py      # Add curated orgs to Baserow
  docs/
    GITHUB_DATABASE.md         # Database documentation
    NEWSLETTER_PLAN.md         # Newsletter architecture plan
```

## Infrastructure

- **Database:** Baserow (self-hosted) at http://77.42.40.207
- **Museums table:** 745 (28,600+ museums, 133 with GitHub)
- **Content table:** 746 (2,000+ RSS articles ingested)
- **Automation:** n8n + Python scripts on Hetzner server
- **AI:** Groq/Llama 3.3 for translation and summarization

## Newsletter (planned)

Two-part periodic digest:
1. **GitHub Radar** - New repos, releases, and projects from museum GitHub orgs
2. **Article Digest** - Curated tech/digital articles from museum RSS feeds

See [docs/NEWSLETTER_PLAN.md](docs/NEWSLETTER_PLAN.md) for the full plan.

## Related

- `E:\_devdocs\musemaniac` - Private docs, credentials, server configs (not on GitHub)
- [heripo-research-radar](https://github.com/heripo-lab/heripo-research-radar) - Reference implementation for AI-powered newsletters
