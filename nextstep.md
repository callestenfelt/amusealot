# Next steps

# Redesign 2026-08-27 — site + newsletter

Both halves of the "Placard / Rammetto One" redesign (design canvas:
https://claude.ai/code/artifact/23f1a203-1074-4bfd-a08d-888dad3489bf).

**Site** (`feature/site-redesign`): new `base.html` design system (real
dark mode, desktop nav + mobile drawer, perforation rules, ticket-punch
link underlines), all 15 web templates restyled, self-hosted fonts.

**Email** (`feature/email-redesign`): numbered small-caps section headers
replace the emoji, warm palette (body/footer `#F7F5F1`, panels
`#FAF9F6`), weekly-first numbers with the corpus size as a footnote,
compact one-row rating, light ruled footer, and the
confirmation/reminder CTA is now an OUTLINED ink-on-paper button (not a
dark filled block). CLAUDE.md's palette line is updated to match.

**DEPLOY NOTE — new directory:** the site half adds
`scripts/static/fonts/` with four `.woff2` files that `base.html`
preloads. The deploy MUST create `/opt/musemaniac/scripts/static/fonts/`
on the VPS and scp all four files — otherwise every page 404s its fonts
and silently falls back to Arial.

# Code review round 2: fix plan (August 2026)

A second multi-agent code review (2026-08-26, three parallel reviewers:
newsletter / site / pipeline) produced 58 findings (7 high, 21 medium,
30 low). **The durable, ordered fix plan lives in
`docs/review-2026-08-26-plan.md`** — seven phases, each its own feature
branch, with per-item checkboxes and a progress log. The full findings
report is `docs/review-2026-08-26.html`. Work from the plan file, not from
this section; this entry is just the pointer so the plan survives context
clears.

**The August 2026 review fix plan is COMPLETE** — all seven phases done,
merged, deployed, and pushed to origin as of 2026-08-27. Only the four
manual items below remain, each with its full step-by-step guide.

## Open — step-by-step guide for the remaining manual work

### 1. Create the `ai_title` column — DONE 2026-08-27

- [x] Created in the Baserow UI (field 7299, long_text) and verified:
      `score_news.py --baserow-only` resolves it by name with no
      "no ai_title column" note. English titles start persisting with the
      2026-09-02 send.
- [ ] After the next send, spot-check a non-English tier 1/2 article row:
      it should have an English title in `ai_title` next to `ai_summary`.

### 2. Phase 5 Outlook dark-mode eyeball test (needs the Windows machine)

- [ ] Generate and send the test edition from the VPS:
  ```
  ssh root@77.42.40.207
  cd /opt/musemaniac/scripts && set -a; . ../.env; set +a
  python3 generate_newsletter.py --test
  python3 send_newsletter.py --input newsletter_email_test.html --test calle@callestenfelt.se --apply
  ```
  `--input` matters — without it, send picks the latest *dated* edition,
  not the test file.
- [ ] View in **Outlook desktop on Windows with dark mode on** (webmail /
      Apple Mail won't exercise the Word-engine path). Checklist:
      - No white-on-white or dark-on-dark anywhere — especially the stats
        bar numbers, most-active list, tool watch, and the footer (light
        text on dark).
      - Rating boxes: borders visible AND clicking a row opens the
        feedback page (was broken in Word-engine Outlook before).
      - "What's new" box links readable on the lavender panel (if shown).
- [ ] Optional: subscribe on amusealot.com with a test address and view
      the **confirmation email** in the same Outlook — the "Confirm
      Subscription" button must be clearly visible and clickable.
      Expectation depends on what is deployed: BEFORE the email redesign
      deploys it is a dark button with light text; AFTER, it is an
      OUTLINED ink-on-paper button whose text is underlined (the
      underline is deliberate insurance — Word-engine dark mode may
      swallow the border, and the underlined bold uppercase text must
      still read as the action). Confirm + unsubscribe afterwards (or
      delete the pending row in Baserow) to clean up.

### 3. Watch the Wednesday send (2026-09-02, 07:00)

First cron run on the whole Phase 2–7 stack (sent marker, URL-only dedup
+ seen-events cache, http(s) guards, 102KB auto-tighten, paginated
feeds/403 taxonomy/batched scoring, shared client + masked logs).

- [ ] **Wednesday morning:** expect exactly one admin email — a *success*
      email ("Newsletter sent … N email(s) sent"). On a *failure* email
      (or two — that itself would be a bug worth reporting), follow
      CLAUDE.md "Recovering from a missed send": read the log tail, fix
      the cause, then
      `ssh root@77.42.40.207 "cd /opt/musemaniac && ./scripts/cron_newsletter.sh"`.
- [ ] **Eyeball the edition** (inbox or amusealot.com/archive):
      - No repeated GitHub events from the 2026-08-26 edition (dedup +
        seen-events cache should remove them).
      - Possibly *more* GitHub events than usual — pagination now sees
        past 30 events per feed.
      - Non-English news items with English titles, if item 1 was done
        before Wednesday.
- [ ] **Log spot-check** (optional):
      `ssh root@77.42.40.207 "tail -50 /opt/musemaniac/logs/newsletter-2026-09-02.log"`
      — send lines should show masked addresses (`ca***@domain` + row
      id), and logs older than 30 days start disappearing from
      `/opt/musemaniac/logs/` over the coming weeks.

### 4. Real-client unsubscribe check (low priority, when occasion arises)

- [ ] From a real newsletter in a real mail client: click **Unsubscribe**
      in the footer → expect a confirmation page with a button (not an
      instant unsubscribe) → the button completes it.
- [ ] Also confirm the mail client's native unsubscribe affordance
      (Gmail's one-click, RFC 8058 POST) still works.
- [ ] Re-subscribe afterwards if the test used your real address.

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
      verified compiling on the server. Pushed to origin with Phase 2.
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
- [x] Phase 3 (2026-08-26): dedup identity on `fix/dedup-hash`
      (`11741c9` + follow-ups `a905dfa` after a 10-finding /code-review) —
      URL-only content hash with URL-derived hashes from stored Baserow
      rows as the migration (no Baserow writes, legacy formula deleted);
      GitHub cross-edition dedup via a seen-URLs cache with a two-phase
      pending/commit-at-send-success design; shared `json_cache.py` with
      atomic writes. **Merged, deployed (originals in
      `.bak-20260826-phase3/`), and pushed to origin the same day.**
- [x] Phase 4 (2026-08-26): site hardening on `fix/site-hardening`
      (`d61ed94` + follow-ups `04a0935` after a 10-finding /code-review
      recovered from a stalled review agent) — ProxyFix + loopback bind so
      rate limits see real client IPs (no Caddy change needed, v2.10
      defaults strip client XFF); unsubscribe GET→confirm-page/POST split
      (RFC 8058 one-click intact); feedback honeypot+timing via shared
      helper/partial; double-submit dedup with delete-404 tolerance;
      Cloudflare named in privacy + no remoteip to Turnstile; byte-wise
      compare_digest; http(s)-only URL guard at collect + render; real 404
      page; purge `--days>=1`; paginated token lookup. **Merged, deployed
      (4 scripts + 6 templates, originals in `.bak-20260826-phase4/`,
      service restarted on 127.0.0.1, live smoke tests green), and pushed
      to origin the same day.**
- [x] Phase 5 (2026-08-26): email dark mode on `fix/email-dark-mode`
      (`979bdce` + follow-ups `b804a20` after a 10-finding /code-review) —
      same-element bg+color pairing across all three email templates
      (newsletter, reminder, confirmation) with corrected `[data-ogsc]`
      pinning in both directions; rating rows made clickable in Word-engine
      Outlook (anchor inside the cell, padding on the td); 102KB Gmail gate
      auto-tightens `section_cap` 4→1 then fails loudly, with tool watch +
      individual creators now cappable ("see all" links) and
      `latest_news.json` on a fixed cap; `split('/')[-1]` guards; regex
      whats_new link styling with per-token stat gating. **Merged and
      deployed same day (generate_newsletter.py + 3 templates, originals in
      `.bak-20260826-phase5/`, compile + checksums + real-data dry-run
      verified on VPS) and pushed to origin the same day. Outlook dark-mode
      eyeball still pending.**
- [x] Phase 6 (2026-08-26/27): pipeline coverage on `fix/pipeline-coverage`
      (`6aa2f88` + follow-ups `10297da` after a 10-finding /code-review +
      3.10 hotfix `cffaa92`) — GitHub 403/429 taxonomy with Retry-After,
      15-min wait cap, and a distinct-owner systemic-abort threshold;
      date-stopped pagination for event feeds and new repos; all scoring in
      batches of 5; prompt-injection markers + sanitizer + output caps via
      new shared `llm_shared.py` (also absorbs the duplicated
      groq_request); server-side recovery filters (tier empty AND
      date-window-or-empty) with loud 400 abort; ai_title resolved by name
      and written in its own PATCH. **Merged, deployed 2026-08-27
      (3 scripts + llm_shared.py, originals in `.bak-20260827-phase6/`,
      compile on VPS Python 3.10 + read-only smoke verified), and pushed.
      ai_title column still to be created in the Baserow UI.**
- [x] Phase 7 (2026-08-27): housekeeping on `fix/review-lows` (`d83480a` +
      follow-ups `02d22d0` after a 10-finding /code-review, incl. one
      reproduced set -E/SENT_COUNT bug) — remaining HTTP timeouts;
      run_newsletter.sh `set -E` + tee-race fix + real 30-day log pruning;
      new `baserow_config.py` (single-source table/field ids, 7 importers)
      and `baserow_client.py` (shared row CRUD — subscriber_app, purge,
      send scripts, collectors all ported; closes Phase 4's deferred
      dedup); email masking (`ca***@domain` + row id) in pipeline logs;
      explicit release-truncation flag; cron_newsletter.sh in the repo,
      restructured to log .env failures instead of dying silently.
      **Merged, deployed 2026-08-27 (18 files checksum-verified, originals
      in `.bak-20260827-phase7/`, service restarted, live routes 200,
      dry-runs clean), and pushed. This completes the review plan.**

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
