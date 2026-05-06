# CLAUDE.md

## Safety Rules
- NEVER run send_newsletter.py or any script that sends real emails
- NEVER run scripts with --apply against production Baserow without explicit user approval
- NEVER commit or push to master directly — always use feature branches
- Always run scripts in dry-run mode (no --apply) by default
- NEVER run git push without explicit user request

## Branching
- All new work goes on a feature branch off master
- Branch naming: feature/description, fix/description
- User will merge to master and deploy manually
- At the start of a session, check and tell the user which branch is currently active

## Newsletter Template Design
- Whenever adding or changing inline `color:` values in newsletter.html.j2, always include `mso-color-alt` on the same declaration for Outlook Desktop dark mode compatibility
- Light text on dark elements: `color:#fbfbfb;mso-color-alt:#fbfbfb`
- Dark text on light elements: `color:#080229;mso-color-alt:#fbfbfb`
- Test dark mode after design changes: generate with `--test`, send with `send_newsletter.py --test calle@callestenfelt.se --apply`

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
