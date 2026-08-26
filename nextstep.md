# Next steps

# Code review round 2: fix plan (August 2026)

A second multi-agent code review (2026-08-26, three parallel reviewers:
newsletter / site / pipeline) produced 58 findings (7 high, 21 medium,
30 low). **The durable, ordered fix plan lives in
`docs/review-2026-08-26-plan.md`** — seven phases, each its own feature
branch, with per-item checkboxes and a progress log. The full findings
report is `docs/review-2026-08-26.html`. Work from the plan file, not from
this section; this entry is just the pointer so the plan survives context
clears.

## Open

- [ ] **Watch the next `0 7 * * 3` send (2026-09-02)** — first cron run on
      the Phase 2 code (sent marker, --input-driven send step, marker-based
      success-email count, reminder send-then-mark).
- [ ] Phases 3–7 — see `docs/review-2026-08-26-plan.md`. Phase 3
      (`fix/dedup-hash`) starts with a migration decision on the content
      hash formula.

## Done

- [x] Phase 0 (2026-08-26): send verified clean (59/59, 0 errors) and
      Baserow score write-backs confirmed on all 52 new rows; subscriber
      app runs as a single process (no gunicorn), so no multi-worker
      signup loss. `FORM_SECRET` was confirmed missing, then **fixed the
      same day** (user ran the one-liner; verified: 64-hex value in `.env`,
      backup at `.env.bak-20260826`, service restarted with the secret in
      its environment, live form renders with bot-protection fields).
- [x] Phase 1 (2026-08-26): all 7 items done on `fix/silent-failures`
      (`1317844`) — loud failures for zero-sent/error sends, dry-run no
      longer saves ETags, partial Baserow fetches abort, LLM score
      validation/coercion, dropped-batch-item accounting, Groq 5xx retry.
      **Merged to master (`ef5c94b`) and deployed to the VPS the same day**
      (originals backed up to `/opt/musemaniac/scripts/.bak-20260826/`);
      verified compiling on the server. Master not yet pushed to origin.
- [x] Phase 2 (2026-08-26): implementation (`6608d96`) — generate dry-run
      mode, edition-row dedup, send marker + `--force`, unsubscribe hard
      errors, stale-date refusal, reminder timezone fix — plus all 10
      review follow-ups (`1c91f6d`): marker auto-removal on zero-sent runs,
      `--force` through `run_newsletter.sh`, dry runs rehearse this week's
      edition via `--input`, reminder send-then-PATCH with retry, edition
      lookup fall-through + filtered GET, single `apply` boolean,
      marker-based success-email count, tokenless rows skip+warn (exit 0).
      **Merged to master (`1c91f6d`) and deployed to the VPS the same day**
      (originals in `/opt/musemaniac/scripts/.bak-20260826-phase2/`;
      verified compiling on the server). Master pushed to origin
      2026-08-26 (`ecc1c8c`, covering Phases 1+2).

---

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

---

# Groq summary style: drop redundant audience-relevance framing (June 2026)

The Groq/Llama 3.3 summaries and spotlight kept tacking on sentences like
"this is highly relevant to museum professionals working with digital
humanities" — pure redundancy, since the whole newsletter is already for that
audience. Root cause: the prompts literally asked the model to explain "why it
matters for the museum community" / "what makes this article valuable", so it
obliged. **Fix:** removed those asks and added an explicit anti-editorializing
rule (with a negative example) to the prompts. Done on `fix/groq-summary-style`,
commit `b702f40`. **Merged to master, pushed to origin, and deployed to the VPS
on 2026-06-24.** Takes effect on the next `0 7 * * 3` send.

## Open

- [ ] **Eyeball the next Wednesday send** to confirm the live copy reads clean.
      Residual editorializing is ~15% of summaries and mild ("improves
      functionality"-style tails) — acceptable, but worth a glance.

## Done

- [x] `score_newsletter_content.py`: added a WRITING STYLE rule (with a BAD/GOOD
      example) to the shared system prompt; reworded the spotlight prompt to drop
      "why it matters / who can benefit".
- [x] `score_news.py`: reworded `generate_english_summary` to describe what the
      article reports instead of "what makes it valuable".
- [x] Verified by dry-run against the latest local data: the egregious pattern is
      gone (spotlight + most summaries purely descriptive); the leak rate fell
      from ~25% to ~15%, with the remainder mild rather than audience-relevance
      framing.
- [x] ff-merged to master (`b702f40`), pushed to origin, scp'd both scripts to
      `/opt/musemaniac/scripts/` (verified: new prompt text present, both
      `py_compile` clean).

---

# Groq model migration: llama-3.3 → gpt-oss-120b (August 2026)

The 2026-08-19 pipeline run failed (exit 1): every scoring batch got a 404 from
Groq and all 46 articles landed in tier 3, tripping the degraded-scoring guard.
Root cause: Groq decommissioned `llama-3.3-70b-versatile` on 2026-08-16 (they
had emailed a deprecation notice). **Fix:** switched both scorers to the
recommended replacement `openai/gpt-oss-120b`; since gpt-oss is a reasoning
model that spends completion tokens on reasoning before the answer, raised
`max_tokens` 2000 → 4000 and set `reasoning_effort: "low"`. Response parsing
needed no changes (final answer still arrives in `message.content`; JSON mode
supported). Done on `fix/groq-model-migration`, commit `ba53435`. **Merged to
master, pushed to origin, and deployed to the VPS on 2026-08-19**; pipeline
rerun manually the same day.

## Open

- [ ] **Confirm the 2026-08-19 manual rerun finished clean** (admin email /
      `logs/newsletter-2026-08-19.log`): no 404s, tier distribution not 46/46
      tier 3.
- [ ] **Watch the next `0 7 * * 3` send and eyeball tier calibration.**
      gpt-oss-120b may score stricter/looser than Llama 3.3 — if tier 1/2
      counts look unusual across an edition or two, recalibrate the scoring
      prompts (quality tweak, not a reliability issue).
- [ ] **Also re-check the summary style rule** (previous section's open item)
      under the new model — the anti-editorializing prompt was tuned against
      Llama 3.3.

## Done

- [x] Diagnosed the 404s: model decommissioned, not an outage — verified
      against Groq's live model list (`llama-3.3-70b-versatile` gone,
      `openai/gpt-oss-120b` is a production model, $0.15/M input).
- [x] `score_news.py` + `score_newsletter_content.py`: `GROQ_MODEL` →
      `openai/gpt-oss-120b`, `max_tokens` 4000, `reasoning_effort: "low"`.
- [x] Live-tested the new model with the production key from the VPS: HTTP 200,
      answer in `message.content`, reasoning in a separate field the scripts
      never read (27/38 completion tokens were reasoning — hence the bump).
- [x] Updated stale "Llama 3.3" mentions in `README.md`,
      `docs/NEWS_ARTICLES.md`, and the public `about.html`; left historical
      notes in `nextstep.md` / `NEWSLETTER_PLAN.md` as-is.
- [x] Pushed `fix/groq-model-migration`, ff-merged to master (`ba53435`),
      pushed master to origin, scp'd both scorers to
      `/opt/musemaniac/scripts/`, and reran the pipeline manually.
- [x] Confirmed the Wednesday cron needs no change — the model name lived only
      inside the two deployed scripts.

---

# News pipeline: Baserow registry + failed-run recovery (August 2026)

Post-mortem of the 2026-08-19 rerun found the news section mostly missing:
the failed morning run had collected 46 articles and persisted feed ETags,
so the rerun's conditional GETs skipped unchanged feeds and overwrote
`news_articles.json` with only 11 articles. Root cause was structural: the
pipeline ran `collect_news.py`/`score_news.py` **without `--apply`** (always
had), so articles/scores never reached Baserow — which also silently disabled
content-hash dedup every week (editions could repeat items from the previous
edition's 14-day window; only the ETag cache limited it). **Fix** (branch
`fix/news-baserow-pipeline`): pipeline now forwards `--apply` to collect+score;
`collect_news` captures the Baserow row id on insert (and saves JSON after the
insert) so `score_news` can write scores back; `score_news` recovers recent
tier-empty Baserow rows into its batch (plus a `--baserow-only` recovery flag),
so a failed-then-rerun cycle self-heals. The 46 missed articles need no manual
recovery: the 14-day window re-collects them next Wednesday and they become
candidates for the 2026-08-26 edition.

## Open

(none — closed 2026-08-26, see Done)

## Done

- [x] Verified the failure chain in logs: morning run "Saved 46 articles" +
      "DRY RUN MODE" on the collect step; rerun "Saved 11 articles" (ETag 304s).
- [x] `score_news.py`: fetch recent tier-empty Baserow rows and merge into the
      scoring batch; `--baserow-only` flag; deployed to VPS and live-tested
      (dry run found/scored the 1 genuinely unscored row).
- [x] `run_newsletter.sh`: forward `--apply` to `collect_news.py` and
      `score_news.py` (user-approved production Baserow writes).
- [x] `collect_news.py`: stamp `article["id"]` from the insert response; save
      Baserow before the JSON so ids reach `score_news` — without this every
      row stays tier-empty and recovery re-includes all articles weekly.
- [x] Decided against a manual recovery run now: inserting the missed articles
      into Baserow today would dedup them **out** of the 2026-08-26 edition.
- [x] **2026-08-26 send verified** (first run on the new `--apply` paths):
      59/59 sent, 0 errors, edition registered (Baserow row 44), 52 articles
      inserted and all 52 got relevance+tier written back (1/5/46 across
      tiers; ai_summary correctly absent — the only tier-1 was English).
