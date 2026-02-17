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
