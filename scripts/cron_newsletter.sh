#!/bin/bash
#
# Outermost cron wrapper for the weekly newsletter send.
#
# Deployed to /opt/musemaniac/scripts/cron_newsletter.sh on the VPS and run by
# root's crontab:  0 7 * * 3  (every Wednesday 07:00). This repo copy is the
# reviewable source of truth — deploy changes via scp like the other scripts.
#
# It writes the day's underscore log (newsletter_YYYY-MM-DD.log); the inner
# run_newsletter.sh additionally tees the hyphen log (newsletter-YYYY-MM-DD.log)
# and prunes both to 30 days. Keep line endings LF — a CRLF here has broken the
# cron before (see CLAUDE.md "Recovering from a missed send", step 4).
set -euo pipefail
set -a
source /opt/musemaniac/.env
set +a
exec /opt/musemaniac/scripts/run_newsletter.sh --apply >> /opt/musemaniac/logs/newsletter_$(date +%Y-%m-%d).log 2>&1
