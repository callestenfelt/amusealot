# CLAUDE.md

## Safety Rules
- NEVER run send_newsletter.py or any script that sends real emails
- NEVER run scripts with --apply against production Baserow without explicit user approval
- NEVER commit straight to master — all work goes on a feature branch first
- Always run scripts in dry-run mode (no --apply) by default
- NEVER run git push without explicit user request (applies to both feature branches and master)

## Branching
- All new work goes on a feature branch off master
- Branch naming: feature/description, fix/description. Pick a name that covers the full scope of the branch — if you start with a narrow fix and end up bundling related commits (defensive fix + upstream hardening + docs), rename the branch (or open a new one) before merging so the name still describes the whole change.
- Merging to master: fast-forward only, after the feature branch is pushed and reviewed. "Merge to master" from the user authorizes a local ff-merge; a separate explicit instruction is needed before pushing master to origin.
- Deploys to the VPS happen via scp, separately from the merge
- At the start of a session, check and tell the user which branch is currently active

## Newsletter Template Design
- **Dark mode / "white-on-white" rule:** every text-bearing `<td>` must carry an explicit `background-color` matching its section, on the *same element* as its `color:`. This is the only thing that stops classic Word-engine Outlook for Windows desktop (and Windows Mail) from producing white-on-white — those clients run their own colour inversion and ignore `<style>` rules, so pairing background+text on one element makes the invert stay coherent. Section palette: body = `#fbfbfb`, lavender panels (What's new box, News+Feedback) = `#EDEBF5`, footer = `#080229` (light text). Never set a cell's `color:` without its sibling `background-color:`, and keep both in the same section's palette.
- **Do NOT use `mso-color-alt`** — it's a real legacy Office property but does NOT control Outlook dark-mode inversion (confirmed against Litmus / Email on Acid / hteumeuleu / Microsoft's own docs). The old template sprinkled it everywhere as a placebo; it was removed 2026-06-10. Don't reintroduce it.
- Outlook.com / new Outlook / Outlook mobile dark mode is handled separately by the `[data-ogsc]/[data-ogsb]` rules in the `<head>` `<style>` block (only those clients inject those attributes). If you add a new section background, add a matching `[data-ogsc] ... { background-color: ... !important }` override there too, or webmail dark mode will show light cells behind forced-white text.
- Test dark mode after design changes: generate with `--test`, send with `send_newsletter.py --test calle@callestenfelt.se --apply`, then view in **Outlook desktop on Windows with dark mode on** (the client the fix targets) — webmail/Apple Mail won't exercise the Word-engine path.

## Subscribe form bot protection
The `/subscribe` form has three layers against subscription-bombing (bots firing double-opt-in confirmation emails at third parties, which burns Resend quota and harms sender reputation):
1. **Honeypot** — hidden `company_website` field; if filled, the request is dropped silently (normal success page, no Baserow write, no email).
2. **Timing** — `form_ts` is an HMAC-signed render timestamp; submissions faster than 3s or older than 2h are dropped silently.
3. **Cloudflare Turnstile** — hard CAPTCHA gate, active only when `TURNSTILE_SITEKEY` + `TURNSTILE_SECRET` are set in `.env`. Privacy-friendly (no cookies), so it keeps the site's "no tracking, no cookies" promise. Fails closed (a Cloudflare outage briefly blocks signups rather than letting bots through).

All three layers are **live in production** (Turnstile enabled 2026-05-20; keys are in `/opt/musemaniac/.env`). To re-create or rotate the Turnstile widget/keys, follow `docs/turnstile-setup.md`.
- Cleanup: bot signups sit as `pending` rows in Baserow and never confirm. They're harmless (only `confirmed` rows are ever emailed), so cleanup is just tidiness. Two ways:
  - **Manual (Baserow UI):** filter the subscribers table to `status = pending`, sort by `subscribed_at`, select and delete. The filter guarantees confirmed subscribers can't be touched. Good for one-off, eyes-on cleanups (this is how the May 2026 bot spike was cleared).
  - **Script (for automation):** `python scripts/purge_pending_subscribers.py` lists stale pending rows (dry run, default >30 days; `--days N` to adjust); add `--apply` to delete. `--apply` against production needs explicit user approval per the safety rules. A 30-day cutoff intentionally keeps recent pending rows, so a fresh bot spike won't be purged until it ages out (or lower `--days`, accepting some risk to legit unconfirmed signups).

## Project
- Newsletter platform for museum tech
- Live at amusealot.com, sends real emails via Resend
- Baserow is the production database — treat writes with care

## Infrastructure
- VPS: `root@77.42.40.207`, SSH key: `~/.ssh/id_ed25519`
- Scripts live at `/opt/musemaniac/scripts/` on the VPS
- Deploy: run the PowerShell scp commands (no deploy.sh — no WSL on this machine)
- Cron: `0 7 * * 3` (every Wednesday 7AM) runs `cron_newsletter.sh` which calls `run_newsletter.sh --apply`
- Logs: two files per day, both useful:
  - `/opt/musemaniac/logs/newsletter_YYYY-MM-DD.log` (underscore) — written by `cron_newsletter.sh` via shell redirect; only the cron path writes here
  - `/opt/musemaniac/logs/newsletter-YYYY-MM-DD.log` (hyphen) — written by `run_newsletter.sh` via `tee -a`; both cron and manual runs write here
- Admin notifications: success/failure emails go to `calle@callestenfelt.se` via `notify_admin.py`
- `GITHUB_TOKEN` in `/opt/musemaniac/.env`: fine-grained PAT, "Public Repositories (read-only)" mode, expires annually. Rotate before expiry; a bad token now aborts the pipeline loudly (401 → SystemExit), but only after the cron has missed a send.

## Recovering from a missed send
1. Read the failure email or the latest log to identify the failure mode.
2. **Bad GitHub token** (admin email mentions "401 Bad credentials" or `Sources with activity: 0` in logs):
   - Generate a new fine-grained PAT (Public Repositories, read-only) at https://github.com/settings/personal-access-tokens/new
   - `ssh root@77.42.40.207 "nano /opt/musemaniac/.env"` and replace `GITHUB_TOKEN=...`
   - Verify: `ssh ... 'set -a; . /opt/musemaniac/.env; curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user'` — expect `200`
3. SSH in and run manually: `cd /opt/musemaniac && ./scripts/cron_newsletter.sh`
4. If the cron itself didn't run, check for `^M` line endings: `grep -a newsletter /var/log/syslog | tail -5`
   - Fix: `crontab -l | sed 's/\r//' | crontab -`

## Recovering a missing archive entry
If a newsletter was sent but not registered in Baserow (e.g. ran locally):
1. `python scripts/register_past_edition.py YYYY-MM-DD`
2. `scp scripts/editions/newsletter_YYYY-MM-DD.html root@77.42.40.207:/opt/musemaniac/scripts/editions/`
