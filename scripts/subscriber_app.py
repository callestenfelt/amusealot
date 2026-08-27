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
import json
import hmac
import hashlib
import secrets
import time
from datetime import datetime, timezone, date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import requests
from flask import Flask, request, render_template, redirect, url_for, Response, send_from_directory, abort
from werkzeug.middleware.proxy_fix import ProxyFix

import baserow_client
from baserow_config import SOURCES_FIELDS

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
NEWS_SOURCES_TABLE_ID = os.environ.get("NEWS_SOURCES_TABLE_ID")  # optional, news RSS sources

# --- Bot protection ---
# Cloudflare Turnstile (privacy-friendly CAPTCHA, no cookies). Both must be set
# for the hard gate to activate; if unset, only honeypot + timing apply.
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY")  # public, rendered in the form
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET")    # private, used for siteverify
# Secret for signing the form-render timestamp (timing check). A per-process
# fallback is fine — at worst, forms rendered before a restart are rejected and
# the visitor simply resubmits.
FORM_SECRET = os.environ.get("FORM_SECRET") or secrets.token_hex(32)
MIN_FORM_AGE = 3       # seconds; a human can't fill + submit faster than this
MAX_FORM_AGE = 7200    # seconds (2h); reject stale/replayed render tokens

BASEROW_HEADERS = {
    "Authorization": f"Token {BASEROW_TOKEN}",
    "Content-Type": "application/json",
}

# --- Flask setup ---
app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates", "web"))
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024  # reject request bodies larger than 256 KB

# The app sits behind Caddy on localhost, so request.remote_addr is 127.0.0.1
# for every request and the rate limiter throttles all visitors as one client.
# Trust exactly one X-Forwarded-For hop: Caddy (v2.5+) strips any
# client-supplied X-Forwarded-For unless trusted_proxies is configured (it
# isn't), so the single value is always the real client IP. This holds only
# while nothing reaches the port except Caddy — hence the app binds 127.0.0.1
# (see __main__) and the VPS firewall doesn't open 5680.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

if HAS_LIMITER:
    limiter = Limiter(get_remote_address, app=app, default_limits=[])


def _rate_limit(spec):
    """Decorator applying a flask-limiter limit when available, else a no-op."""
    if HAS_LIMITER:
        return limiter.limit(spec)
    return lambda f: f


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


# --- Bot protection helpers ---

def make_form_token():
    """Return a signed render timestamp for the timing check (form_ts field)."""
    ts = str(int(time.time()))
    sig = hmac.new(FORM_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{ts}.{sig}"


def form_token_ok(token, min_age=MIN_FORM_AGE):
    """Validate a form_ts token: correct signature and a human-plausible age."""
    try:
        ts_str, sig = token.split(".", 1)
        expected = hmac.new(FORM_SECRET.encode(), ts_str.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return False
        age = time.time() - int(ts_str)
        return min_age <= age <= MAX_FORM_AGE
    except (ValueError, AttributeError):
        return False


def bot_check_failed(form, label, min_age=MIN_FORM_AGE):
    """Shared honeypot + timing gate for POSTed forms.

    Returns True when the submission looks bot-like; the caller renders its
    normal success page so the drop stays silent (bots can't detect the trap).
    """
    # 1. Honeypot: a field hidden from humans; only bots fill it.
    if form.get("company_website", "").strip():
        print(f"Bot {label} blocked: honeypot filled")
        return True
    # 2. Timing: reject submissions that arrive implausibly fast or with a
    #    missing/forged render token.
    if not form_token_ok(form.get("form_ts", ""), min_age=min_age):
        print(f"Bot {label} blocked: timing/token check failed")
        return True
    return False


def verify_turnstile(token):
    """Verify a Cloudflare Turnstile token. Returns True if disabled (no secret).

    Fails closed: a missing token or a verification error counts as failure, so a
    Cloudflare outage briefly blocks signups rather than letting bots through.

    Deliberately does NOT send the optional remoteip field — the privacy policy
    promises we don't hand visitor IPs to third parties.
    """
    if not TURNSTILE_SECRET:
        return True  # gate not configured — honeypot + timing still apply
    if not token:
        return False
    try:
        data = {"secret": TURNSTILE_SECRET, "response": token}
        resp = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=data,
            timeout=10,
        )
        resp.raise_for_status()
        return bool(resp.json().get("success"))
    except Exception as e:
        print(f"ERROR verifying Turnstile token: {e}")
        return False


# --- Baserow helpers ---

# Thin wrappers around the shared baserow_client, pinned to the subscribers
# table — routes call these; the pagination/CRUD mechanics live in one place
# shared with the ops scripts (purge_pending_subscribers).

def baserow_list_rows(filters=None):
    """Fetch rows from the subscribers table with optional filters (paginated)."""
    return baserow_client.list_rows(SUBSCRIBER_TABLE_ID, filters=filters)


def baserow_create_row(data):
    """Create a row in the subscribers table."""
    return baserow_client.create_row(SUBSCRIBER_TABLE_ID, data)


def baserow_update_row(row_id, data):
    """Update a row in the subscribers table."""
    return baserow_client.update_row(SUBSCRIBER_TABLE_ID, row_id, data)


def baserow_delete_row(row_id):
    """Delete a row from the subscribers table."""
    return baserow_client.delete_row(SUBSCRIBER_TABLE_ID, row_id)


def find_row_by_token(field_name, token):
    """Find a row by token field using search (constant-time comparison)."""
    # Baserow search narrows the candidates; compare_digest avoids leaking
    # token prefixes through comparison timing on the exact match. Compare as
    # bytes — the str overload raises TypeError on non-ASCII input (a crafted
    # ?token=påhitt would 500 instead of 404).
    rows = baserow_list_rows({"search": token})
    for row in rows:
        value = row.get(field_name)
        if isinstance(value, str) and hmac.compare_digest(
                value.encode("utf-8"), token.encode("utf-8")):
            return row
    return None


def find_rows_by_email(email):
    """All rows with exactly this email (server-side filter, not full-text search)."""
    return baserow_list_rows({"filter__email__equal": email})


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
        timeout=10,
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
        timeout=10,
    )
    resp.raise_for_status()
    print(f"Welcome email sent to {email}")
    return resp.json()


# --- Static files (favicon, share image, webmanifest) ---

STATIC_FILES = {
    "favicon.svg", "favicon.ico", "favicon-96x96.png",
    "apple-touch-icon.png", "web-app-manifest-192x192.png",
    "web-app-manifest-512x512.png", "site.webmanifest", "share.png",
    "logo_footer.svg", "bluesky.svg", "bathing_in_code.webp",
    # Self-hosted fonts (OFL): served locally so the site keeps its
    # "no tracking" promise — no visitor request ever reaches Google.
    "fonts/rammetto-one-latin.woff2", "fonts/rammetto-one-latin-ext.woff2",
    "fonts/archivo-var-latin.woff2", "fonts/archivo-var-latin-ext.woff2",
}


@app.route("/<path:filename>")
def static_root_files(filename):
    if filename in STATIC_FILES:
        return send_from_directory(STATIC_DIR, filename)
    # Real 404 (previously the landing page body with a 404 status — a
    # soft-404). abort() routes through the errorhandler below, keeping a
    # single source for how 404s render.
    abort(404)


@app.errorhandler(404)
def not_found(e):
    return render_template("not_found.html"), 404


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
    # Add archive editions (dates come from Baserow — only well-formed
    # YYYY-MM-DD values may reach the XML, both as URL path and lastmod)
    try:
        editions = get_editions()
        for ed in editions:
            ed_date = ed.get("edition_date", "")
            if ed_date and DATE_RE.match(ed_date):
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
    sources = get_sources()
    total_sources = len(sources)
    countries = set()
    for source in sources:
        country = source.get("country")
        if isinstance(country, dict):
            country = country.get("value", "")
        if country:
            countries.add(country)
    latest_news = get_latest_news()
    return render_template("landing.html",
                           canonical_url=BASE_URL + "/",
                           total_sources=total_sources,
                           total_countries=len(countries),
                           latest_news=latest_news,
                           form_ts=make_form_token(),
                           turnstile_sitekey=TURNSTILE_SITEKEY)


subscribe_route = app.route("/subscribe", methods=["POST"])

def _subscribe():
    # Bot protection (subscription-bombing defense): honeypot + timing,
    # shared with /feedback — see bot_check_failed
    if bot_check_failed(request.form, "signup"):
        return render_template("subscribe_success.html")

    email = request.form.get("email", "").strip().lower()

    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        return render_template("subscribe_success.html",
                               error="Please enter a valid email address."), 400

    # 3. Turnstile hard gate (active only when TURNSTILE_SECRET is set). The
    #    widget is visible, so a failure gets honest user-facing feedback.
    if not verify_turnstile(request.form.get("cf-turnstile-response", "")):
        print(f"Subscribe blocked: Turnstile verification failed for {email}")
        return render_template("subscribe_success.html",
                               error="Verification failed. Please go back and try again."), 400

    # Check for existing subscriber (exact server-side filter — cheaper than
    # full-text search and needs no client-side re-check)
    existing_rows = find_rows_by_email(email)
    existing = existing_rows[0] if existing_rows else None

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
            try:
                baserow_update_row(existing["id"], {
                    "status": "pending",
                    "subscribed_at": now,
                    "confirmed_at": None,
                    "unsubscribed_at": None,
                    "confirm_token": confirm_token,
                    "unsubscribe_token": unsubscribe_token,
                    "consent_source": "web_form",
                })
            except Exception as e:
                print(f"ERROR updating subscriber row for {email}: {e}")
                return render_template("subscribe_success.html")
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

    try:
        created = baserow_create_row({
            "email": email,
            "status": "pending",
            "subscribed_at": now,
            "confirm_token": confirm_token,
            "unsubscribe_token": unsubscribe_token,
            "consent_source": "web_form",
        })
    except Exception as e:
        # Baserow write failed — log it but still show success so we don't leak
        # backend errors to visitors (they can simply try again later).
        print(f"ERROR creating subscriber row for {email}: {e}")
        return render_template("subscribe_success.html")

    # Double-submit race: two parallel POSTs can both pass the "existing" check
    # above and each create a row. Re-query and keep only the oldest row
    # (lowest id) — both racers run the same deterministic cleanup, so exactly
    # one row survives. Each delete tolerates failure individually: the other
    # racer may have deleted that row first (404), and that must not skip the
    # "did my row lose" check below, or the loser would still send a
    # confirmation email carrying its just-deleted row's token.
    dupes = []
    try:
        dupes = sorted(find_rows_by_email(email), key=lambda r: r["id"])
    except Exception as e:
        # Listing is best-effort; a leftover duplicate row is harmless enough
        # (only one gets confirmed) and can be removed manually.
        print(f"WARNING: duplicate check failed for {email}: {e}")
    for loser in dupes[1:]:
        try:
            baserow_delete_row(loser["id"])
            print(f"Deleted duplicate subscriber row {loser['id']} for {email} (double submit)")
        except Exception as e:
            print(f"WARNING: could not delete duplicate row {loser['id']} for {email}: {e}")
    if dupes and dupes[0]["id"] != created["id"]:
        # Our row lost the race — the winning request sends its own email
        return render_template("subscribe_success.html")

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
@_rate_limit("30/minute")
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
    try:
        baserow_update_row(row["id"], {
            "status": "confirmed",
            "confirmed_at": now,
        })
    except Exception as e:
        print(f"ERROR confirming subscriber {row.get('email', '')}: {e}")
        return render_template("confirm_error.html"), 503

    try:
        send_welcome_email(row.get("email", ""), row.get("unsubscribe_token", ""))
    except Exception as e:
        print(f"ERROR sending welcome email to {row.get('email', '')}: {e}")

    return render_template("confirm_success.html")


@app.route("/unsubscribe", methods=["GET", "POST"])
@_rate_limit("30/minute")
def unsubscribe():
    # State only changes on POST. Mail-security scanners (Outlook SafeLinks,
    # Mimecast, corporate prefetchers) GET every link in an email — if GET
    # unsubscribed, a scanner could silently remove a real reader. The GET
    # renders a confirmation page whose button POSTs back; RFC 8058 one-click
    # (List-Unsubscribe-Post) already POSTs directly, so mail clients'
    # unsubscribe buttons keep working with no page in between.
    token = request.args.get("token", "").strip()
    if not token:
        # RFC 8058: the token may arrive in the POST body
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

    if request.method == "GET":
        return render_template("unsubscribe_confirm.html", token=token)

    now = date.today().isoformat()
    try:
        baserow_update_row(row["id"], {
            "status": "unsubscribed",
            "unsubscribed_at": now,
        })
    except Exception as e:
        print(f"ERROR unsubscribing {row.get('email', '')}: {e}")
        return render_template("unsubscribe_error.html"), 503

    return render_template("unsubscribe_success.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", canonical_url=BASE_URL + "/privacy")


@app.route("/about")
def about():
    # Get source stats for dynamic count
    sources = get_sources()
    total_sources = len(sources)
    countries = set()
    for source in sources:
        country = source.get("country")
        if isinstance(country, dict):
            country = country.get("value", "")
        if country:
            countries.add(country)
    total_countries = len(countries)

    return render_template("about.html",
                         canonical_url=BASE_URL + "/about",
                         total_sources=total_sources,
                         total_countries=total_countries)


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
        rows = baserow_client.list_rows(
            SOURCES_TABLE_ID,
            filters={f"filter__{SOURCES_FIELDS['github']}__not_empty": "true"},
            user_field_names=False,
        )
        sources = []
        for row in rows:
            entity_type = row.get(SOURCES_FIELDS["entity_type"])
            if isinstance(entity_type, dict):
                entity_type = entity_type.get("value", "")
            sources.append({
                "name": row.get(SOURCES_FIELDS["name"]) or "",
                "github": row.get(SOURCES_FIELDS["github"]) or "",
                "github_url": row.get(SOURCES_FIELDS["github_url"]) or "",
                "entity_type": entity_type or "",
                "country": row.get(SOURCES_FIELDS["country"]) or "",
            })

        sources.sort(key=lambda s: s["name"].lower())
        _sources_cache["data"] = sources
        _sources_cache["time"] = now
        return sources
    except Exception as e:
        print(f"ERROR fetching sources: {e}")
        if _sources_cache["data"] is not None:
            return _sources_cache["data"]
        return []


def get_latest_news():
    """Load latest_news.json written by generate_newsletter.py after each edition."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_news.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"date": None, "articles": []}


_news_sources_cache = {"data": None, "time": 0}


def get_news_sources():
    """Fetch active RSS news sources from Baserow with a 1-hour TTL cache."""
    now = time.time()
    if _news_sources_cache["data"] is not None and now - _news_sources_cache["time"] < SOURCES_CACHE_TTL:
        return _news_sources_cache["data"]

    if not NEWS_SOURCES_TABLE_ID:
        return []

    try:
        sources = []
        for row in baserow_client.list_rows(NEWS_SOURCES_TABLE_ID):
            if not row.get("active"):
                continue
            country = row.get("country") or {}
            language = row.get("language") or {}
            sources.append({
                "name": row.get("name", ""),
                "country": country.get("value", "") if isinstance(country, dict) else str(country),
                "language": language.get("value", "") if isinstance(language, dict) else str(language),
                "focus_area": row.get("focus_area", "") or "",
                "rss_url": row.get("rss_url", "") or "",
            })
        sources.sort(key=lambda s: s["name"].lower())
        _news_sources_cache["data"] = sources
        _news_sources_cache["time"] = now
        return sources
    except Exception as e:
        print(f"ERROR fetching news sources: {e}")
        if _news_sources_cache["data"] is not None:
            return _news_sources_cache["data"]
        return []


@app.route("/sources")
def sources():
    source_list = get_sources()
    news_list = get_news_sources()
    countries = set(s["country"] for s in source_list if s["country"])
    return render_template("sources.html",
                           sources=source_list,
                           total=len(source_list),
                           country_count=len(countries),
                           news_sources=news_list,
                           news_total=len(news_list),
                           canonical_url=BASE_URL + "/sources")


# --- Archive routes ---

def get_editions():
    """Fetch all editions from Baserow, sorted by date descending."""
    if not EDITION_TABLE_ID:
        return []
    return baserow_client.list_rows(EDITION_TABLE_ID,
                                    filters={"order_by": "-edition_date"})


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
    # file_name comes from Baserow — never let a path component escape editions/
    file_name = os.path.basename(file_name)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "editions", file_name)

    if not os.path.exists(file_path):
        return render_template("archive.html", editions=[], error="Edition not found."), 404

    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Replace unsubscribe placeholder with generic landing page link
    html = html.replace("%%UNSUBSCRIBE_URL%%", f"{BASE_URL}/unsubscribe")

    # Inject responsive CSS for web viewing (email clients never see this)
    responsive_css = (
        '<style type="text/css">'
        '@media screen and (max-width:620px){'
        'table[width="600"]{width:100%!important;}'
        'td[style*="font-size:78px"]{font-size:clamp(36px,11vw,78px)!important;letter-spacing:-1px!important;}'
        'td[style*="letter-spacing:4.5px"]{letter-spacing:2px!important;font-size:11px!important;}'
        'td[style*="px 40px"]{padding-left:20px!important;padding-right:20px!important;}'
        'td[style*=":0 40px"]{padding-left:20px!important;padding-right:20px!important;}'
        '}'
        '</style>'
    )
    head_close = html.find("</head>")
    if head_close != -1:
        html = html[:head_close] + responsive_css + html[head_close:]

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
    resp = requests.post(url, json=data, params=params, headers=BASEROW_HEADERS, timeout=10)
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
    return render_template("feedback.html", edition=edition, rating=rating,
                           form_ts=make_form_token(),
                           canonical_url=BASE_URL + "/feedback")


if HAS_LIMITER:
    _feedback_get = limiter.limit("20/day")(_feedback_get)
_feedback_get = feedback_get_route(_feedback_get)


feedback_post_route = app.route("/feedback", methods=["POST"])


def _feedback_post():
    if not FEEDBACK_TABLE_ID:
        return "Feedback not configured", 503

    # Bot protection (same honeypot + timing layers as /subscribe — an
    # unprotected POST here fires a Resend notification email per request).
    # min_age=1 (not the subscribe form's 3s): a reader following a rating
    # link from the newsletter lands with the stars prefilled and can
    # legitimately submit within a couple of seconds.
    if bot_check_failed(request.form, "feedback", min_age=1):
        return render_template("feedback_success.html")

    edition = request.form.get("edition", "").strip()
    rating_str = request.form.get("rating", "").strip()
    feedback_text = request.form.get("feedback_text", "").strip()[:5000]
    suggest_org = request.form.get("suggest_org", "").strip()[:500]
    email = request.form.get("email", "").strip()[:254]

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
        # Re-render with the SUBMITTED token, not a fresh one: it already
        # passed the min-age check and stays valid for 2h, so an immediate
        # retry click isn't silently swallowed as "too fast".
        return render_template("feedback.html", edition=edition, rating=rating,
                               form_ts=request.form.get("form_ts", ""),
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
                timeout=10,
            )
        except Exception as e:
            print(f"ERROR sending feedback notification: {e}")

    return render_template("feedback_success.html")


if HAS_LIMITER:
    _feedback_post = limiter.limit("20/day")(_feedback_post)
_feedback_post = feedback_post_route(_feedback_post)


if __name__ == "__main__":
    # Loopback only: the app is only ever reached through Caddy's reverse
    # proxy. Binding wider would let anyone who reaches the port directly
    # forge X-Forwarded-For past ProxyFix and evade the rate limiter.
    app.run(host="127.0.0.1", port=5680, debug=False)
