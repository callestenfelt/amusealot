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
  GET  /about        — About page
  GET  /sources      — List tracked GitHub sources
  GET  /feedback     — Feedback form
  POST /feedback     — Submit feedback

Requires environment variables:
  BASEROW_URL, BASEROW_TOKEN, RESEND_API_KEY, RESEND_FROM,
  MUSEMANIAC_BASE_URL, SUBSCRIBER_TABLE_ID, FEEDBACK_TABLE_ID, SOURCES_TABLE_ID
"""

import sys
import io
import os
import re
import glob
import secrets
import time
from datetime import datetime, timezone, date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import requests
from flask import Flask, request, render_template, redirect, url_for, Response, send_from_directory

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
EDITION_TABLE_ID = os.environ.get("EDITION_TABLE_ID")  # optional, needed for /archive
FEEDBACK_TABLE_ID = os.environ.get("FEEDBACK_TABLE_ID")  # optional, needed for /feedback
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL")  # optional, feedback notifications
SOURCES_TABLE_ID = os.environ.get("SOURCES_TABLE_ID")  # optional, needed for /sources

BASEROW_HEADERS = {
    "Authorization": f"Token {BASEROW_TOKEN}",
    "Content-Type": "application/json",
}

# --- Flask setup ---
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates", "web"))

if HAS_LIMITER:
    limiter = Limiter(get_remote_address, app=app, default_limits=[])

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

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
            "subject": "Confirm your AmuseAlot subscription",
            "html": html,
        },
    )
    resp.raise_for_status()
    return resp.json()


def send_welcome_email(email, unsubscribe_token):
    """Send the latest newsletter as a welcome email to a newly confirmed subscriber."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pattern = os.path.join(script_dir, "editions", "newsletter_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print(f"No newsletter files found, skipping welcome email for {email}")
        return

    with open(files[0], "r", encoding="utf-8") as f:
        html = f.read()

    unsub_url = f"{BASE_URL}/unsubscribe?token={unsubscribe_token}"
    html = html.replace("%%UNSUBSCRIBE_URL%%", unsub_url)

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM,
            "to": [email],
            "subject": "Welcome to AmuseAlot \u2014 here's our latest issue",
            "html": html,
            "headers": {
                "List-Unsubscribe": f"<{unsub_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click-Unsubscribe",
            },
        },
    )
    resp.raise_for_status()
    print(f"Welcome email sent to {email}")
    return resp.json()


# --- Static files (favicon, share image, webmanifest) ---

STATIC_FILES = {
    "favicon.svg", "favicon.ico", "favicon-96x96.png",
    "apple-touch-icon.png", "web-app-manifest-192x192.png",
    "web-app-manifest-512x512.png", "site.webmanifest", "share.png",
}


@app.route("/<path:filename>")
def static_root_files(filename):
    if filename in STATIC_FILES:
        return send_from_directory(STATIC_DIR, filename)
    return render_template("landing.html", canonical_url=BASE_URL + "/"), 404


# --- SEO routes ---

@app.route("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /subscribe\n"
        "Disallow: /confirm\n"
        "Disallow: /unsubscribe\n"
        "\n"
        "Sitemap: https://amusealot.com/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    today = date.today().isoformat()
    urls = [
        (f"{BASE_URL}/", today),
        (f"{BASE_URL}/about", today),
        (f"{BASE_URL}/sources", today),
        (f"{BASE_URL}/archive", today),
        (f"{BASE_URL}/privacy", today),
    ]
    # Add archive editions
    try:
        editions = get_editions()
        for ed in editions:
            ed_date = ed.get("edition_date", "")
            if ed_date:
                urls.append((f"{BASE_URL}/archive/{ed_date}", ed_date))
    except Exception as e:
        print(f"ERROR building sitemap editions: {e}")

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, lastmod in urls:
        xml_parts.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
    xml_parts.append("</urlset>")
    return Response("\n".join(xml_parts), mimetype="application/xml")


# --- Routes ---

@app.route("/")
def landing():
    return render_template("landing.html", canonical_url=BASE_URL + "/")


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
            now = date.today().isoformat()
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
    now = date.today().isoformat()

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

    now = date.today().isoformat()
    baserow_update_row(row["id"], {
        "status": "confirmed",
        "confirmed_at": now,
    })

    try:
        send_welcome_email(row.get("email", ""), row.get("unsubscribe_token", ""))
    except Exception as e:
        print(f"ERROR sending welcome email to {row.get('email', '')}: {e}")

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

    now = date.today().isoformat()
    baserow_update_row(row["id"], {
        "status": "unsubscribed",
        "unsubscribed_at": now,
    })

    return render_template("unsubscribe_success.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", canonical_url=BASE_URL + "/privacy")


@app.route("/about")
def about():
    return render_template("about.html", canonical_url=BASE_URL + "/about")


# --- Sources ---

_sources_cache = {"data": None, "time": 0}
SOURCES_CACHE_TTL = 3600  # 1 hour


def get_sources():
    """Fetch tracked sources from Baserow with a 1-hour TTL cache."""
    now = time.time()
    if _sources_cache["data"] is not None and now - _sources_cache["time"] < SOURCES_CACHE_TTL:
        return _sources_cache["data"]

    if not SOURCES_TABLE_ID:
        return []

    try:
        sources = []
        page = 1
        while True:
            resp = requests.get(
                f"{BASEROW_URL}/api/database/rows/table/{SOURCES_TABLE_ID}/",
                params={
                    "size": 200,
                    "page": page,
                    "filter__field_7222__not_empty": "true",
                },
                headers=BASEROW_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
            for row in data.get("results", []):
                entity_type = row.get("field_7225")
                if isinstance(entity_type, dict):
                    entity_type = entity_type.get("value", "")
                sources.append({
                    "name": row.get("field_7191") or "",
                    "github": row.get("field_7222") or "",
                    "github_url": row.get("field_7223") or "",
                    "entity_type": entity_type or "",
                    "country": row.get("field_7192") or "",
                })
            if not data.get("next"):
                break
            page += 1

        sources.sort(key=lambda s: s["name"].lower())
        _sources_cache["data"] = sources
        _sources_cache["time"] = now
        return sources
    except Exception as e:
        print(f"ERROR fetching sources: {e}")
        if _sources_cache["data"] is not None:
            return _sources_cache["data"]
        return []


@app.route("/sources")
def sources():
    source_list = get_sources()
    countries = set(s["country"] for s in source_list if s["country"])
    return render_template("sources.html",
                           sources=source_list,
                           total=len(source_list),
                           country_count=len(countries),
                           canonical_url=BASE_URL + "/sources")


# --- Archive routes ---

def get_editions():
    """Fetch all editions from Baserow, sorted by date descending."""
    if not EDITION_TABLE_ID:
        return []
    editions = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASEROW_URL}/api/database/rows/table/{EDITION_TABLE_ID}/",
            params={
                "size": 200,
                "page": page,
                "user_field_names": "true",
                "order_by": "-edition_date",
            },
            headers=BASEROW_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        editions.extend(data.get("results", []))
        if not data.get("next"):
            break
        page += 1
    return editions


def find_edition_by_date(edition_date):
    """Find a single edition by date string (YYYY-MM-DD)."""
    if not EDITION_TABLE_ID:
        return None
    editions = get_editions()
    for ed in editions:
        if ed.get("edition_date") == edition_date:
            return ed
    return None


@app.route("/archive")
def archive():
    editions = get_editions()
    # Format dates for display
    for ed in editions:
        raw = ed.get("edition_date", "")
        if raw:
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d")
                ed["display_date"] = dt.strftime("%B %d, %Y")
            except ValueError:
                ed["display_date"] = raw
        else:
            ed["display_date"] = ""
    return render_template("archive.html", editions=editions, canonical_url=BASE_URL + "/archive")


@app.route("/archive/<edition_date>")
def archive_edition(edition_date):
    # Validate date format
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", edition_date):
        return render_template("archive.html", editions=[], error="Invalid date format."), 404

    edition = find_edition_by_date(edition_date)
    file_name = edition.get("file_name", "") if edition else ""
    if not file_name:
        file_name = f"newsletter_{edition_date}.html"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "editions", file_name)

    if not os.path.exists(file_path):
        return render_template("archive.html", editions=[], error="Edition not found."), 404

    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Replace unsubscribe placeholder with generic landing page link
    html = html.replace("%%UNSUBSCRIBE_URL%%", f"{BASE_URL}/unsubscribe")

    # Inject back-to-archive nav bar at the top of <body>
    nav_bar = (
        '<div style="background-color:#080229;padding:12px 24px;text-align:center;">'
        '<a href="/archive" style="color:#fbfbfb;font-size:14px;text-decoration:underline;text-underline-offset:3px;font-family:Arial,sans-serif;">'
        'Back to Archive</a></div>'
    )
    # Insert after the first > that closes the <body> tag
    body_idx = html.find("<body")
    if body_idx != -1:
        close_idx = html.find(">", body_idx)
        if close_idx != -1:
            html = html[:close_idx + 1] + nav_bar + html[close_idx + 1:]

    return html


# --- Feedback routes ---

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def create_feedback_row(data):
    """Create a row in the feedback table."""
    if not FEEDBACK_TABLE_ID:
        return None
    url = f"{BASEROW_URL}/api/database/rows/table/{FEEDBACK_TABLE_ID}/"
    params = {"user_field_names": "true"}
    resp = requests.post(url, json=data, params=params, headers=BASEROW_HEADERS)
    resp.raise_for_status()
    return resp.json()


feedback_get_route = app.route("/feedback", methods=["GET"])


def _feedback_get():
    if not FEEDBACK_TABLE_ID:
        return "Feedback not configured", 503
    edition = request.args.get("edition", "").strip()
    rating = request.args.get("rating", "").strip()
    # Validate edition if provided
    if edition and not DATE_RE.match(edition):
        edition = ""
    # Validate rating if provided
    try:
        rating = int(rating) if rating else 0
    except ValueError:
        rating = 0
    if rating < 1 or rating > 5:
        rating = 0
    return render_template("feedback.html", edition=edition, rating=rating, canonical_url=BASE_URL + "/feedback")


if HAS_LIMITER:
    _feedback_get = limiter.limit("20/day")(_feedback_get)
_feedback_get = feedback_get_route(_feedback_get)


feedback_post_route = app.route("/feedback", methods=["POST"])


def _feedback_post():
    if not FEEDBACK_TABLE_ID:
        return "Feedback not configured", 503

    edition = request.form.get("edition", "").strip()
    rating_str = request.form.get("rating", "").strip()
    feedback_text = request.form.get("feedback_text", "").strip()
    suggest_org = request.form.get("suggest_org", "").strip()
    email = request.form.get("email", "").strip()

    # Parse rating (optional)
    try:
        rating = int(rating_str)
        if rating < 1 or rating > 5:
            rating = 0
    except (ValueError, TypeError):
        rating = 0

    # Validate edition date if provided
    if edition and not DATE_RE.match(edition):
        edition = ""

    # Build row data
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    row_data = {
        "feedback_text": feedback_text,
        "suggest_org": suggest_org,
        "email": email,
        "created_at": now,
    }
    if rating:
        row_data["rating"] = rating
    if edition:
        row_data["edition_date"] = edition

    try:
        create_feedback_row(row_data)
    except Exception as e:
        print(f"ERROR creating feedback row: {e}")
        return render_template("feedback.html", edition=edition, rating=rating,
                               error="Something went wrong. Please try again."), 500

    # Send notification email
    if NOTIFY_EMAIL:
        try:
            parts = []
            if rating:
                parts.append(f"Rating: {'★' * rating}{'☆' * (5 - rating)}")
            if edition:
                parts.append(f"Edition: {edition}")
            if feedback_text:
                parts.append(f"Feedback: {feedback_text}")
            if suggest_org:
                parts.append(f"Suggested org: {suggest_org}")
            if email:
                parts.append(f"From: {email}")
            body = "\n\n".join(parts) if parts else "(empty submission)"
            requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": RESEND_FROM,
                    "to": [NOTIFY_EMAIL],
                    "subject": "AmuseAlot: New feedback received",
                    "text": body,
                },
            )
        except Exception as e:
            print(f"ERROR sending feedback notification: {e}")

    return render_template("feedback_success.html")


if HAS_LIMITER:
    _feedback_post = limiter.limit("20/day")(_feedback_post)
_feedback_post = feedback_post_route(_feedback_post)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5680, debug=False)
