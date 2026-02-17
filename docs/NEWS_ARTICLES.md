# Cultural Heritage News Feature

The Cultural Heritage News feature curates news articles from museums, archives, and heritage organizations across Europe, delivering AI-scored content alongside GitHub activity.

## Why News Articles?

Museums publish important technical and digital heritage announcements through institutional blogs and news pages. The news feature captures these stories and surfaces the most relevant content to complement GitHub activity.

## How it works

1. **Collection**: `collect_news.py` fetches RSS feeds from tracked news sources in Baserow
2. **Deduplication**: Content hashing (SHA256 of title + URL + date) prevents duplicate collection
3. **Caching**: ETag headers minimize bandwidth and respect 304 Not Modified responses
4. **Language detection**: Automatically detects article language via langdetect
5. **Scoring**: `score_news.py` uses Groq/Llama 3.3 to score articles for relevance (1-10 → tier 1/2/3)
6. **Translation**: Non-English tier 1 articles get AI-generated English summaries
7. **Integration**: Newsletter includes top 4 articles (max 1 per source) with links to archive for more

## Baserow News Sources Table Setup

### Required Fields

| Field Name | Field Type | Description | Example |
|------------|-----------|-------------|---------|
| `name` | Text | Institution name | Riksantikvarieämbetet |
| `country` | Single Select | Source country | Sweden, Denmark, Norway, Finland, Iceland, Germany, International |
| `source_type` | Single Select | Collection method | rss, website, api, arxiv |
| `rss_url` | URL | RSS feed URL | https://example.se/feed |
| `language` | Single Select | Primary language | sv, da, no, fi, is, de, en |
| `active` | Boolean | Include in collection | ✓ |
| `focus_area` | Long Text | Coverage description | Digital preservation, museum tech |
| `last_collected` | Date | Last successful run | 2026-02-16 |
| `priority` | Number | Source importance (1-5) | 5 (national agencies) → 1 (experimental) |

### Country Options

Create these single_select options for the `country` field:
- Sweden
- Denmark
- Norway
- Finland
- Iceland
- Germany
- International

### Language Options

Create these single_select options for the `language` field:
- sv (Swedish)
- da (Danish)
- no (Norwegian)
- fi (Finnish)
- is (Icelandic)
- de (German)
- en (English)

### Source Type Options

Create these single_select options for the `source_type` field:
- rss
- website (future: web scraping)
- api (future: NewsAPI, arXiv)
- arxiv (future: academic papers)

**Phase 1 uses RSS only.** Other source types are placeholders for future enhancements.

## Baserow News Articles Table Setup

### Required Fields

| Field Name | Field Type | Description | Example |
|------------|-----------|-------------|---------|
| `title` | Text | Article headline | New 3D scanning initiative |
| `url` | URL | Article link | https://... |
| `source_name` | Text | Institution name | Riksantikvarieämbetet |
| `source_id` | Link to table | Link to News Sources | (row ref) |
| `published_date` | Date | Publication date | 2026-02-10 |
| `collected_date` | Date | Collection timestamp | 2026-02-16 |
| `summary` | Long Text | Original excerpt | ... |
| `language` | Text | Detected language | sv |
| `content_hash` | Text | SHA256 for dedup | sha256:abc123... |
| `relevance_score` | Number | AI score (1-10) | 8 |
| `tier` | Single Select | Newsletter tier | 1, 2, 3 |
| `ai_summary` | Long Text | LLM-generated summary | ... |
| `included_in_edition` | Date | Newsletter date if sent | 2026-02-19 |

### Tier Options

Create these single_select options for the `tier` field:
- 1 (featured - score 8-10)
- 2 (mentioned - score 5-7)
- 3 (skip - score 1-4)

## Configuration

### Environment Variables

Add to `.env`:

```bash
NEWS_SOURCES_TABLE_ID=your-news-sources-table-id
NEWS_ARTICLES_TABLE_ID=your-news-articles-table-id
```

### Script Integration

The news collection runs in the weekly newsletter pipeline via `run_newsletter.sh`:

```bash
# Step 3: Collect news articles
python3 collect_news.py

# Step 4: Score news articles
python3 score_news.py
```

## Newsletter Output

The Cultural Heritage News section appears after "New Repos" in the newsletter, capped at 4 articles with a "see all" link if more exist:

```
📰 Cultural Heritage News

Title of Featured Article
Riksantikvarieämbetet · 2026-02-10 · SV

AI-generated summary explaining the article's
technical significance and relevance to the
museum tech community.

Read more →

[3 more articles...]

See all 8 news articles in the full edition
```

## Newsletter Integration Details

### Section Placement

The news section appears in this order:
1. Newsletter intro + stats
2. Spotlight project
3. **New Repos** (capped at 4)
4. **📰 Cultural Heritage News** (capped at 4)
5. **Releases** (capped at 4)
6. **Notable Pushes** (capped at 4)
7. Most Active Organizations
8. Individual Creators
9. Tool Watch
10. Feedback

### Article Filtering

Articles are prepared with the following logic:
1. Sort tier 1 and tier 2 by relevance score (descending)
2. Combine lists (tier 1 first)
3. Filter to **max 1 article per source** to ensure diversity
4. Cap at 4 for email newsletter
5. Next 4 go to website-only section
6. "See all" link appears if more than 4 total articles

### Dynamic Source Counts

Both the newsletter and /about page now show dynamic source counts:
- Newsletter intro: "Tracking 736 sources in 55+ countries"
- About page: Same counts fetched from Baserow API
- Counts include both GitHub sources (table 745) and news sources (table 753)

## AI Scoring Prompt

The scoring system uses this prompt to evaluate news articles:

```
You are a museum technology analyst scoring news articles for relevance.

Target audience: Museum professionals, digital preservationists,
heritage technologists, GLAM developers.

Relevant topics:
- Digital preservation, collection management systems
- 3D digitization, IIIF, linked open data
- Museum tech projects and open source software
- Cultural heritage AI/ML applications
- Digital exhibitions, web accessibility

Tier definitions:
- Tier 1 (8-10): High technical value, actionable, newsworthy
- Tier 2 (5-7): Moderately interesting, worth mentioning
- Tier 3 (1-4): Skip (general tourism, routine events)

For non-English articles: Focus on technical substance,
provide English summary.
```

## Initial RSS Feeds

The feature launched with 15 validated RSS feeds across:
- **Sweden** (8): Riksantikvarieämbetet, Nationalmuseum, Moderna Museet, etc.
- **Denmark** (3): Nationalmuseet, Danish National Archives, etc.
- **Norway** (2): Nasjonalmuseet, Kulturrådet
- **Finland** (1): National Museum of Finland
- **Germany** (1): Deutsche Digitale Bibliothek

Full feed list: `E:\_devdocs\musemaniac\news_sources_validated_feeds.csv`

## Technical Implementation

### ETag Caching Pattern

```python
# Load ETag cache from previous run
etag_cache = load_json("news_etags.json") if exists else {}

# Fetch with conditional request
headers = {'If-None-Match': etag_cache.get(url)}
response = requests.get(url, headers=headers, timeout=30)

if response.status_code == 304:  # Not modified
    continue

# Save new ETag for next run
if 'ETag' in response.headers:
    etag_cache[url] = response.headers['ETag']
save_json("news_etags.json", etag_cache)
```

### Content Hash Deduplication

```python
import hashlib

def compute_content_hash(title, url, published_date):
    """Generate SHA256 hash for deduplication."""
    content = f"{title}|{url}|{published_date}"
    return "sha256:" + hashlib.sha256(content.encode('utf-8')).hexdigest()
```

### Language Detection

```python
from langdetect import detect, LangDetectException

try:
    language = detect(text)
except LangDetectException:
    language = "unknown"
```

## File Structure

```
E:/_dev/musemaniac/scripts/
├── collect_news.py              # RSS collection with ETag caching
├── score_news.py                # Groq/Llama AI scoring
├── news_articles.json           # Intermediate: collected articles
├── news_articles_scored.json    # Intermediate: scored articles
├── news_etags.json              # ETag cache for bandwidth optimization
├── generate_newsletter.py       # Modified: loads news_articles_scored.json
├── run_newsletter.sh            # Modified: added steps 3-4 for news
└── templates/
    └── newsletter.html.j2       # Modified: added news section
```

## Data Flow

```
Baserow: News Sources (RSS URLs, active=true)
    ↓
collect_news.py → news_articles.json
    ↓ (uses news_etags.json for caching)
score_news.py → news_articles_scored.json
    ↓ (Groq/Llama 3.3 scoring + translation)
    ├─→ Baserow: News Articles (storage + metrics)
    └─→ generate_newsletter.py
            ↓ (merges with GitHub scored content)
        newsletter_email_YYYY-MM-DD.html
            ↓
        send_newsletter.py → Resend API → Subscribers
```

## Future Enhancements (Phase 2+)

### Web Scraping for Non-RSS Sources

- Playwright + BeautifulSoup for JavaScript-heavy sites
- Store CSS selectors in Baserow (per-source scraping config)
- Use LLM to extract article metadata from HTML (fallback for complex layouts)

### arXiv API Integration

- Use **arxiv.py** library (official Python wrapper)
- Search categories: cs.CV (Computer Vision), cs.CL (NLP), cs.DL (Digital Libraries)
- Keywords: "cultural heritage", "museum digitization", "3D heritage", "IIIF", "digital preservation"
- Rate limit: Max 1 request per 3 seconds (enforced by library)
- Returns structured metadata: title, authors, abstract, PDF URL, publication date

### Advanced Analytics

- Topic modeling (BERTopic) to identify emerging trends
- Geographic clustering (group by region in newsletter)
- Source quality metrics (hit rate, adjust scoring weights)

### Semantic Deduplication

- Move from hash-based to embedding-based similarity
- Catch same story from multiple outlets
- Use text-dedup library with MinHash LSH

## Cost Analysis

**Current (Phase 1 - RSS Only):**
- Groq API: Free tier sufficient (~10-15 API calls per newsletter)
- Baserow: Existing instance, no additional cost
- Bandwidth: Negligible (RSS feeds are small, ETag caching minimizes)

**Total additional cost: $0**

**Future (Phase 2+ - Web Scraping, arXiv):**
- Playwright: Free (headless browser)
- arXiv API: Free
- Optional translation (DeepL): $5-10/month for premium quality

**Total Phase 2 cost: $0-10/month**

## Success Metrics

**Quantitative:**
- 5-15 news articles per newsletter (tier 1 + tier 2 combined)
- News section click-through rate > 5%
- >70% of tier 1 articles rated "relevant" by readers
- >80% of active sources providing usable content monthly

**Qualitative:**
- Positive reader feedback mentioning news section
- Requests for specific sources or topics
- "I wouldn't have found this otherwise" sentiment

## Notes

- News articles are optional — newsletter works without them
- Tier 3 (skip) articles are stored in Baserow for future analysis but not shown in newsletter
- Non-English tier 2 articles appear as links only (no translation)
- Non-English tier 1 articles get AI-generated English summaries
- Article language is shown as badge (e.g., "SV", "DE") when not English
- Each newsletter edition logs which articles were included via `included_in_edition` date field
