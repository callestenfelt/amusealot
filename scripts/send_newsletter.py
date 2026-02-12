#!/usr/bin/env python3
"""
Send the generated newsletter to confirmed subscribers via Resend API.

Usage:
  python send_newsletter.py [--input newsletter_YYYY-MM-DD.html] [--apply]

Default is dry-run — shows what would be sent without actually sending.

Requires environment variables:
  BASEROW_URL, BASEROW_TOKEN, RESEND_API_KEY, RESEND_FROM,
  MUSEMANIAC_BASE_URL, SUBSCRIBER_TABLE_ID
"""

import sys
import io
import os
import glob
import time
import argparse
from datetime import datetime, timezone

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


def find_latest_newsletter(script_dir):
    """Find the most recent email newsletter, falling back to full version."""
    editions = os.path.join(script_dir, "editions")
    # Prefer email (truncated) version
    email_files = sorted(glob.glob(os.path.join(editions, "newsletter_email_*.html")), reverse=True)
    if email_files:
        return email_files[0]
    # Fallback to full version (old editions before email split)
    full_files = sorted(glob.glob(os.path.join(editions, "newsletter_*.html")), reverse=True)
    if full_files:
        return full_files[0]
    print("ERROR: No newsletter_*.html files found")
    sys.exit(1)


def get_confirmed_subscribers():
    """Fetch all subscribers from Baserow, filter to confirmed in code."""
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
        )
        resp.raise_for_status()
        data = resp.json()
        subscribers.extend(data.get("results", []))

        if not data.get("next"):
            break
        page += 1

    # Filter in code — Baserow single_select API filters are unreliable with text values
    confirmed = [s for s in subscribers if (s.get("status") or {}).get("value") == "confirmed"]
    return confirmed


def personalize_html(html, subscriber):
    """Replace %%UNSUBSCRIBE_URL%% with the subscriber's personal link."""
    unsub_token = subscriber.get("unsubscribe_token") or ""
    unsub_url = f"{BASE_URL}/unsubscribe?token={unsub_token}"
    return html.replace("%%UNSUBSCRIBE_URL%%", unsub_url)


def send_email(to_email, html, unsub_url):
    """Send a single email via Resend API with proper headers."""
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM,
            "to": [to_email],
            "subject": "AmuseAlot — Museum Tech Newsletter",
            "html": html,
            "headers": {
                "List-Unsubscribe": f"<{unsub_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click-Unsubscribe",
            },
        },
    )
    resp.raise_for_status()
    return resp.json()


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Send newsletter to confirmed subscribers")
    parser.add_argument("--input", default=None,
                        help="Input HTML file (default: latest newsletter_*.html)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually send emails (default: dry-run)")
    parser.add_argument("--test", metavar="EMAIL",
                        help="Send only to this email address (for testing)")
    args = parser.parse_args()

    # Resolve input file
    input_file = args.input or find_latest_newsletter(script_dir)
    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        base_html = f.read()

    print(f"Newsletter: {input_file}")
    print(f"  Size: {len(base_html) / 1024:.1f} KB")

    # Check for unsubscribe placeholder
    if "%%UNSUBSCRIBE_URL%%" not in base_html:
        print("WARNING: Newsletter does not contain %%UNSUBSCRIBE_URL%% placeholder")
        print("  Unsubscribe links will not be personalized")

    # Fetch subscribers
    if args.test:
        print(f"\n--- TEST MODE: sending only to {args.test} ---")
        subscribers = [{"email": args.test, "unsubscribe_token": "test-token"}]
    else:
        print("\nFetching confirmed subscribers from Baserow...")
        subscribers = get_confirmed_subscribers()
        print(f"  Found {len(subscribers)} confirmed subscriber(s)")

    if not subscribers:
        print("\nNo subscribers to send to. Done.")
        return

    if not args.apply and not args.test:
        print("\n--- DRY RUN ---")
        for sub in subscribers:
            email = sub.get("email", "?")
            token = (sub.get("unsubscribe_token") or "")[:8]
            print(f"  Would send to: {email}  (unsub token: {token}...)")
        print(f"\nTotal: {len(subscribers)} email(s) would be sent")
        print("Pass --apply to actually send.")
        return

    # Send
    print(f"\n--- SENDING ({len(subscribers)} emails) ---")
    sent = 0
    errors = 0

    for i, sub in enumerate(subscribers):
        email = sub.get("email", "")
        if not email:
            print(f"  SKIP: row {sub.get('id')} has no email")
            continue

        unsub_token = sub.get("unsubscribe_token") or ""
        unsub_url = f"{BASE_URL}/unsubscribe?token={unsub_token}"
        personalized = personalize_html(base_html, sub)

        try:
            result = send_email(email, personalized, unsub_url)
            sent += 1
            email_id = result.get("id", "?")
            print(f"  [{sent}/{len(subscribers)}] Sent to {email} (id: {email_id})")
        except requests.exceptions.HTTPError as e:
            errors += 1
            print(f"  ERROR sending to {email}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"    Response: {e.response.text[:200]}")
        except Exception as e:
            errors += 1
            print(f"  ERROR sending to {email}: {e}")

        # Rate limit delay (skip after last email)
        if i < len(subscribers) - 1:
            time.sleep(SEND_DELAY)

    print(f"\n--- DONE ---")
    print(f"  Sent: {sent}")
    print(f"  Errors: {errors}")
    print(f"  Total: {len(subscribers)}")


if __name__ == "__main__":
    main()
