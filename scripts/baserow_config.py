#!/usr/bin/env python3
"""Single source of truth for Baserow table ids and field-id maps.

Field ids are stable per column (they survive renames), so this module is the
one place they live — the collectors, scorers, GitHub scripts, the generator,
and the subscriber app all import from here instead of carrying their own
copies. Regenerate a map with `python get_field_ids.py <TABLE_ID>` after
adding columns.

Table ids that vary per deployment (news sources/articles, editions,
subscribers) stay in .env; only the sources table id was hardcoded across
scripts, so it lives here too.
"""

# Sources table (museums / heritage orgs / individuals with GitHub accounts)
SOURCES_TABLE_ID = 745
SOURCES_FIELDS = {
    "name": "field_7191",
    "museum_uri": "field_7189",
    "qid": "field_7190",
    "country": "field_7192",
    "website": "field_7193",
    "github": "field_7222",
    "github_url": "field_7223",
    "tracked_repos": "field_7261",
    "entity_type": "field_7225",
}

# News Sources table (753 in production; id comes from NEWS_SOURCES_TABLE_ID)
NEWS_SOURCES_FIELDS = {
    "name": "field_7285",
    "country": "field_7288",
    "source_type": "field_7289",
    "rss_url": "field_7290",
    "language": "field_7291",
    "active": "field_7292",
    "last_collected": "field_7294",
}

# News Articles table (752 in production; id comes from NEWS_ARTICLES_TABLE_ID)
NEWS_ARTICLES_FIELDS = {
    "title": "field_7271",
    "url": "field_7274",
    "source_name": "field_7275",
    "source_id": "field_7296",
    "published_date": "field_7276",
    "collected_date": "field_7277",
    "summary": "field_7278",
    "language": "field_7279",
    "content_hash": "field_7280",
    "relevance_score": "field_7281",
    "tier": "field_7282",
    "ai_summary": "field_7283",
    # "ai_title" is created by hand in the Baserow UI and resolved by name at
    # runtime (score_news.resolve_ai_title_field) — deliberately not listed.
}
