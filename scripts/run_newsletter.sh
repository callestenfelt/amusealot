#!/bin/bash
#
# End-to-end newsletter pipeline: collect → enrich → collect news → score news → score → generate → send → remind
#
# Usage:
#   ./run_newsletter.sh          # Dry run (shows what would be sent)
#   ./run_newsletter.sh --apply  # Actually send
#
# Requires .env to be loaded (BASEROW_URL, BASEROW_TOKEN, GITHUB_TOKEN,
# GROQ_API_KEY, RESEND_API_KEY, RESEND_FROM, MUSEMANIAC_BASE_URL, SUBSCRIBER_TABLE_ID,
# NEWS_SOURCES_TABLE_ID, NEWS_ARTICLES_TABLE_ID)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "  AmuseAlot Newsletter Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# Step 1: Collect GitHub activity
echo ""
echo "[1/8] Collecting GitHub activity..."
python3 "$SCRIPT_DIR/collect_github_activity.py"

# Step 2: Enrich events
echo ""
echo "[2/8] Enriching GitHub events..."
python3 "$SCRIPT_DIR/enrich_github_activity.py"

# Step 3: Collect news articles
echo ""
echo "[3/8] Collecting news articles..."
python3 "$SCRIPT_DIR/collect_news.py"

# Step 4: Score news articles
echo ""
echo "[4/8] Scoring news articles..."
python3 "$SCRIPT_DIR/score_news.py"

# Step 5: Score GitHub content with LLM
echo ""
echo "[5/8] Scoring GitHub content..."
python3 "$SCRIPT_DIR/score_newsletter_content.py"

# Step 6: Generate HTML
echo ""
echo "[6/8] Generating newsletter..."
python3 "$SCRIPT_DIR/generate_newsletter.py"

# Step 7: Send (passes --apply through if provided)
echo ""
echo "[7/8] Sending newsletter..."
python3 "$SCRIPT_DIR/send_newsletter.py" "$@"

# Step 8: Send confirmation reminders to pending subscribers
echo ""
echo "[8/8] Sending confirmation reminders..."
python3 "$SCRIPT_DIR/send_reminders.py" "$@"

# Clear "What's new" after a real send so it doesn't repeat next week
if [[ "${1:-}" == "--apply" ]]; then
    > "$SCRIPT_DIR/whats_new.txt"
    echo ""
    echo "Cleared whats_new.txt"
fi

echo ""
echo "========================================"
echo "  Pipeline complete"
echo "========================================"
