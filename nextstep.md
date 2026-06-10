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
- [x] **Housekeeping:** added `scripts/latest_news.json` to `.gitignore`
      (generated runtime artifact; no longer clutters `git status`).

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
- [x] Deployed to VPS (scp'd `newsletter.html.j2` + `generate_newsletter.py`;
      backed up the old template to `.bak`; verified on the server —
      `mso-color-alt` count `0`, `background-color` count `76`).

---

# Code review & hardening (June 2026)

A multi-agent code review (every high-impact finding verified against source)
surfaced a batch of bugs and improvements. Fixes are done on the
`fix/review-hardening` branch — commits `0df9de7` (P0+P1) and `9477406` (P2).
**Merged to master and deployed to the VPS on 2026-06-10** (master at `9c1c51d`,
pushed to origin).

## Open

- [ ] **Watch the next `0 7 * * 3` send** to exercise the new degraded-scoring
      guard: a Groq outage now aborts the run (non-zero exit → admin failure
      email) instead of silently shipping a near-empty edition.

## Done

- [x] **P0** — `send_newsletter.py --test` without `--apply` now dry-runs instead
      of sending a real email; enabled Jinja autoescaping for the email template
      (its `.j2` name had silently disabled `select_autoescape(["html"])`, so RSS
      titles / AI summaries rendered raw).
- [x] **P1** — added request timeouts to every Baserow/Resend/GitHub call in the
      web app + pipeline; both AI scorers now exit non-zero when a large fraction
      of items fail to score; guarded the Baserow writes in `/subscribe`,
      `/confirm`, `/unsubscribe` so a Baserow blip yields a friendly page, not a 500.
- [x] **P2** — deduped GitHub event extraction (`_extract_event`); removed dead
      `parse_rss_date` / `find_row_by_field`; rate-limited `/confirm` +
      `/unsubscribe`; added input length caps + `MAX_CONTENT_LENGTH`; enricher
      aborts on a GitHub 401; escaped the admin notification; dated-edition glob
      guard; `run_newsletter.sh` forwards only `--apply` to the send scripts.
- [x] Verified: all changed files byte-compile; autoescape proven end-to-end (a
      `<canvas>` title escapes to `&lt;canvas&gt;`); the `_extract_event` refactor
      is unit-checked; `bash -n run_newsletter.sh` clean.
- [x] Pushed `fix/review-hardening`, ff-merged to master, pushed master to origin
      (`9c1c51d`), and deployed all 11 changed scripts to
      `/opt/musemaniac/scripts/` — restarted `musemaniac-subscriber.service`
      (active; live form still shows honeypot + timing token + Turnstile).
