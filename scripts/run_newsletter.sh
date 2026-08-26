#!/bin/bash
#
# End-to-end newsletter pipeline: collect → enrich → collect news → score news → score → generate → send → remind
#
# Usage:
#   ./run_newsletter.sh                  # Dry run (shows what would be sent)
#   ./run_newsletter.sh --apply          # Actually send
#   ./run_newsletter.sh --apply --force  # Recovery: override the .sent marker
#                                        # (re-sends to everyone — see CLAUDE.md)
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

# Only --apply and --force are meaningful pass-throughs, and each script gets
# only the flag(s) it understands — forwarding "$@" verbatim would make e.g.
# send_reminders.py error on --force. collect_news/score_news get --apply:
# without it they never write articles or scores to Baserow, which disables
# cross-edition dedup and leaves nothing for score_news's unscored-row
# recovery to heal after a failed run. --force goes only to send_newsletter.py
# (recovery path: override the .sent marker / stale-date check after a
# partially-sent run — see CLAUDE.md "Recovering from a missed send").
APPLY_FLAG=""
FORCE_FLAG=""
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY_FLAG="--apply" ;;
        --force) FORCE_FLAG="--force" ;;
        *) echo "Unknown argument: $arg (expected --apply and/or --force)"; exit 2 ;;
    esac
done

# The edition file this run generates and sends. Computed here so the send
# step previews THIS run's output (dry runs write test filenames), and so the
# success email can read the sent count from this edition's .sent marker.
if [[ -n "$APPLY_FLAG" ]]; then
    EMAIL_FILE="$SCRIPT_DIR/editions/newsletter_email_$(date '+%Y-%m-%d').html"
else
    EMAIL_FILE="$SCRIPT_DIR/newsletter_email_test.html"
fi

echo "========================================"
echo "  AmuseAlot Newsletter Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# Step 1: Collect GitHub activity (--apply persists the seen-events cache
# used for cross-edition dedup; dry runs leave it untouched)
echo ""
echo "[1/8] Collecting GitHub activity..."
python3 "$SCRIPT_DIR/collect_github_activity.py" --days 8 $APPLY_FLAG

# Step 2: Enrich events
echo ""
echo "[2/8] Enriching GitHub events..."
python3 "$SCRIPT_DIR/enrich_github_activity.py"

# Step 3: Collect news articles
echo ""
echo "[3/8] Collecting news articles..."
python3 "$SCRIPT_DIR/collect_news.py" $APPLY_FLAG

# Step 4: Score news articles
echo ""
echo "[4/8] Scoring news articles..."
python3 "$SCRIPT_DIR/score_news.py" $APPLY_FLAG

# Step 5: Score GitHub content with LLM
echo ""
echo "[5/8] Scoring GitHub content..."
python3 "$SCRIPT_DIR/score_newsletter_content.py"

# Step 6: Generate HTML (without --apply it writes test filenames and skips
# latest_news.json + Baserow edition registration)
echo ""
echo "[6/8] Generating newsletter..."
python3 "$SCRIPT_DIR/generate_newsletter.py" $APPLY_FLAG

# Step 7: Send — always the file step 6 just generated (dry runs would
# otherwise glob last week's dated edition, or fail on an empty editions/)
echo ""
echo "[7/8] Sending newsletter..."
python3 "$SCRIPT_DIR/send_newsletter.py" --input "$EMAIL_FILE" $APPLY_FLAG $FORCE_FLAG

# Step 8: Send confirmation reminders to pending subscribers
echo ""
echo "[8/8] Sending confirmation reminders..."
python3 "$SCRIPT_DIR/send_reminders.py" $APPLY_FLAG

# Clear "What's new" after a real send so it doesn't repeat next week
if [[ -n "$APPLY_FLAG" ]]; then
    > "$SCRIPT_DIR/whats_new.txt"
    echo ""
    echo "Cleared whats_new.txt"
fi

echo ""
echo "========================================"
echo "  Pipeline complete"
echo "========================================"

# Admin success notification (only when actually sending)
if [[ -n "$APPLY_FLAG" ]]; then
    # Read the sent count from this edition's .sent marker (its final
    # "send finished ... sent=N" line) — the day's log accumulates across
    # re-runs and the tee is async, so parsing the log is unreliable.
    SENT_COUNT=$(grep -o 'sent=[0-9]*' "$EMAIL_FILE.sent" 2>/dev/null | tail -1 | cut -d= -f2)
    SENT_COUNT="${SENT_COUNT:-0}"
    python3 "$SCRIPT_DIR/notify_admin.py" \
        --status success \
        --message "Newsletter sent on $(date '+%Y-%m-%d %H:%M:%S') — ${SENT_COUNT} email(s) sent.

Log: $LOG_FILE" || true
fi
