#!/usr/bin/env python3
"""Shared Baserow row CRUD used by the subscriber app and ops scripts.

Reads BASEROW_URL / BASEROW_TOKEN from the environment at call time. All
functions raise on HTTP errors — callers decide what a failure means.
"""

import os
import requests


def _base():
    return os.environ["BASEROW_URL"], {
        "Authorization": f"Token {os.environ['BASEROW_TOKEN']}",
        "Content-Type": "application/json",
    }


def list_rows(table_id, filters=None, user_field_names=True, timeout=10):
    """Fetch all rows of a table (paginated), with optional filter params."""
    base_url, headers = _base()
    url = f"{base_url}/api/database/rows/table/{table_id}/"
    rows = []
    page = 1
    while True:
        params = {"size": 200, "page": page}
        if user_field_names:
            params["user_field_names"] = "true"
        if filters:
            # Never let a filters dict override the pagination keys — a stray
            # "page" would pin every iteration to the same page and loop forever
            params.update({k: v for k, v in filters.items()
                           if k not in ("page", "size")})
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("results", []))
        if not data.get("next"):
            return rows
        page += 1


def create_row(table_id, data, user_field_names=True, timeout=10):
    base_url, headers = _base()
    url = f"{base_url}/api/database/rows/table/{table_id}/"
    params = {"user_field_names": "true"} if user_field_names else {}
    resp = requests.post(url, json=data, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def update_row(table_id, row_id, data, user_field_names=True, timeout=10):
    base_url, headers = _base()
    url = f"{base_url}/api/database/rows/table/{table_id}/{row_id}/"
    params = {"user_field_names": "true"} if user_field_names else {}
    resp = requests.patch(url, json=data, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def delete_row(table_id, row_id, timeout=10):
    base_url, headers = _base()
    url = f"{base_url}/api/database/rows/table/{table_id}/{row_id}/"
    resp = requests.delete(url, headers=headers, timeout=timeout)
    resp.raise_for_status()


def mask_email(email):
    """ca***@example.com — enough to eyeball a log line (pair it with the
    Baserow row id for exact tracing) without persisting full addresses."""
    email = str(email or "")
    if "@" not in email:
        return (email[:2] + "***") if email else "***"
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"
