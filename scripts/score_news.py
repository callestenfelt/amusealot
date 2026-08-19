#!/usr/bin/env python3
"""
Score news articles for relevance using Groq/GPT-OSS 120B.
Assigns tier (1=featured, 2=mentioned, 3=skip) based on relevance to museum tech audience.
Generates English summaries for tier 1 non-English articles.

Usage:
  python score_news.py [--input news_articles.json] [--output news_articles_scored.json] [--apply]

By default, runs in dry-run mode (safe). Use --apply to write scores to Baserow.

Requires environment variable: GROQ_API_KEY, BASEROW_URL, BASEROW_TOKEN, NEWS_ARTICLES_TABLE_ID
"""

import sys
import io
import os
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# Configuration from environment
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
BASEROW_URL = os.environ.get("BASEROW_URL")
BASEROW_TOKEN = os.environ.get("BASEROW_TOKEN")
NEWS_ARTICLES_TABLE_ID = os.environ.get("NEWS_ARTICLES_TABLE_ID")

if not GROQ_API_KEY:
    print("ERROR: Missing GROQ_API_KEY environment variable")
    sys.exit(1)

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DELAY_BETWEEN_CALLS = 3  # seconds
MAX_RETRIES = 3
BATCH_SIZE = 10  # Smaller than GitHub batches due to longer text

# Field IDs for News Articles table (752)
ARTICLES_FIELDS = {
    "relevance_score": "field_7281",
    "tier": "field_7282",
    "ai_summary": "field_7283",
    # Read fields (same table, used when recovering unscored rows)
    "title": "field_7271",
    "url": "field_7274",
    "source_name": "field_7275",
    "published_date": "field_7276",
    "collected_date": "field_7277",
    "summary": "field_7278",
    "language": "field_7279",
}

# Unscored rows older than this are left alone (stale; next edition won't use them)
RECOVERY_WINDOW_DAYS = 14

SCRIPT_DIR = Path(__file__).parent

SCORING_SYSTEM_PROMPT = """You are a museum technology analyst scoring news articles for a newsletter read by museum and cultural heritage tech professionals.

Be STRICT and SELECTIVE. Most articles should be tier 3. Only promote articles that are directly and specifically about museum/heritage technology.

ALWAYS TIER 3 (score 1-3) — no exceptions:
- Job postings, vacancies, hiring calls, PhD/postdoc positions
- Generic digital preservation or web archiving news NOT specifically about museums/GLAM institutions
- WordPress plugins, general web tools, or internet infrastructure (even if tangentially related to preservation)
- Press releases about funding or partnerships with no technical detail
- Tourism, visitor statistics, or physical building news
- Staff appointments or personnel changes
- Award announcements without technical content
- General AI/ML news not specifically applied to museum collections

RELEVANT — must be DIRECTLY about museums, galleries, libraries, archives, or heritage institutions:
- Collection management systems, digital cataloguing, metadata standards (LIDO, Dublin Core, CIDOC CRM)
- IIIF implementations, linked open data in heritage contexts
- Digitisation projects at specific institutions (3D scanning, mass digitisation, born-digital)
- Museum-specific AI/ML applications (visual search on collections, OCR for historical documents)
- Open source tools built for or widely used by museums (Omeka, AtoM, Archivematica, CollectiveAccess)
- Digital exhibitions, virtual tours, or online collection interfaces at cultural institutions
- Heritage sector data standards, APIs, and interoperability initiatives
- Museum cybersecurity, GDPR compliance for collections data
- Significant new digital collections or archives made publicly available

Scoring (1-10):
- Relevance: Is this specifically about museum/heritage technology?
- Technical depth: Does it have substance beyond a press release?
- Actionability: Can a museum professional learn from or apply this?

Tier definitions:
- Tier 1 (score 8-10): Highly relevant, technically substantive, newsworthy — worth featuring with summary
- Tier 2 (score 5-7): Relevant to the sector, worth a brief mention
- Tier 3 (score 1-4): Not relevant enough, skip — when in doubt, use tier 3

For non-English articles: Focus on technical substance over language. If tier 1, you'll be asked to provide an English summary."""


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
        # gpt-oss spends completion tokens on reasoning before the answer
        "max_tokens": 4000,
        "reasoning_effort": "low",
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


def score_article_batch(articles):
    """Score a batch of articles for relevance."""
    # Prepare article descriptions for the LLM
    article_texts = []
    for i, article in enumerate(articles):
        text = f"""Article {i+1}:
Title: {article['title']}
Source: {article['source_name']} ({article.get('language', 'unknown')})
Date: {article.get('published_date', 'unknown')}
Summary: {article.get('summary', 'No summary available')[:300]}
"""
        article_texts.append(text)

    batch_text = "\n\n".join(article_texts)

    prompt = f"""Score these {len(articles)} news articles for relevance to museum technology professionals.

{batch_text}

For each article, provide:
1. relevance: score 1-10
2. tier: 1 (feature), 2 (mention), or 3 (skip)
3. reasoning: brief explanation of score

Return JSON object with "articles" array, each with: {{"index": N, "relevance": X, "tier": Y, "reasoning": "..."}}"""

    messages = [
        {"role": "system", "content": SCORING_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]

    result, error = groq_request(messages, json_mode=True)

    if error:
        print(f"    Error: {error}")
        return None

    return result


def generate_english_summary(article):
    """Generate English title and summary for a non-English tier 1 article."""
    prompt = f"""This article is in {article['language']}. Translate the title to English and write a concise English summary (2-3 sentences) focusing on the technical substance — what the article actually reports.

Do not add framing about relevance to museum professionals or "why this matters"; the newsletter audience already works in the sector, so that wording is redundant. Just describe what the article is about.

Title: {article['title']}
Summary: {article.get('summary', 'No summary available')}

Return JSON with exactly two fields:
- "title": a concise English translation of the article title
- "summary": a clear, informative English summary of what the article reports"""

    messages = [
        {"role": "system", "content": "You are a technical translator for the museum technology sector."},
        {"role": "user", "content": prompt}
    ]

    result, error = groq_request(messages, json_mode=True)

    if error:
        print(f"    Summary generation error: {error}")
        return None

    return result if result else None


def _select_value(field):
    """Baserow single-selects come back as {'value': ...}; plain text as str."""
    if isinstance(field, dict):
        return field.get("value", "")
    return field or ""


def fetch_unscored_articles():
    """Fetch recent Baserow rows with an empty tier field.

    Articles land in Baserow during collection but only get a tier during
    scoring, so a scoring failure (e.g. a Groq outage) followed by a rerun
    strands them: collect_news dedups against Baserow and never re-emits them.
    Merging them back in here makes a failed-then-rerun cycle self-heal.
    """
    if not all([BASEROW_URL, BASEROW_TOKEN, NEWS_ARTICLES_TABLE_ID]):
        print("  Baserow env not configured, skipping unscored-row recovery")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECOVERY_WINDOW_DAYS)
    articles = []
    page = 1

    while True:
        try:
            response = requests.get(
                f"{BASEROW_URL}/api/database/rows/table/{NEWS_ARTICLES_TABLE_ID}/",
                params={"size": 200, "page": page},
                headers={"Authorization": f"Token {BASEROW_TOKEN}"},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"  Warning: Could not fetch unscored articles from Baserow: {e}")
            return articles

        for row in data["results"]:
            if _select_value(row.get(ARTICLES_FIELDS["tier"])):
                continue  # already scored

            collected_raw = row.get(ARTICLES_FIELDS["collected_date"]) or ""
            if collected_raw:
                try:
                    collected = datetime.fromisoformat(collected_raw.replace("Z", "+00:00"))
                    if collected.tzinfo is None:
                        collected = collected.replace(tzinfo=timezone.utc)
                    if collected < cutoff:
                        continue  # too old to matter for the next edition
                except ValueError:
                    pass  # unparseable date: keep the row rather than strand it

            articles.append({
                "id": row["id"],
                "title": row.get(ARTICLES_FIELDS["title"], ""),
                "url": row.get(ARTICLES_FIELDS["url"], ""),
                "source_name": _select_value(row.get(ARTICLES_FIELDS["source_name"])),
                "published_date": row.get(ARTICLES_FIELDS["published_date"], ""),
                "summary": row.get(ARTICLES_FIELDS["summary"], ""),
                "language": _select_value(row.get(ARTICLES_FIELDS["language"])) or "en",
            })

        if not data.get("next"):
            break
        page += 1

    return articles


def update_article_scores_in_baserow(article_id, score_data, apply_mode):
    """Update article scores in Baserow."""
    if not apply_mode:
        return

    try:
        # Map tier to single_select value (needs to match Baserow options)
        tier_value = str(score_data["tier"])

        update_data = {
            ARTICLES_FIELDS["relevance_score"]: score_data["relevance"],
            ARTICLES_FIELDS["tier"]: tier_value,
        }

        if score_data.get("ai_summary"):
            update_data[ARTICLES_FIELDS["ai_summary"]] = score_data["ai_summary"]

        response = requests.patch(
            f"{BASEROW_URL}/api/database/rows/table/{NEWS_ARTICLES_TABLE_ID}/{article_id}/",
            headers={
                "Authorization": f"Token {BASEROW_TOKEN}",
                "Content-Type": "application/json",
            },
            json=update_data,
            timeout=30
        )
        response.raise_for_status()

    except Exception as e:
        print(f"    Warning: Could not update Baserow: {e}")


def main():
    parser = argparse.ArgumentParser(description="Score news articles for relevance")
    parser.add_argument("--input", default="news_articles.json", help="Input JSON file")
    parser.add_argument("--output", default="news_articles_scored.json", help="Output JSON file")
    parser.add_argument("--apply", action="store_true", help="Write scores to Baserow (default is dry-run)")
    parser.add_argument("--baserow-only", action="store_true",
                        help="Skip the input file; score only unscored Baserow rows (recovery mode)")
    args = parser.parse_args()

    print("=" * 60)
    print("News Article Scoring")
    print("=" * 60)

    if not args.apply:
        print("\n⚠️  DRY RUN MODE - Use --apply to write to Baserow\n")

    # Load articles
    articles = []
    if not args.baserow_only:
        input_path = SCRIPT_DIR / args.input
        if not input_path.exists():
            print(f"ERROR: Input file not found: {input_path}")
            print("Run collect_news.py first to generate articles")
            sys.exit(1)

        with open(input_path, encoding='utf-8') as f:
            articles = json.load(f)

        print(f"Loaded {len(articles)} articles from {args.input}")

    # Recover unscored rows stranded in Baserow by a previous failed run
    print("Checking Baserow for recent unscored articles...")
    seen_ids = {a["id"] for a in articles if "id" in a}
    seen_urls = {a["url"] for a in articles if a.get("url")}
    recovered = [a for a in fetch_unscored_articles()
                 if a["id"] not in seen_ids and a["url"] not in seen_urls]
    if recovered:
        print(f"  Recovered {len(recovered)} unscored articles from Baserow")
        articles.extend(recovered)

    if not articles:
        print("No articles to score")
        return

    print(f"Scoring {len(articles)} articles total")

    # Score articles in batches
    scored_articles = []
    failed_count = 0  # articles dropped to default tier 3 by a Groq/API failure
    total_batches = (len(articles) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(0, len(articles), BATCH_SIZE):
        batch = articles[batch_idx:batch_idx + BATCH_SIZE]
        batch_num = batch_idx // BATCH_SIZE + 1

        print(f"\nScoring batch {batch_num}/{total_batches} ({len(batch)} articles)...")

        scores = score_article_batch(batch)

        if not scores or "articles" not in scores:
            print("  Warning: Scoring failed for this batch, skipping")
            failed_count += len(batch)
            # Add articles with default low scores
            for article in batch:
                article["score"] = {
                    "relevance": 1,
                    "tier": 3,
                    "reasoning": "Scoring failed",
                    "ai_summary": None
                }
                scored_articles.append(article)
            continue

        # Map scores back to articles
        for score_data in scores["articles"]:
            idx = score_data.get("index", 0) - 1  # Convert to 0-based
            if 0 <= idx < len(batch):
                article = batch[idx]
                article["score"] = {
                    "relevance": score_data.get("relevance", 1),
                    "tier": score_data.get("tier", 3),
                    "reasoning": score_data.get("reasoning", ""),
                    "ai_summary": None
                }

                # Generate English title + summary for tier 1 and tier 2 non-English articles
                if article["score"]["tier"] in (1, 2) and article.get("language") != "en":
                    print(f"  Generating English title+summary for: {article['title'][:50]}...")
                    time.sleep(DELAY_BETWEEN_CALLS)

                    result = generate_english_summary(article)
                    if result:
                        if isinstance(result, dict):
                            article["score"]["ai_title"] = result.get("title")
                            article["score"]["ai_summary"] = result.get("summary")
                        else:
                            article["score"]["ai_summary"] = result

                # Update Baserow if apply mode
                if "id" in article:  # Only if article has Baserow ID
                    update_article_scores_in_baserow(article["id"], article["score"], args.apply)

                scored_articles.append(article)

        # Rate limiting between batches
        if batch_idx + BATCH_SIZE < len(articles):
            time.sleep(DELAY_BETWEEN_CALLS)

    # Save scored articles
    output_path = SCRIPT_DIR / args.output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(scored_articles, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Saved scored articles to {output_path}")

    # Summary statistics
    tier_counts = {1: 0, 2: 0, 3: 0}
    for article in scored_articles:
        tier = article.get("score", {}).get("tier", 3)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total articles scored: {len(scored_articles)}")
    print(f"\nTier distribution:")
    print(f"  Tier 1 (Featured): {tier_counts[1]} articles")
    print(f"  Tier 2 (Mentioned): {tier_counts[2]} articles")
    print(f"  Tier 3 (Skip): {tier_counts[3]} articles")

    if tier_counts[1] > 0:
        print(f"\nTier 1 articles:")
        for article in scored_articles:
            if article.get("score", {}).get("tier") == 1:
                score = article["score"]["relevance"]
                lang = article.get("language", "?")
                print(f"  [{score}/10] [{lang}] {article['title'][:60]}...")

    print("=" * 60)

    # Abort if a large fraction of articles failed to score (Groq outage / rate
    # limit). Better to fail the run and retry than to silently ship a thin
    # edition — run_newsletter.sh's ERR trap turns this into an admin alert.
    if failed_count >= 3 and failed_count > len(scored_articles) * 0.5:
        print(f"\nERROR: {failed_count}/{len(scored_articles)} articles failed to "
              "score due to Groq API errors. Aborting so the pipeline is retried.")
        sys.exit(1)


if __name__ == "__main__":
    main()
