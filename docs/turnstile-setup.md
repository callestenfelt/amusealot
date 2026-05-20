# Enabling Cloudflare Turnstile on the subscribe form

> **Status: LIVE.** Turnstile was enabled on `amusealot.com` on 2026-05-20; the
> keys live in `/opt/musemaniac/.env` on the VPS. This doc is now mainly a runbook
> for **re-creating or rotating** the widget/keys (e.g. if the secret leaks or the
> Cloudflare account changes). The steps below are unchanged for that purpose.

The `/subscribe` form ships with two bot-protection layers that need **no config**
(honeypot + signed timing token). Cloudflare Turnstile is the third layer — a
privacy-friendly CAPTCHA (no cookies, GDPR-friendly, free) that keeps the site's
"no tracking, no cookies" promise. The code stays dormant until both keys are
present in the environment.

Estimated time: ~5 minutes.

## Steps

1. **Create the Turnstile widget**
   - Go to https://dash.cloudflare.com → **Turnstile** → **Add widget**.
   - Widget name: `amusealot subscribe` (anything).
   - Domain: `amusealot.com` (add `localhost` too if you want to test locally).
   - Widget mode: **Managed** (recommended — invisible for most visitors).
   - Save. Cloudflare shows two keys:
     - **Site Key** (public) → `TURNSTILE_SITEKEY`
     - **Secret Key** (private) → `TURNSTILE_SECRET`

2. **Add the keys to the VPS env**
   ```
   ssh root@77.42.40.207 "nano /opt/musemaniac/.env"
   ```
   Add:
   ```
   TURNSTILE_SITEKEY=0x4AAAAAAA...
   TURNSTILE_SECRET=0x4AAAAAAA...
   ```

3. **Restart the subscriber app** so it picks up the new env.
   (However the Flask app is run/supervised on the VPS — systemd unit, gunicorn,
   etc. Check `systemctl` or the process manager in use, then restart it.)

4. **Verify**
   - Load https://amusealot.com/ — the Turnstile widget should appear above the
     Subscribe button (the `<script>` tag and widget only render when
     `TURNSTILE_SITEKEY` is set).
   - Subscribe with a real test address; confirm you still get the confirmation
     email.
   - Submitting without solving the challenge (or via a direct POST) should be
     rejected with "Verification failed. Please go back and try again."

## How it behaves

- **Disabled (no keys):** honeypot + timing only. Form works normally.
- **Enabled (both keys):** every submission's `cf-turnstile-response` token is
  verified server-side via Cloudflare `siteverify` before any Baserow write or
  email send.
- **Fails closed:** if Cloudflare is unreachable or the token is missing/invalid,
  the signup is rejected. A brief Cloudflare outage will block new signups rather
  than let bots through — an acceptable trade for a low-volume newsletter.

## Local testing (optional)

Add `localhost` as an allowed domain on the widget, set both keys in your local
`.env`, and run `python scripts/subscriber_app.py`. Cloudflare also publishes
[testing keys](https://developers.cloudflare.com/turnstile/troubleshooting/testing/)
that always pass or always fail, useful for exercising both branches.

See also: the "Subscribe form bot protection" section in `CLAUDE.md`.
