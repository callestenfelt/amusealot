#!/usr/bin/env python3
"""
Helper script to get field IDs from Baserow tables.
Use this after creating the News Sources and News Articles tables.

Usage:
  python get_field_ids.py <TABLE_ID>

Example:
  python get_field_ids.py 1234

Requires environment variables: BASEROW_URL, BASEROW_TOKEN
"""

import sys
import os
import json
import requests

BASEROW_URL = os.environ.get("BASEROW_URL")
BASEROW_TOKEN = os.environ.get("BASEROW_TOKEN")

if not BASEROW_URL or not BASEROW_TOKEN:
    print("ERROR: Missing BASEROW_URL or BASEROW_TOKEN environment variables")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: python get_field_ids.py <TABLE_ID>")
    sys.exit(1)

table_id = sys.argv[1]

try:
    response = requests.get(
        f"{BASEROW_URL}/api/database/fields/table/{table_id}/",
        headers={"Authorization": f"Token {BASEROW_TOKEN}"},
        timeout=30
    )
    response.raise_for_status()
    fields = response.json()

    print(f"\nField IDs for table {table_id}:")
    print("=" * 60)

    for field in fields:
        field_id = field['id']
        field_name = field['name']
        field_type = field['type']
        # NB: don't pad the id itself ("field_{id:4d}" printed "field_ 123"
        # for short ids — not a real field name); pad the whole token instead.
        token = f"field_{field_id}"
        print(f"{field_name:20s} {token:12s}  ({field_type})")

    print("=" * 60)
    print(f"\nTotal: {len(fields)} fields\n")

    # Generate Python dict for easy copying
    print("Python dictionary format:")
    print("{")
    for field in fields:
        # Convert field name to snake_case for dict key
        key = field['name'].lower().replace(' ', '_').replace('-', '_')
        print(f'    "{key}": "field_{field["id"]}",')
    print("}")

except requests.exceptions.HTTPError as e:
    print(f"ERROR: HTTP {e.response.status_code}")
    print(f"Response: {e.response.text}")
except Exception as e:
    print(f"ERROR: {e}")
