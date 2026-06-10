#!/usr/bin/env python3
"""
Send a single confirmation reminder to pending subscribers who signed up 24h+ ago.

Usage:
  python send_reminders.py          # Dry run
  python send_reminders.py --apply  # Actually send

Requires environment variables:
  BASEROW_URL, BASEROW_TOKEN, RESEND_API_KEY, RESEND_FROM,
  MUSEMANIAC_BASE_URL, SUBSCRIBER_TABLE_ID
"""

import sys
import io
import os
import time
import argparse
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import requests

# --- Config from environment ---
BASEROW_URL = os.environ["BASEROW_URL"]
BASEROW_TOKEN = os.environ["BASEROW_TOKEN"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
RESEND_FROM = os.environ["RESEND_FROM"]
BASE_URL = os.environ["MUSEMANIAC_BASE_URL"]
SUBSCRIBER_TABLE_ID = os.environ["SUBSCRIBER_TABLE_ID"]

BASEROW_HEADERS = {
    "Authorization": f"Token {BASEROW_TOKEN}",
    "Content-Type": "application/json",
}

SEND_DELAY = 1  # seconds between sends
REMINDER_WAIT_HOURS = 24


def get_pending_needing_reminder():
    """Fetch all subscribers, return pending ones eligible for a reminder."""
    subscribers = []
    page = 1

    while True:
        resp = requests.get(
            f"{BASEROW_URL}/api/database/rows/table/{SUBSCRIBER_TABLE_ID}/",
            params={
                "size": 200,
                "page": page,
                "user_field_names": "true",
            },
            headers=BASEROW_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        subscribers.extend(data.get("results", []))

        if not data.get("next"):
            break
        page += 1

    cutoff = datetime.now(timezone.utc) - timedelta(hours=REMINDER_WAIT_HOURS)
    eligible = []

    for sub in subscribers:
        # Must be pending
        status = (sub.get("status") or {}).get("value", "")
        if status != "pending":
            continue

        # Must not have already been reminded
        if sub.get("reminder_sent_at"):
            continue

        # Must have subscribed 24h+ ago
        subscribed_at = sub.get("subscribed_at") or ""
        if not subscribed_at:
            continue

        try:
            sub_date = datetime.fromisoformat(subscribed_at).replace(tzinfo=timezone.utc)
        except ValueError:
            # Date-only field from Baserow (YYYY-MM-DD)
            try:
                sub_date = datetime.strptime(subscribed_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                print(f"  WARNING: Cannot parse subscribed_at '{subscribed_at}' for {sub.get('email')}")
                continue

        if sub_date <= cutoff:
            eligible.append(sub)

    return eligible


def update_reminder_sent(row_id):
    """Set reminder_sent_at to today's date in Baserow."""
    from datetime import date
    resp = requests.patch(
        f"{BASEROW_URL}/api/database/rows/table/{SUBSCRIBER_TABLE_ID}/{row_id}/",
        params={"user_field_names": "true"},
        headers=BASEROW_HEADERS,
        json={"reminder_sent_at": date.today().isoformat()},
        timeout=30,
    )
    resp.raise_for_status()


def send_reminder_email(to_email, html):
    """Send a single reminder email via Resend API."""
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM,
            "to": [to_email],
            "subject": "AmuseAlot — Quick reminder to confirm",
            "html": html,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Send confirmation reminders to pending subscribers")
    parser.add_argument("--apply", action="store_true",
                        help="Actually send emails (default: dry-run)")
    args = parser.parse_args()

    # Load template
    template_path = os.path.join(script_dir, "templates", "reminder_email.html")
    if not os.path.exists(template_path):
        print(f"ERROR: Template not found: {template_path}")
        sys.exit(1)

    with open(template_path, "r", encoding="utf-8") as f:
        template_html = f.read()

    # Fetch eligible subscribers
    print("Fetching pending subscribers needing reminder...")
    eligible = get_pending_needing_reminder()
    print(f"  Found {len(eligible)} subscriber(s) eligible for reminder")

    if not eligible:
        print("\nNo reminders to send. Done.")
        return

    if not args.apply:
        print("\n--- DRY RUN ---")
        for sub in eligible:
            email = sub.get("email", "?")
            subscribed = sub.get("subscribed_at", "?")
            print(f"  Would remind: {email}  (subscribed: {subscribed})")
        print(f"\nTotal: {len(eligible)} reminder(s) would be sent")
        print("Pass --apply to actually send.")
        return

    # Send reminders
    print(f"\n--- SENDING REMINDERS ({len(eligible)}) ---")
    sent = 0
    errors = 0

    for i, sub in enumerate(eligible):
        email = sub.get("email", "")
        row_id = sub.get("id")
        confirm_token = sub.get("confirm_token") or ""

        if not email or not confirm_token:
            print(f"  SKIP: row {row_id} missing email or confirm_token")
            continue

        confirm_url = f"{BASE_URL}/confirm?token={confirm_token}"
        html = template_html.replace("%%CONFIRM_URL%%", confirm_url)

        try:
            result = send_reminder_email(email, html)
            email_id = result.get("id", "?")
            print(f"  [{i+1}/{len(eligible)}] Sent reminder to {email} (id: {email_id})")

            # Mark as reminded in Baserow
            update_reminder_sent(row_id)
            sent += 1
        except requests.exceptions.HTTPError as e:
            errors += 1
            print(f"  ERROR sending to {email}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"    Response: {e.response.text[:200]}")
        except Exception as e:
            errors += 1
            print(f"  ERROR sending to {email}: {e}")

        # Rate limit delay (skip after last)
        if i < len(eligible) - 1:
            time.sleep(SEND_DELAY)

    print(f"\n--- DONE ---")
    print(f"  Sent: {sent}")
    print(f"  Errors: {errors}")
    print(f"  Total: {len(eligible)}")


if __name__ == "__main__":
    main()
