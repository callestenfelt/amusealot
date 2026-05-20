# Next steps

Living checklist of follow-ups after the May 2026 subscription-bombing defense
work. The core fix is **done**: three-layer bot protection (honeypot + timing +
Cloudflare Turnstile) is live in production, Turnstile was enabled and verified on
2026-05-20, and the stale `pending` bot rows were cleared manually from Baserow.

## Open

- [ ] **Verify the attack is blocked (give it a few days).** Bot signups should
      drop sharply.
  - Cloudflare → Turnstile widget page shows challenge / solve / block counts.
  - Baserow: daily `pending` signups should fall back toward the normal 1–5/day
    (vs. the 12 / 54 / 26 / 22 spike on May 17–20).
- [ ] **Automate pending-row cleanup (optional).** Add a VPS cron to run
      `python scripts/purge_pending_subscribers.py --apply` (e.g. monthly, default
      30-day cutoff) so stale rows never pile up again.
- [ ] **Housekeeping:** decide whether `scripts/latest_news.json` (generated
      runtime artifact) should be added to `.gitignore` so it stops showing up in
      `git status`.

## Done

- [x] Diagnosed subscription-bombing attack (May 17–20 2026 spike, ~100 stuck
      `pending` rows).
- [x] Added honeypot + signed timing token + Cloudflare Turnstile to `/subscribe`.
- [x] Merged to master, deployed to VPS, restarted `musemaniac-subscriber.service`.
- [x] Enabled Turnstile in production (keys in `/opt/musemaniac/.env`); verified
      the widget renders on the public site.
- [x] Cleared stale `pending` bot rows from Baserow (manual, filtered by status).
- [x] Updated docs: `CLAUDE.md`, `docs/turnstile-setup.md`, `README.md`,
      `.env.example`.
