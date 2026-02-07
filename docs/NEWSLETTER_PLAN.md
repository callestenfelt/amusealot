# Musemaniac Newsletter Plan

## Vision

A periodic newsletter (weekly or biweekly) covering technical development activity in the museum sector. Two sections:

1. **GitHub Radar** - What museums are building, releasing, and open-sourcing
2. **Article Digest** - Curated articles from museum RSS feeds about digital/tech topics

Inspired by [heripo-research-radar](https://github.com/heripo-lab/heripo-research-radar), an AI-powered newsletter for Korean cultural heritage that costs $0.2-1 per issue to run.

## Architecture

```
DATA SOURCES                    PROCESSING                 OUTPUT
============                    ==========                 ======

GitHub API (133 museums)
  - New repos
  - Releases             -->  Collect & Score  -->  Newsletter HTML
  - README changes              (LLM)                - Email
  - Significant commits                              - RSS feed
                                                     - Web archive
RSS Feeds (234 active)
  - New articles          -->  Filter & Rank   -->
  - Blog posts                  (LLM)
  - Digital/tech content
```

## Part 1: GitHub Radar

### Data collection

Monitor the 133 museum GitHub accounts for notable activity:

| Signal | GitHub API endpoint | Why it matters |
|--------|-------------------|----------------|
| **New public repos** | `GET /orgs/{org}/repos?sort=created` | Museum starts a new project |
| **New releases** | `GET /repos/{owner}/{repo}/releases` | Stable version shipped |
| **README updates** | `GET /repos/{owner}/{repo}/commits?path=README.md` | Project documentation changes |
| **Repo description changes** | Compare cached vs current | Project direction shifts |
| **Stars/forks spike** | `GET /repos/{owner}/{repo}` | Community interest signal |

### Collection script: `collect_github_activity.py`

Runs daily (or before each newsletter). For each museum GitHub org:
1. Fetch recent repos (created in last 7/14 days)
2. Fetch recent releases across all repos
3. Check for significant README changes
4. Store activity entries in Baserow (new table) or JSON

### Scoring

Each GitHub event gets an AI relevance score:
- **New repo** with description mentioning "IIIF", "collection", "API", "digital", "archive" -> high score
- **Release** of known significant project -> high score
- **Fork/config repo** -> low score
- **Dependabot/CI commits** -> exclude

### Prompt strategy

```
You are a museum technology analyst. Score these GitHub activities
from museum organizations on a scale of 1-10 for relevance to
museum professionals interested in digital innovation.

Consider: Is this a meaningful technical contribution? Would museum
tech professionals want to know about it? Is it reusable by other
museums?

For each scored item (7+), write a 1-2 sentence summary explaining
why it matters for the museum sector.
```

## Part 2: Article Digest

### Data source

Already operational:
- 234 active RSS feeds from Swedish museums (expandable)
- 2,092+ content entries ingested
- AI translation & summarization via Groq/Llama 3.3

### Filtering for newsletter

From the existing content pipeline, select articles that match tech/digital categories:
- `digital` - Digital tools, apps, virtual exhibitions
- `technology` - AV, interactive, immersive tech, AI
- `accessibility` - Digital accessibility
- `research` - Digital research, data projects

### Additional article sources

Consider adding RSS feeds from:
- Museum tech blogs (e.g., museum-digital.org blog)
- IIIF community news
- Europeana tech blog
- MCN (Museum Computer Network)
- MuseWeb / MW conference

## Newsletter Generation Pipeline

Following the heripo-research-radar pattern:

### Step 1: Collect (daily cron)
```
collect_github_activity.py  ->  github_activity table in Baserow
ingest_rss_content.py       ->  content_entries table in Baserow (existing)
```

### Step 2: Score & Filter (before newsletter)
```
score_newsletter_content.py
  - Fetch unscored GitHub activity + new articles
  - Send to LLM for relevance scoring (1-10)
  - Filter to score >= 7
  - Deduplicate similar items
  - Select top 10-15 items per section
```

### Step 3: Generate (newsletter day)
```
generate_newsletter.py
  - Take top scored items
  - Send to LLM with newsletter composition prompt
  - Generate structured digest with:
    - Opening summary (2-3 sentences on the week's theme)
    - GitHub Radar section (5-8 items)
    - Article Digest section (5-8 items)
    - Closing note
  - Render into HTML template
  - Save to archive
```

### Step 4: Distribute
```
- Email via Resend API (or similar)
- Publish as RSS feed
- Archive on static site (optional)
```

## Tech Stack Options

### Option A: Python (extend existing pipeline)
- **Pro:** Matches existing scripts, Groq/Llama already set up, fast to build
- **Con:** HTML templating less elegant, no TypeScript type safety
- **Stack:** Python + Groq API + Jinja2 templates + Resend API

### Option B: TypeScript (fork heripo-research-radar)
- **Pro:** Proven newsletter architecture, good email templates, provider pattern
- **Con:** New stack to maintain, needs OpenAI (or adapt to Groq)
- **Stack:** TypeScript + OpenAI/Vercel AI SDK + HTML templates + Resend

### Option C: Hybrid
- **Pro:** Best of both worlds
- **Con:** Two languages to maintain
- **Stack:** Python for data collection/scoring (existing), TypeScript for newsletter generation/email

### Recommendation: Option A (Python)

The existing Python pipeline already handles data collection, AI processing via Groq, and Baserow integration. Adding newsletter generation is a natural extension. Use Jinja2 for HTML templates and the Resend API for email delivery.

## Estimated Cost Per Issue

| Component | Cost |
|-----------|------|
| GitHub API calls | Free (with token) |
| Groq/Llama 3.3 (scoring ~50 items) | Free tier |
| Groq/Llama 3.3 (newsletter generation) | Free tier |
| Resend email (up to 100 recipients) | Free tier |
| **Total** | **$0** (within free tiers) |

If scaling beyond free tiers or switching to OpenAI: ~$0.50-2 per issue.

## Data Model

### New Baserow table: Newsletter Activity (proposed)

| Field | Type | Description |
|-------|------|-------------|
| source_type | select | github / rss |
| source_org | text | GitHub org or museum name |
| title | text | Activity title |
| description | long_text | Raw description |
| url | url | Link to source |
| event_type | select | new_repo / release / article / blog_post |
| detected_date | date | When activity was detected |
| relevance_score | number | AI score 1-10 |
| ai_summary | long_text | AI-generated summary |
| newsletter_id | text | Which newsletter issue it was included in |
| status | select | new / scored / included / excluded |

## Timeline

### Phase 1: GitHub activity collection
- Build `collect_github_activity.py`
- Set up daily cron to collect events
- Store in Baserow

### Phase 2: Scoring pipeline
- Build `score_newsletter_content.py`
- Integrate GitHub activity + RSS articles
- LLM scoring and filtering

### Phase 3: Newsletter generation
- Build `generate_newsletter.py`
- HTML email template (Jinja2)
- Preview and archive

### Phase 4: Distribution
- Email delivery via Resend
- RSS feed output
- Subscription management (simple)

## Reference

- [heripo-research-radar](https://github.com/heripo-lab/heripo-research-radar) - AI newsletter for Korean cultural heritage
- Uses: TypeScript, OpenAI GPT-5, Vercel AI SDK, Provider-Service pattern
- Pipeline: Crawl (66 sources) -> LLM Analyze/Score -> LLM Generate -> Email
- Cost: $0.2-1 per issue, 15% click-through rate
