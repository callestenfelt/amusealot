#!/usr/bin/env python3
"""
Collect news articles from RSS feeds of Nordic and German cultural heritage institutions.
Supports ETag caching to minimize bandwidth and respect server resources.

Usage:
  python collect_news.py [--days 14] [--output news_articles.json] [--apply]

By default, runs in dry-run mode (safe). Use --apply to write to Baserow.

Requires environment variables: BASEROW_URL, BASEROW_TOKEN, NEWS_SOURCES_TABLE_ID, NEWS_ARTICLES_TABLE_ID
"""

import sys
import io
import os
import json
import hashlib
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

try:
    import feedparser
except ImportError:
    print("ERROR: feedparser not installed. Run: pip install feedparser")
    sys.exit(1)

try:
    from langdetect import detect, LangDetectException
except ImportError:
    print("ERROR: langdetect not installed. Run: pip install langdetect")
    sys.exit(1)

# Configuration from environment
BASEROW_URL = os.environ.get("BASEROW_URL")
BASEROW_TOKEN = os.environ.get("BASEROW_TOKEN")
NEWS_SOURCES_TABLE_ID = os.environ.get("NEWS_SOURCES_TABLE_ID")
NEWS_ARTICLES_TABLE_ID = os.environ.get("NEWS_ARTICLES_TABLE_ID")

if not all([BASEROW_URL, BASEROW_TOKEN, NEWS_SOURCES_TABLE_ID, NEWS_ARTICLES_TABLE_ID]):
    print("ERROR: Missing required environment variables")
    print("Required: BASEROW_URL, BASEROW_TOKEN, NEWS_SOURCES_TABLE_ID, NEWS_ARTICLES_TABLE_ID")
    sys.exit(1)

# Field IDs from Baserow
# News Sources table (753)
SOURCES_FIELDS = {
    "name": "field_7285",
    "country": "field_7288",
    "source_type": "field_7289",
    "rss_url": "field_7290",
    "language": "field_7291",
    "active": "field_7292",
    "last_collected": "field_7294",
}

# News Articles table (752)
ARTICLES_FIELDS = {
    "title": "field_7271",
    "url": "field_7274",
    "source_name": "field_7275",
    "source_id": "field_7296",
    "published_date": "field_7276",
    "collected_date": "field_7277",
    "summary": "field_7278",
    "language": "field_7279",
    "content_hash": "field_7280",
}

SCRIPT_DIR = Path(__file__).parent
ETAG_CACHE_FILE = SCRIPT_DIR / "news_etags.json"


def load_etag_cache():
    """Load ETag cache from previous runs."""
    if ETAG_CACHE_FILE.exists():
        try:
            with open(ETAG_CACHE_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load ETag cache: {e}")
    return {}


def save_etag_cache(cache):
    """Save ETag cache for next run."""
    try:
        with open(ETAG_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Could not save ETag cache: {e}")


def get_active_sources():
    """Fetch all active RSS sources from Baserow."""
    print("Fetching active RSS sources from Baserow...")
    sources = []
    page = 1

    while True:
        try:
            response = requests.get(
                f"{BASEROW_URL}/api/database/rows/table/{NEWS_SOURCES_TABLE_ID}/",
                params={
                    "size": 200,
                    "page": page,
                },
                headers={"Authorization": f"Token {BASEROW_TOKEN}"},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            for row in data["results"]:
                # Filter for active RSS sources
                active = row.get(SOURCES_FIELDS["active"])
                source_type = row.get(SOURCES_FIELDS["source_type"], {})
                source_type_value = source_type.get("value") if isinstance(source_type, dict) else source_type

                if active and source_type_value == "rss":
                    rss_url = row.get(SOURCES_FIELDS["rss_url"], "").strip()
                    if rss_url:
                        sources.append({
                            "id": row["id"],
                            "name": row.get(SOURCES_FIELDS["name"], ""),
                            "rss_url": rss_url,
                            "country": row.get(SOURCES_FIELDS["country"], {}).get("value", ""),
                            "language": row.get(SOURCES_FIELDS["language"], {}).get("value", ""),
                        })

            if not data.get("next"):
                break
            page += 1

        except Exception as e:
            print(f"ERROR fetching sources: {e}")
            break

    print(f"Found {len(sources)} active RSS sources")
    return sources


def compute_content_hash(title, url, published_date):
    """Compute SHA256 hash for deduplication."""
    content = f"{title}||{url}||{published_date}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def detect_language_safe(text):
    """Detect language with fallback to 'en'."""
    try:
        if not text or len(text.strip()) < 10:
            return "en"
        return detect(text)
    except LangDetectException:
        return "en"


def get_existing_hashes():
    """Fetch all existing content_hash values from Baserow for deduplication."""
    print("Fetching existing article hashes from Baserow...")
    hashes = set()
    page = 1

    while True:
        try:
            response = requests.get(
                f"{BASEROW_URL}/api/database/rows/table/{NEWS_ARTICLES_TABLE_ID}/",
                params={
                    "size": 200,
                    "page": page,
                },
                headers={"Authorization": f"Token {BASEROW_TOKEN}"},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            for row in data["results"]:
                content_hash = row.get(ARTICLES_FIELDS["content_hash"], "")
                if content_hash:
                    hashes.add(content_hash)

            if not data.get("next"):
                break
            page += 1

        except Exception as e:
            print(f"Warning: Could not fetch existing hashes: {e}")
            break

    print(f"Found {len(hashes)} existing articles")
    return hashes


def fetch_rss_feed(source, etag_cache, cutoff_date):
    """Fetch and parse RSS feed with ETag caching."""
    url = source["rss_url"]
    name = source["name"]

    print(f"\nFetching: {name}")
    print(f"  URL: {url}")

    try:
        # Use requests to fetch with proper SSL and encoding handling
        headers = {
            'User-Agent': 'AmuseAlot/1.0 (https://amusealot.com; newsletter@amusealot.com)',
        }
        if url in etag_cache:
            headers['If-None-Match'] = etag_cache[url]

        response = requests.get(url, headers=headers, timeout=30, verify=True)

        # Check if feed was modified
        if response.status_code == 304:
            print("  ✓ Not modified (304), skipping")
            return [], etag_cache.get(url)

        response.raise_for_status()

        # Get ETag from response
        new_etag = response.headers.get('ETag')

        # Parse the feed content
        # Set response encoding to UTF-8 if not specified
        if not response.encoding or response.encoding == 'ISO-8859-1':
            response.encoding = 'utf-8'

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:
            print(f"  ✗ Parse error: {feed.get('bozo_exception', 'Unknown error')}")
            return [], None

        print(f"  Found {len(feed.entries)} entries")

        # Extract articles
        articles = []
        for entry in feed.entries:
            # Parse publication date
            published_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    published_date = dt.date().isoformat()

                    # Skip old articles
                    if dt.date() < cutoff_date:
                        continue
                except Exception:
                    pass

            # If no valid date, use today
            if not published_date:
                published_date = datetime.now(timezone.utc).date().isoformat()

            # Get title and URL
            title = entry.get('title', '').strip()
            url = entry.get('link', '').strip()

            if not title or not url:
                continue

            # Get summary/description
            summary = entry.get('summary', '') or entry.get('description', '')
            if summary:
                # Clean HTML tags from summary
                import re
                summary = re.sub(r'<[^>]+>', '', summary).strip()
                summary = summary[:500]  # Limit length

            # Detect language from title + summary
            text_for_lang = f"{title} {summary}"
            language = detect_language_safe(text_for_lang)

            # Compute content hash
            content_hash = compute_content_hash(title, url, published_date)

            articles.append({
                "title": title,
                "url": url,
                "source_name": name,
                "source_id": source["id"],
                "published_date": published_date,
                "collected_date": datetime.now(timezone.utc).date().isoformat(),
                "summary": summary,
                "language": language,
                "content_hash": content_hash,
            })

        print(f"  ✓ Extracted {len(articles)} articles")
        return articles, new_etag

    except requests.exceptions.SSLError as e:
        print(f"  ✗ SSL Error: {e}")
        return [], None
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Request error: {e}")
        return [], None
    except Exception as e:
        print(f"  ✗ Error fetching feed: {e}")
        return [], None


def update_source_last_collected(source_id, apply_mode):
    """Update last_collected date for a source."""
    if not apply_mode:
        return

    try:
        today = datetime.now(timezone.utc).date().isoformat()
        response = requests.patch(
            f"{BASEROW_URL}/api/database/rows/table/{NEWS_SOURCES_TABLE_ID}/{source_id}/",
            headers={
                "Authorization": f"Token {BASEROW_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                SOURCES_FIELDS["last_collected"]: today,
            },
            timeout=30
        )
        response.raise_for_status()
    except Exception as e:
        print(f"  Warning: Could not update last_collected: {e}")


def save_articles_to_baserow(articles, apply_mode):
    """Save new articles to Baserow."""
    if not apply_mode:
        print(f"\n[DRY RUN] Would save {len(articles)} articles to Baserow")
        return

    print(f"\nSaving {len(articles)} articles to Baserow...")
    saved = 0

    for article in articles:
        try:
            # Map to Baserow field IDs
            row_data = {
                ARTICLES_FIELDS["title"]: article["title"],
                ARTICLES_FIELDS["url"]: article["url"],
                ARTICLES_FIELDS["source_name"]: article["source_name"],
                ARTICLES_FIELDS["source_id"]: [article["source_id"]],  # Link field expects array
                ARTICLES_FIELDS["published_date"]: article["published_date"],
                ARTICLES_FIELDS["collected_date"]: article["collected_date"],
                ARTICLES_FIELDS["summary"]: article["summary"],
                ARTICLES_FIELDS["language"]: article["language"],
                ARTICLES_FIELDS["content_hash"]: article["content_hash"],
            }

            response = requests.post(
                f"{BASEROW_URL}/api/database/rows/table/{NEWS_ARTICLES_TABLE_ID}/",
                headers={
                    "Authorization": f"Token {BASEROW_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=row_data,
                timeout=30
            )
            response.raise_for_status()
            saved += 1

        except Exception as e:
            print(f"  Error saving article '{article['title'][:50]}...': {e}")

    print(f"✓ Saved {saved}/{len(articles)} articles")


def main():
    parser = argparse.ArgumentParser(description="Collect news articles from RSS feeds")
    parser.add_argument("--days", type=int, default=14, help="Collect articles from last N days")
    parser.add_argument("--output", default="news_articles.json", help="Output JSON file")
    parser.add_argument("--apply", action="store_true", help="Write to Baserow (default is dry-run)")
    args = parser.parse_args()

    print("=" * 60)
    print("Cultural Heritage News Collection")
    print("=" * 60)

    if not args.apply:
        print("\n⚠️  DRY RUN MODE - Use --apply to write to Baserow\n")

    # Calculate cutoff date
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=args.days)).date()
    print(f"Collecting articles from: {cutoff_date}")

    # Load ETag cache
    etag_cache = load_etag_cache()
    print(f"Loaded {len(etag_cache)} ETags from cache")

    # Get active sources
    sources = get_active_sources()
    if not sources:
        print("No active RSS sources found!")
        return

    # Get existing article hashes for deduplication (skip in dry-run — not needed for testing)
    if args.apply:
        existing_hashes = get_existing_hashes()
    else:
        existing_hashes = set()
        print("Skipping hash deduplication (dry-run mode)")

    # Collect articles from all sources
    all_articles = []
    new_etag_cache = {}

    for source in sources:
        articles, new_etag = fetch_rss_feed(source, etag_cache, cutoff_date)

        # Update ETag cache
        if new_etag:
            new_etag_cache[source["rss_url"]] = new_etag
        elif source["rss_url"] in etag_cache:
            new_etag_cache[source["rss_url"]] = etag_cache[source["rss_url"]]

        # Filter out duplicates
        new_articles = [a for a in articles if a["content_hash"] not in existing_hashes]

        if len(articles) != len(new_articles):
            print(f"  Filtered {len(articles) - len(new_articles)} duplicates")

        all_articles.extend(new_articles)

        # Update source last_collected date
        if articles:  # Only update if we successfully fetched
            update_source_last_collected(source["id"], args.apply)

    # Save ETag cache
    save_etag_cache(new_etag_cache)

    # Save intermediate JSON
    output_path = SCRIPT_DIR / args.output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Saved {len(all_articles)} articles to {output_path}")

    # Save to Baserow
    if all_articles:
        save_articles_to_baserow(all_articles, args.apply)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Sources checked: {len(sources)}")
    print(f"New articles: {len(all_articles)}")

    # Language breakdown
    lang_counts = {}
    for article in all_articles:
        lang = article["language"]
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    if lang_counts:
        print("\nLanguage breakdown:")
        for lang, count in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {lang}: {count}")

    print("=" * 60)


if __name__ == "__main__":
    main()
