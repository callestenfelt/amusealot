# Code review fix plan — August 2026

Source: multi-agent code review of 2026-08-26 (three parallel reviewers:
newsletter, site, pipeline). Full findings report:
`docs/review-2026-08-26.html` (also published as a Claude artifact:
https://claude.ai/code/artifact/2b2a9262-5277-458d-b476-dfd5268f6eb6).
Totals: **7 high, 21 medium, 30 low**. Line numbers reference master at
`c76770d`.

This file is the durable plan. Work through the phases in order, tick items
off as they land, and record branch/commit per phase. `nextstep.md` only
carries a pointer here, so context clears don't lose the plan.

**Ground rules (from CLAUDE.md):** every phase is its own feature branch off
master; dry-run first; no `--apply` against production Baserow and no pushes
without explicit approval; deploys via scp are a separate step after merge.

---

## Phase 0 — Verify before touching code (no branch)

Do these first; two review findings are "verify config", and today
(2026-08-26) was the first send exercising the new `--apply` Baserow paths.

- [x] Confirm the 2026-08-26 send ran clean and Baserow write-backs worked —
      **verified 2026-08-26**: 59/59 sent, 0 errors; all 52 collected rows
      have relevance+tier in Baserow (tiers 1/5/46); ai_summary correctly
      absent (the only tier-1 was English). Edition registered as row 44.
- [ ] **[site H2]** Verify `FORM_SECRET` is set in `/opt/musemaniac/.env` —
      **verified MISSING 2026-08-26** (`subscriber_app.py:68` falls back to
      a random per-process secret; systemd unit does load the `.env` via
      `EnvironmentFile`). Fix still pending (needs a manual run — the
      assistant's attempt was permission-blocked):
      `ssh root@77.42.40.207 'cp /opt/musemaniac/.env /opt/musemaniac/.env.bak-20260826 && echo "FORM_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")" >> /opt/musemaniac/.env && systemctl restart musemaniac-subscriber.service && systemctl is-active musemaniac-subscriber.service'`
- [x] Check how many gunicorn workers the subscriber service runs —
      **checked 2026-08-26**: none; the unit runs plain
      `python3 subscriber_app.py` (single process), so restart-invalidation
      is the only exposure, not multi-worker signup loss.

## Phase 1 — Silent-failure cluster (branch: `fix/silent-failures`)

The highest-impact code fixes, all small, all in the pipeline/send path.
Theme: failures must abort loudly (non-zero exit → ERR trap → admin failure
email) instead of "succeeding" thin or empty.

- [x] **[newsletter H1]** `send_newsletter.py`: exit non-zero when
      `sent == 0` (and consider when `errors > 0`), so a revoked Resend key
      triggers the failure email instead of a success email saying
      "0 email(s) sent". Same fix in `send_reminders.py:207`.
- [x] **[pipeline H2]** `collect_news.py:437`: gate `save_etag_cache()` on
      `args.apply`. A dry-run currently poisons the next real run into
      skipping feeds via 304 — this exact chain caused the Aug 19 thin
      edition (see nextstep.md post-mortem), so it's production-proven.
- [x] **[pipeline H3]** `collect_news.py:163` `get_existing_hashes()`:
      abort (SystemExit) on mid-pagination errors instead of returning a
      partial set that silently disables dedup and mass-re-inserts articles.
- [x] **[pipeline M1]** `collect_news.py:104` `get_active_sources()`: same
      fix — abort instead of silently returning a partial source list. Also
      harden the two row-parsing spots that raise on null fields
      (lines ~125, ~131).
- [x] **[pipeline M3]** Scoring scripts: count LLM-dropped batch items
      (model returns fewer indices than the batch) as `scoring_error`, not
      `unscored`, so the ≥50% abort guard actually sees them; in
      `score_news.py` make sure unmatched articles still reach the output
      instead of vanishing. Ignore duplicate indices from the model.
- [x] **[pipeline M8]** `score_news.py:290`: validate LLM output before the
      Baserow PATCH — `tier` ∈ {1,2,3} as int, `relevance` ∈ 1–10 as int;
      coerce `"1"` → 1 so the English-summary branch doesn't silently skip.
- [x] **[pipeline M9]** Both scorers: retry Groq 5xx (like 429/timeout),
      not just fail the batch.

Verify: `py_compile` all touched scripts; dry-run the pipeline locally;
simulate a send with an invalid Resend key and confirm exit 1.

## Phase 2 — Re-run safety & dry-run honesty (branch: `fix/rerun-safety`)

Theme: the documented recovery playbook is "re-run it" — make re-running
actually safe, and make dry runs actually dry.

- [x] **[newsletter H2]** `run_newsletter.sh:92` + `generate_newsletter.py`:
      give generate a real dry-run mode and forward `--apply` like the other
      steps. Without `--apply`: no edition row registered, no
      `latest_news.json` overwrite, no dated file the public archive serves.
- [x] **[newsletter M1]** `generate_newsletter.py:280` +
      `register_past_edition.py:66`: check for an existing edition row for
      that date before POSTing (update or skip instead of duplicating).
- [x] **[newsletter M2]** `send_newsletter.py`: add send idempotency — an
      "edition sent" marker checked before sending (per-subscriber column
      like `reminder_sent_at`, or minimally a per-edition sent flag +
      refusal to re-send without `--force`), so a mid-send crash + re-run
      doesn't double-send.
- [x] **[newsletter M3]** `send_newsletter.py:163,204`: make a missing
      `%%UNSUBSCRIBE_URL%%` placeholder and an empty `unsubscribe_token`
      hard errors under `--apply` (skip that recipient / abort), not
      warnings. Compliance, not cosmetics.
- [x] **[newsletter L5]** `send_newsletter.py:44`: refuse to `--apply` an
      edition whose date isn't today unless `--force` — stops a manual run
      from silently re-sending last week's file.
- [x] **[newsletter M4+M5]** `send_reminders.py`: fix timezone parsing
      (`fromisoformat(...).astimezone(utc)` with naive fallback; handle `Z`
      suffix) and mark `reminder_sent_at` *before* sending (or retry the
      PATCH) so a Baserow blip can't cause duplicate "one-time" reminders.
- [x] **[pipeline/newsletter L1]** `run_newsletter.sh:118`: scope the
      sent-count grep to the current run (e.g. grep from a run-start marker)
      so same-day re-runs don't inflate the admin email.

Verify: full local dry-run leaves no trace (no Baserow rows, no
`latest_news.json` change, no editions file); re-run scenario on test data.

### Phase 2 review follow-ups (automated /code-review of `6608d96`, 2026-08-26)

The review confirmed the mechanics but found 10 issues, mostly interaction
effects with the wider pipeline. Fix on this branch before merging:

All fixed 2026-08-26 (same branch, commit after `6608d96`); every path
verified with monkeypatched harnesses (marker removal/retention/--force,
send-then-mark retry, lookup fall-through, filtered GET, shell arg matrix).

- [x] **(1)** Recovery path fixed: `send_newsletter.py` now removes the
      `.sent` marker when `sent == 0` (nothing went out → re-run is safe);
      `run_newsletter.sh` accepts `--force` and forwards it to the send step
      only; CLAUDE.md playbook step 3 documents the marker semantics and the
      `--apply --force` recovery run.
- [x] **(2)** `run_newsletter.sh` computes the edition file it generates
      (dated under `editions/` with `--apply`, `newsletter_email_test.html`
      otherwise) and passes it to step 7 via `--input` — dry runs now
      rehearse this week's edition.
- [x] **(3)** `send_reminders.py` reverted to send-then-PATCH;
      `update_reminder_sent` retries 3× with backoff and returns False on
      exhaustion, which counts as a loud error (exit 1) naming the row id.
- [x] **(6)** `register_edition` wraps the lookup separately; a lookup
      failure warns and falls through to POST.
- [x] **(7)** Success email reads `sent=N` from the `.sent` marker's
      `send finished` line (missing/unfinished marker → 0, but the ERR trap
      fires first in those cases). `RUN_START_MARKER` awk counting removed.
- [x] **(8)** Both edition lookups are now one
      `filter__edition_date__equal` GET (same approach in
      `generate_newsletter.py` and `register_past_edition.py`).
- [x] **(9)** Collapsed to one `apply = args.apply and not args.test`
      boolean gating dated files, `latest_news.json`, and registration.
- [x] **(10)** Gone with the (3) restructure — no PATCH-before-send path,
      one rate-limit sleep per iteration.

User decisions (made 2026-08-26):

- [x] **(4)** **Skip + warn, exit 0.** Tokenless rows are skipped (never
      emailed without an unsubscribe link) and counted separately as
      `skipped_no_token` with a loud per-row warning naming the Baserow row;
      they no longer fail the run. Real send errors still exit 1.
- [x] **(5)** **Local marker accepted.** Cron only runs on the VPS, so
      split-brain requires a deliberate local `--apply` send; with (1),
      zero-sent failures self-recover and only a genuine mid-send crash
      needs a human `--force` call. Revisit (per-subscriber Baserow column)
      only if a mid-send crash actually happens.

## Phase 3 — Pipeline dedup identity (branch: `fix/dedup-hash`)

Isolated on its own branch because it changes data identity and needs a
migration story — don't bundle it with quick fixes.

- [ ] **[pipeline H1]** `collect_news.py:147,257`: drop `published_date`
      from the content hash (hash on URL, or title+URL). Date stays in the
      cutoff filter only.
- [ ] **Migration caution:** existing Baserow rows carry old-formula hashes,
      so the first run after the change would see recent articles as new
      and re-insert them. Mitigate: during a transition window compare
      against *both* hash formulas (compute old + new for each candidate),
      or backfill new hashes for rows inside the 14-day window before
      deploying. Decide + document the choice here.
- [ ] **[pipeline L6]** While in the file: add newly-inserted hashes to the
      in-run set (same-run syndicated duplicates), move `import re` to
      module top.
- [ ] **[pipeline M6]** `collect_github_activity.py`: add cross-edition
      dedup for GitHub events (persist seen event URLs, or shrink the
      8-day window overlap) so the ~1-day lookback overlap stops producing
      a guaranteed repeat slot every week.

## Phase 4 — Site security & flows (branch: `fix/site-hardening`)

- [ ] **[site H1]** Rate limiting behind Caddy: add
      `ProxyFix(app.wsgi_app, x_for=1)` and configure Caddy to set
      `X-Forwarded-For` from the client (verify Caddy strips any
      client-supplied value — otherwise the limiter becomes spoofable).
      Needs a VPS Caddy config change alongside the code deploy.
- [ ] **[site M2]** `/unsubscribe`: GET renders a confirmation page with a
      POST button; the state change happens only on POST. Keep the
      tokenized POST path working for RFC 8058 one-click. (Stops SafeLinks/
      Mimecast prefetch from silently unsubscribing real readers.)
- [ ] **[site M3]** `/feedback`: add the honeypot + `form_ts` layers (reuse
      the subscribe-form pattern) — it currently fires a Resend email per
      unprotected POST.
- [ ] **[site M5]** Subscribe double-submit race: after create, re-query by
      email and delete the loser row (or add a Baserow unique constraint if
      available) so duplicate subscriber rows can't accumulate.
- [ ] **[site M1]** Privacy policy: name Cloudflare as a processor for the
      Turnstile check; drop the optional `remoteip` field from siteverify
      (`subscriber_app.py:130`) to keep the no-IP claim true.
- [ ] **[site M4]** (optional, decide) Bind `form_ts` to client IP or make
      it single-use — currently one 3s wait buys 2h of replays; Turnstile
      is the real gate, so this may be accepted as-is. Record the decision.
- [ ] **[site lows, cheap batch]** `basename()` on edition `file_name`
      (L3); validate `http(s)://` scheme on article URLs when writing
      `latest_news.json` (L5 — also covers newsletter L8 at the source);
      escape/validate dates in sitemap (L4); `--days >= 1` guard in
      `purge_pending_subscribers.py` (L8); paginate + `compare_digest` in
      `find_row_by_token` (L1); real 404 page instead of soft-404 landing
      (L6).

Verify: subscribe/confirm/unsubscribe flows end-to-end against a test row;
rate limit observed per-client after Caddy change; one-click unsubscribe
POST still works from a real mail client.

## Phase 5 — Email templates & dark mode (branch: `fix/email-dark-mode`)

Needs the full test loop from CLAUDE.md (generate `--test`, send to
calle@callestenfelt.se, view in Outlook desktop on Windows, dark mode).

- [ ] **[newsletter M6]** `reminder_email.html`: pair `background-color` +
      `color` on the same element for every text-bearing cell, especially
      the CTA (`<td>` bg / `<a>` color split = invisible confirm button
      risk); add `p` to the `[data-ogsc]` override set; fix the explicit
      `color` on the closing `<p>`.
- [ ] **[newsletter L3]** `newsletter.html.j2`: bring the span-based
      sections (stats bar, most-active, tool watch, footer) onto the
      same-element pairing rule — footer (light text on `#080229`) first.
- [ ] **[newsletter L4]** Add `[data-ogsc]` border override for the rating
      boxes; restructure the `<a>`-wrapped rating table so Word-engine
      Outlook gets a clickable target.
- [ ] **[newsletter M7]** `generate_newsletter.py:388`: make the >102KB
      check fail the pipeline (or auto-tighten `section_cap`) instead of
      warn-only — Gmail clips the footer/unsubscribe first.
- [ ] **[newsletter L6]** Guard `repo.split('/')` for slash-less repo
      names.
- [ ] **[newsletter L2]** (optional) Make the `whats_new` link rewrite less
      brittle; skip the "N sources" line when stats are unavailable.

Verify: test send viewed in Outlook desktop dark mode per CLAUDE.md.

## Phase 6 — Pipeline coverage & robustness (branch: `fix/pipeline-coverage`)

- [ ] **[pipeline M4]** GitHub 403 handling: honor `Retry-After`
      (secondary rate limits); treat a no-header 403 as fatal-ish (log +
      abort or clearly surface) instead of silent empty results.
- [ ] **[pipeline M5]** Paginate org event feeds (or raise `per_page`) and
      `collect_new_repos` beyond 10; filter bot events before windowing
      decisions.
- [ ] **[pipeline M2]** `score_newsletter_content.py`: batch new-repo and
      release scoring like pushes (`PUSH_BATCH_SIZE`-style) so a busy week
      can't overflow `max_tokens` and tier-3 a whole category.
- [ ] **[pipeline M7]** Prompt-injection hardening: delimit untrusted
      content (RSS text, READMEs, release bodies) in prompts; cap summary
      length from the model. (Type validation already landed in Phase 1.)
- [ ] **[pipeline L7]** `score_news.py` recovery: server-side Baserow
      filters instead of fetching the whole table; stop re-fetching
      permanently-unscored rows older than the window.
- [ ] **[pipeline L8]** Write `ai_title` to Baserow alongside `ai_summary`.

## Phase 7 — Housekeeping batch (branch: `chore/review-lows`)

Low-risk cleanups; fine to trickle in or do as one sweep.

- [ ] Timeouts on remaining HTTP calls: `register_past_edition.py:68`,
      `enrich_github.py` (Wikidata + Baserow), `search_github_museums.py`,
      `add_github_museums.py`.
- [ ] `run_newsletter.sh`: add `set -E` so the ERR trap survives future
      function refactors; make the failure-email tail not race the `tee`.
- [ ] Config dedup: single source for `TABLE_ID`/field-ID maps shared by
      `collect_news`/`score_news` and the GitHub scripts; kill dead
      `TECH_FIELDS` and the hardcoded `field_7222`.
- [ ] Log retention: actually prune `/opt/musemaniac/logs/` (subscriber
      emails = PII accumulating indefinitely); align or remove the
      "30 days" comment. Consider not logging full email addresses.
- [ ] `enrich_github_activity.py`: replace the `len == 300` truncation
      heuristic with an explicit truncation flag; rename the misleading
      `remaining` headers variable.
- [ ] `get_field_ids.py` padded-ID printout; `search_github_museums.py`
      `KNOWN_GITHUB` drift note.
- [ ] Copy `cron_newsletter.sh` from the VPS into the repo so the outermost
      cron wrapper is version-controlled and reviewable.

---

## Explicitly accepted / not planned (for the record)

- **Timing oracles on the subscribe flow (site L2)** — honeypot drops
  return faster than real submissions; enumeration via timing. Low value
  to attackers, non-trivial to fully close. Revisit only if bot behavior
  suggests exploitation.
- **`whats_new.txt` as an HTML injection point (newsletter L2)** — it's an
  author-controlled file; the `| safe` is intentional. Documented, not
  fixed.
- **Archive route caching (site L10)** — nice-to-have; add only if the
  archive gets slow or Baserow flakes on it.

## Progress log

| Date | Phase | Branch | Commits | Deployed |
|------|-------|--------|---------|----------|
| 2026-08-26 | 0 (verify) | — | — | FORM_SECRET fix pending manual run |
| 2026-08-26 | 1 | fix/silent-failures | 1317844 | 2026-08-26 (5 scripts, verified on VPS) |
| 2026-08-26 | 2 | fix/rerun-safety | 6608d96 + 1c91f6d (merged to master 2026-08-26) | not yet (scp deploy pending) |
