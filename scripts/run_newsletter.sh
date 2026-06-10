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

# Load .env from the project root (one level up from scripts/) if present.
# Needed when running via cron, which doesn't source shell profiles.
ENV_FILE="$(dirname "$SCRIPT_DIR")/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -o allexport
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +o allexport
fi

# Log file — keeps the last 30 days of output
LOG_DIR="$(dirname "$SCRIPT_DIR")/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/newsletter-$(date '+%Y-%m-%d').log"

# Tee all output to the log file
exec > >(tee -a "$LOG_FILE") 2>&1

# On failure: send admin notification with the log tail
_on_failure() {
    local exit_code=$?
    local tail
    tail=$(tail -30 "$LOG_FILE" 2>/dev/null || echo "(log unavailable)")
    python3 "$SCRIPT_DIR/notify_admin.py" \
        --status failure \
        --message "Pipeline failed (exit $exit_code) at $(date '+%Y-%m-%d %H:%M:%S')

$tail" || true
}
trap _on_failure ERR

# Only --apply is a meaningful pass-through. Compute it once and forward only it
# to the send scripts: send_reminders.py understands only --apply, so forwarding
# "$@" verbatim would make it error on any other arg (e.g. --input/--test).
APPLY_FLAG=""
if [[ "${1:-}" == "--apply" ]]; then
    APPLY_FLAG="--apply"
fi

echo "========================================"
echo "  AmuseAlot Newsletter Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# Step 1: Collect GitHub activity
echo ""
echo "[1/8] Collecting GitHub activity..."
python3 "$SCRIPT_DIR/collect_github_activity.py" --days 8

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
python3 "$SCRIPT_DIR/send_newsletter.py" $APPLY_FLAG

# Step 8: Send confirmation reminders to pending subscribers
echo ""
echo "[8/8] Sending confirmation reminders..."
python3 "$SCRIPT_DIR/send_reminders.py" $APPLY_FLAG

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

# Admin success notification (only when actually sending)
if [[ "${1:-}" == "--apply" ]]; then
    SENT_COUNT=$(grep -c "Sent to " "$LOG_FILE" 2>/dev/null || true)
    python3 "$SCRIPT_DIR/notify_admin.py" \
        --status success \
        --message "Newsletter sent on $(date '+%Y-%m-%d %H:%M:%S') — ${SENT_COUNT} email(s) sent.

Log: $LOG_FILE" || true
fi
