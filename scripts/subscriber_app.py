#!/usr/bin/env python3
"""
Flask web app for newsletter subscriber management.

Routes:
  GET  /             — Landing page with subscribe form
  POST /subscribe    — Handle subscription (double opt-in)
  GET  /confirm      — Confirm email via token
  GET  /unsubscribe  — Unsubscribe via token
  POST /unsubscribe  — One-click unsubscribe (RFC 8058)
  GET  /privacy      — Privacy policy

Requires environment variables:
  BASEROW_URL, BASEROW_TOKEN, RESEND_API_KEY, RESEND_FROM,
  MUSEMANIAC_BASE_URL, SUBSCRIBER_TABLE_ID
"""

import sys
import io
import os
import re
import secrets
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import requests
from flask import Flask, request, render_template, redirect, url_for

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    HAS_LIMITER = True
except ImportError:
    HAS_LIMITER = False
    print("WARNING: flask-limiter not installed, rate limiting disabled")

# --- Config from environment ---
BASEROW_URL = os.environ["BASEROW_URL"]
BASEROW_TOKEN = os.environ["BASEROW_TOKEN"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
RESEND_FROM = os.environ["RESEND_FROM"]
BASE_URL = os.environ["MUSEMANIAC_BASE_URL"]  # e.g. https://amusealot.com
SUBSCRIBER_TABLE_ID = os.environ["SUBSCRIBER_TABLE_ID"]

BASEROW_HEADERS = {
    "Authorization": f"Token {BASEROW_TOKEN}",
    "Content-Type": "application/json",
}

# --- Flask setup ---
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates", "web"))

if HAS_LIMITER:
    limiter = Limiter(get_remote_address, app=app, default_limits=[])

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


# --- Baserow helpers ---

def baserow_list_rows(filters=None):
    """Fetch rows from the subscribers table with optional filters."""
    url = f"{BASEROW_URL}/api/database/rows/table/{SUBSCRIBER_TABLE_ID}/"
    params = {"size": 200, "user_field_names": "true"}
    if filters:
        params.update(filters)
    resp = requests.get(url, params=params, headers=BASEROW_HEADERS)
    resp.raise_for_status()
    return resp.json().get("results", [])


def baserow_create_row(data):
    """Create a row in the subscribers table."""
    url = f"{BASEROW_URL}/api/database/rows/table/{SUBSCRIBER_TABLE_ID}/"
    params = {"user_field_names": "true"}
    resp = requests.post(url, json=data, params=params, headers=BASEROW_HEADERS)
    resp.raise_for_status()
    return resp.json()


def baserow_update_row(row_id, data):
    """Update a row in the subscribers table."""
    url = f"{BASEROW_URL}/api/database/rows/table/{SUBSCRIBER_TABLE_ID}/{row_id}/"
    params = {"user_field_names": "true"}
    resp = requests.patch(url, json=data, params=params, headers=BASEROW_HEADERS)
    resp.raise_for_status()
    return resp.json()


def find_row_by_field(field_name, value):
    """Find a single row where field equals value."""
    rows = baserow_list_rows({f"filter__field_{field_name}__equal": value})
    return rows[0] if rows else None


def find_row_by_token(field_name, token):
    """Find a row by token field using search."""
    # Use Baserow search to find token
    rows = baserow_list_rows({"search": token})
    for row in rows:
        if row.get(field_name) == token:
            return row
    return None


# --- Resend helper ---

def send_confirmation_email(email, confirm_url):
    """Send the double opt-in confirmation email via Resend API."""
    template_path = os.path.join(os.path.dirname(__file__), "templates", "confirmation_email.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("%%CONFIRM_URL%%", confirm_url)

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM,
            "to": [email],
            "subject": "Confirm your Musemaniac subscription",
            "html": html,
        },
    )
    resp.raise_for_status()
    return resp.json()


# --- Routes ---

@app.route("/")
def landing():
    return render_template("landing.html")


subscribe_route = app.route("/subscribe", methods=["POST"])

def _subscribe():
    email = request.form.get("email", "").strip().lower()

    if not email or not EMAIL_RE.match(email):
        return render_template("subscribe_success.html",
                               error="Please enter a valid email address."), 400

    # Check for existing subscriber
    existing = find_row_by_token("email", email)

    if existing:
        status = existing.get("status", {})
        status_value = status.get("value", "") if isinstance(status, dict) else str(status)

        if status_value == "confirmed":
            # Already subscribed — show success anyway (don't reveal subscription status)
            return render_template("subscribe_success.html")
        elif status_value == "pending":
            # Resend confirmation
            confirm_token = existing.get("confirm_token", "")
            if confirm_token:
                confirm_url = f"{BASE_URL}/confirm?token={confirm_token}"
                try:
                    send_confirmation_email(email, confirm_url)
                except Exception as e:
                    print(f"ERROR sending confirmation to {email}: {e}")
            return render_template("subscribe_success.html")
        elif status_value == "unsubscribed":
            # Re-subscribe: generate new tokens, set to pending
            confirm_token = secrets.token_urlsafe(32)
            unsubscribe_token = existing.get("unsubscribe_token") or secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc).isoformat()
            baserow_update_row(existing["id"], {
                "status": "pending",
                "subscribed_at": now,
                "confirmed_at": None,
                "unsubscribed_at": None,
                "confirm_token": confirm_token,
                "unsubscribe_token": unsubscribe_token,
                "consent_source": "web_form",
            })
            confirm_url = f"{BASE_URL}/confirm?token={confirm_token}"
            try:
                send_confirmation_email(email, confirm_url)
            except Exception as e:
                print(f"ERROR sending confirmation to {email}: {e}")
            return render_template("subscribe_success.html")

    # New subscriber
    confirm_token = secrets.token_urlsafe(32)
    unsubscribe_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()

    baserow_create_row({
        "email": email,
        "status": "pending",
        "subscribed_at": now,
        "confirm_token": confirm_token,
        "unsubscribe_token": unsubscribe_token,
        "consent_source": "web_form",
    })

    confirm_url = f"{BASE_URL}/confirm?token={confirm_token}"
    try:
        send_confirmation_email(email, confirm_url)
    except Exception as e:
        print(f"ERROR sending confirmation to {email}: {e}")

    return render_template("subscribe_success.html")


# Apply rate limiter if available, then register the route
if HAS_LIMITER:
    _subscribe = limiter.limit("10/hour")(_subscribe)
_subscribe = subscribe_route(_subscribe)


@app.route("/confirm")
def confirm():
    token = request.args.get("token", "").strip()
    if not token:
        return render_template("confirm_error.html"), 400

    row = find_row_by_token("confirm_token", token)
    if not row:
        return render_template("confirm_error.html"), 404

    status = row.get("status", {})
    status_value = status.get("value", "") if isinstance(status, dict) else str(status)

    if status_value == "confirmed":
        return render_template("confirm_success.html")

    if status_value != "pending":
        return render_template("confirm_error.html"), 400

    now = datetime.now(timezone.utc).isoformat()
    baserow_update_row(row["id"], {
        "status": "confirmed",
        "confirmed_at": now,
    })

    return render_template("confirm_success.html")


@app.route("/unsubscribe", methods=["GET", "POST"])
def unsubscribe():
    token = request.args.get("token", "").strip()
    if not token:
        # RFC 8058: POST body may contain List-Unsubscribe=One-Click-Unsubscribe
        token = request.form.get("token", "").strip()
    if not token:
        return render_template("unsubscribe_error.html"), 400

    row = find_row_by_token("unsubscribe_token", token)
    if not row:
        return render_template("unsubscribe_error.html"), 404

    status = row.get("status", {})
    status_value = status.get("value", "") if isinstance(status, dict) else str(status)

    if status_value == "unsubscribed":
        return render_template("unsubscribe_success.html")

    now = datetime.now(timezone.utc).isoformat()
    baserow_update_row(row["id"], {
        "status": "unsubscribed",
        "unsubscribed_at": now,
    })

    return render_template("unsubscribe_success.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5680, debug=False)
