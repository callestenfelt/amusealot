#!/bin/bash
#
# End-to-end newsletter pipeline: collect → enrich → score → generate → send
#
# Usage:
#   ./run_newsletter.sh          # Dry run (shows what would be sent)
#   ./run_newsletter.sh --apply  # Actually send
#
# Requires .env to be loaded (BASEROW_URL, BASEROW_TOKEN, GITHUB_TOKEN,
# GROQ_API_KEY, RESEND_API_KEY, RESEND_FROM, MUSEMANIAC_BASE_URL, SUBSCRIBER_TABLE_ID)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "  Musemaniac Newsletter Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# Step 1: Collect GitHub activity
echo ""
echo "[1/5] Collecting GitHub activity..."
python3 "$SCRIPT_DIR/collect_github_activity.py"

# Step 2: Enrich events
echo ""
echo "[2/5] Enriching events..."
python3 "$SCRIPT_DIR/enrich_github_activity.py"

# Step 3: Score with LLM
echo ""
echo "[3/5] Scoring content..."
python3 "$SCRIPT_DIR/score_newsletter_content.py"

# Step 4: Generate HTML
echo ""
echo "[4/5] Generating newsletter..."
python3 "$SCRIPT_DIR/generate_newsletter.py"

# Step 5: Send (passes --apply through if provided)
echo ""
echo "[5/5] Sending newsletter..."
python3 "$SCRIPT_DIR/send_newsletter.py" "$@"

echo ""
echo "========================================"
echo "  Pipeline complete"
echo "========================================"
