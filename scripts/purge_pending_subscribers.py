#!/usr/bin/env python3
"""
Purge stale `pending` subscribers from Baserow.

Bots that hit the /subscribe form leave rows stuck in `pending` (they never click
the double-opt-in confirmation link). This removes pending rows older than a
cutoff so they don't accumulate. Confirmed and unsubscribed rows are never touched.

Dry-run by default — lists what WOULD be deleted. Pass --apply to actually delete.

Usage:
  python purge_pending_subscribers.py                 # dry run, default 30 days
  python purge_pending_subscribers.py --days 60       # dry run, 60-day cutoff
  python purge_pending_subscribers.py --apply         # delete (>= 30 days old)

Requires environment variables:
  BASEROW_URL, BASEROW_TOKEN, SUBSCRIBER_TABLE_ID
"""

import sys
import os
from datetime import date, datetime, timedelta

import requests

BASEROW_URL = os.environ["BASEROW_URL"]
BASEROW_TOKEN = os.environ["BASEROW_TOKEN"]
SUBSCRIBER_TABLE_ID = os.environ["SUBSCRIBER_TABLE_ID"]

BASEROW_HEADERS = {
    "Authorization": f"Token {BASEROW_TOKEN}",
    "Content-Type": "application/json",
}

DEFAULT_DAYS = 30


def _status_value(row):
    s = row.get("status")
    return s.get("value") if isinstance(s, dict) else s


def fetch_all_rows():
    """Fetch every subscriber row (paginated)."""
    url = f"{BASEROW_URL}/api/database/rows/table/{SUBSCRIBER_TABLE_ID}/"
    rows = []
    page = 1
    while True:
        resp = requests.get(
            url,
            params={"size": 200, "page": page, "user_field_names": "true"},
            headers=BASEROW_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("results", []))
        if not data.get("next"):
            break
        page += 1
    return rows


def delete_row(row_id):
    url = f"{BASEROW_URL}/api/database/rows/table/{SUBSCRIBER_TABLE_ID}/{row_id}/"
    resp = requests.delete(url, headers=BASEROW_HEADERS, timeout=30)
    resp.raise_for_status()


def parse_arg_days(argv):
    if "--days" in argv:
        i = argv.index("--days")
        try:
            days = int(argv[i + 1])
        except (IndexError, ValueError):
            print("ERROR: --days requires an integer, e.g. --days 60")
            sys.exit(1)
        if days < 1:
            # --days 0 (or negative) would make TODAY's legitimate unconfirmed
            # signups purgeable — refuse.
            print("ERROR: --days must be at least 1")
            sys.exit(1)
        return days
    return DEFAULT_DAYS


def main():
    argv = sys.argv[1:]
    dry_run = "--apply" not in argv
    days = parse_arg_days(argv)
    cutoff = date.today() - timedelta(days=days)

    if dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No changes will be made")
        print("Run with --apply to actually delete from Baserow")
        print("=" * 60)

    print(f"Cutoff: pending rows with subscribed_at on or before {cutoff.isoformat()} "
          f"({days} days ago)")

    rows = fetch_all_rows()
    print(f"Fetched {len(rows)} subscriber rows")

    to_delete = []
    skipped_recent = 0
    skipped_no_date = 0
    for row in rows:
        if _status_value(row) != "pending":
            continue
        sub_at = (row.get("subscribed_at") or "").strip()
        if not sub_at:
            # No date — don't guess; leave it for manual review.
            skipped_no_date += 1
            continue
        try:
            sub_date = datetime.strptime(sub_at[:10], "%Y-%m-%d").date()
        except ValueError:
            skipped_no_date += 1
            continue
        if sub_date <= cutoff:
            to_delete.append(row)
        else:
            skipped_recent += 1

    print(f"\nPending & older than cutoff: {len(to_delete)}")
    print(f"Pending but still recent (kept): {skipped_recent}")
    if skipped_no_date:
        print(f"Pending with unparseable/missing date (kept for review): {skipped_no_date}")

    if not to_delete:
        print("\nNothing to purge.")
        return

    print()
    for row in to_delete:
        print(f"  {'WOULD DELETE' if dry_run else 'DELETING'}: "
              f"row {row.get('id')} | {row.get('email')} | subscribed {row.get('subscribed_at')}")

    if dry_run:
        print(f"\n=== DRY RUN - would delete {len(to_delete)} pending rows ===")
        return

    print(f"\n=== Deleting {len(to_delete)} pending rows ===")
    deleted = failed = 0
    for row in to_delete:
        try:
            delete_row(row["id"])
            deleted += 1
        except Exception as e:
            failed += 1
            print(f"  ERROR deleting row {row.get('id')} ({row.get('email')}): {e}")
    print(f"\nDone — deleted {deleted}, failed {failed}")


if __name__ == "__main__":
    main()
