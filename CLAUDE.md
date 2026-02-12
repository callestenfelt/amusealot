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

## Project
- Newsletter platform for museum tech
- Live at amusealot.com, sends real emails via Resend
- Baserow is the production database — treat writes with care
