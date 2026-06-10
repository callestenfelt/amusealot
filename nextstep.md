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

---

# Newsletter: Outlook Windows dark-mode white-on-white (June 2026)

Users on **classic Outlook for Windows desktop** (Word rendering engine) reported
white-on-white body text in dark mode. Root cause: the template's dark-mode
defenses didn't reach that client — `mso-color-alt` is an inert no-op for
inversion, `[data-ogsc]/[data-ogsb]` are only injected by Outlook.com/new
Outlook/mobile, and `meta color-scheme` is ignored by the Word engine. Outlook
ran its own per-element colour inversion and desynced text from its inherited
background. **Fix:** pair an explicit `background-color` with `color` on every
text cell (same element) so the invert stays coherent — worst case is a readable
dark render, not white-on-white. Removed the inert `mso-color-alt` everywhere.
Details in `CLAUDE.md` → Newsletter Template Design.

## Open

- [ ] **Deploy to VPS** (required before it affects the cron send): scp
      `scripts/templates/newsletter.html.j2` and `scripts/generate_newsletter.py`
      to `/opt/musemaniac/scripts/...`. Verify on the server with
      `grep -c mso-color-alt` (expect `0`) and `grep -c background-color`
      (expect `76`).
- [ ] **Watch the next Wednesday `0 7 * * 3` send** and the admin success email
      to confirm the live edition renders correctly.

## Done

- [x] Diagnosed Outlook dark-mode behaviour; confirmed `mso-color-alt` is a
      no-op and `[data-ogsc]` never reaches the Word engine.
- [x] Reworked `newsletter.html.j2` to pair background+text per cell; removed
      `mso-color-alt` from the template and `generate_newsletter.py`.
- [x] Verified with a real test send to an affected user (Outlook desktop, dark
      mode) — body and lavender News panel readable.
- [x] Merged to master; rewrote the CLAUDE.md Newsletter Template Design rule.
