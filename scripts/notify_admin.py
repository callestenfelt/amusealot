#!/usr/bin/env python3
"""
Send a brief admin notification email after the newsletter pipeline runs.

Called from run_newsletter.sh on both success and failure.

Usage:
  python notify_admin.py --status success --message "Sent to 12 subscribers"
  python notify_admin.py --status failure --message "Step 3 failed: ..."

Requires environment variables:
  RESEND_API_KEY, RESEND_FROM, NOTIFY_EMAIL
"""

import sys
import os
import argparse
import html
import requests
from datetime import datetime, timezone

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", choices=["success", "failure"], required=True)
    parser.add_argument("--message", default="")
    args = parser.parse_args()

    if not all([RESEND_API_KEY, RESEND_FROM, NOTIFY_EMAIL]):
        print("notify_admin: RESEND_API_KEY, RESEND_FROM, or NOTIFY_EMAIL not set — skipping")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    icon = "✓" if args.status == "success" else "✗"
    subject = f"{icon} Newsletter pipeline {args.status} — {now}"

    body = f"<pre style='font-family:monospace'>{html.escape(args.message)}</pre>"

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={"from": RESEND_FROM, "to": [NOTIFY_EMAIL], "subject": subject, "html": body},
        timeout=30,
    )
    if resp.status_code >= 400:
        print(f"notify_admin: failed to send ({resp.status_code}): {resp.text[:200]}")
    else:
        print(f"notify_admin: sent to {NOTIFY_EMAIL}")


if __name__ == "__main__":
    main()
