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
- [x] **[site H2]** Verify `FORM_SECRET` is set in `/opt/musemaniac/.env` —
      was **missing** (`subscriber_app.py:68` fell back to a random
      per-process secret); **fixed 2026-08-26** by the user running the
      backup+append+restart one-liner. Verified: one 64-hex `FORM_SECRET`
      line in `.env`, backup at `.env.bak-20260826`, service restarted at
      the same timestamp with the secret present in the running process's
      environment, and the live landing page renders the form with
      `form_ts` + honeypot.
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

Done 2026-08-26 (two rounds: implementation, then an automated /code-review
at high effort found 10 issues — all resolved, see follow-ups below).
Decisions (user-approved): **URL-only hash** (an article is its URL; titles
and dates are the churn sources) and **persisted seen-URLs cache** for GitHub
(over shrinking the 8-day window).

- [x] **[pipeline H1]** `compute_content_hash(url)` hashes the URL alone;
      date stays in the cutoff filter only.
- [x] **Migration** — the user picked dual-formula compare, but the review
      (finding 5) showed it misses its own target case: the legacy hash is
      recomputed from the feed's *current* title/date, so churned articles
      (the reason for the change) wouldn't match. Superseded by a strictly
      better approach in the same no-Baserow-writes spirit:
      `get_existing_hashes` now also adds `sha256(stored URL)` for every
      Baserow row, making dedup formula-independent forever. The legacy
      formula is deleted entirely.
- [x] **[pipeline L6]** Accepted hashes join the in-run set immediately
      (same-run syndicated duplicates filtered); `import re` at module top.
- [x] **[pipeline M6]** Cross-edition dedup via a seen-URLs cache
      (`github_seen_events.json`, pruned at 30 days). Two-phase after
      review finding 1: collection (`--apply`) writes candidates to a
      *pending* file only; `run_newsletter.sh` commits it to the cache via
      `--commit-seen` right after the send step succeeds — so a failed run
      burns nothing and the documented recovery re-run still ships a full
      GitHub section. Both files gitignored.

### Phase 3 review follow-ups (automated /code-review of `11741c9`, high, 2026-08-26)

10 findings, all resolved in the follow-up commit:

- [x] **(1)** Cache persisted at step 1 broke failure recovery → two-phase
      pending/commit design (commit only after send success).
- [x] **(2)** Collected-but-unpublished events burned → *partially
      accepted*: the pending file still records all collected URLs, so an
      event cut by a transient scoring error inside the ~1-day overlap
      slice stays suppressed. Rare (one-day slice × scoring-failure rate)
      and bounded by the 8-day window; revisit with a published-URL-derived
      cache only if it visibly bites.
- [x] **(3)** Persist read post-collapse list while filter read
      pre-collapse → pending is built from `all_activity` (pre-collapse),
      so a superseded push can't resurface and win next week.
- [x] **(4)** Non-unique cache keys → `is_cacheable_url()` excludes empty
      URLs and the per-branch `/commits/{branch}` fallback from both the
      filter and the pending file.
- [x] **(5)** Legacy compare missed churned articles → superseded by
      URL-derived hashes from Baserow (see Migration above).
- [x] **(6)** Legacy branch skipped the in-run set add → moot; with
      URL-derived hashes the matching entry *is* `sha256(url)`, so the
      invariant holds structurally.
- [x] **(7)** Bare `--apply` with the `--days 30` default poisoning the
      cache → defused by the pending design: bare `--apply` only writes
      the pending file, which the next pipeline run's step 1 overwrites
      before anything commits.
- [x] **(8)** Non-atomic cache writes → new shared `json_cache.py` writes
      via temp file + `os.replace`; the news ETag cache now uses it too.
- [x] **(9)** Transient `legacy_hash` key contract → gone with the legacy
      formula.
- [x] **(10)** Duplicated cache-I/O idiom → shared `json_cache.py` helper
      used by both scripts (deploy it alongside).

## Phase 4 — Site security & flows (branch: `fix/site-hardening`)

Done 2026-08-26. All items verified with a 19-check Flask test-client
harness (mocked Baserow).

- [x] **[site H1]** `ProxyFix(app.wsgi_app, x_for=1)` added. **No Caddy
      config change needed**: the VPS runs Caddy v2.10.2, and since v2.5
      `reverse_proxy` drops any client-supplied `X-Forwarded-For` unless
      `trusted_proxies` is configured (it isn't), replacing it with the
      real client IP — so the single trusted hop is not spoofable.
- [x] **[site M2]** `/unsubscribe` GET now renders a confirmation page
      (`unsubscribe_confirm.html`, new) whose button POSTs back; the state
      change happens only on POST. RFC 8058 one-click (query-token POST)
      verified still working. Already-unsubscribed GETs show the success
      page directly (idempotent, no state to protect).
- [x] **[site M3]** `/feedback` got the honeypot + `form_ts` layers (same
      markup/logic as the subscribe form); both drop silently with the
      normal success page.
- [x] **[site M5]** After creating a subscriber row, the app re-queries by
      email and deletes all but the lowest-id row; a losing request skips
      sending its (dead) confirmation email. Both racers run the same
      deterministic cleanup.
- [x] **[site M1]** Privacy policy names Cloudflare (Turnstile) as a
      processor with an honest description of the flow; the optional
      `remoteip` field removed from siteverify so the no-IP claim is true.
- [x] **[site M4]** **Decision: accepted as-is** — `form_ts` stays
      IP-unbound and multi-use. Turnstile is the real gate; binding to IP
      would break legitimate mobile/NAT users and add statefulness for
      marginal gain against a layer that's only defense-in-depth.
- [x] **[site lows]** All six: `basename()` on edition `file_name` (L3);
      http(s)-scheme filter on `latest_news.json` URLs (L5, covers
      newsletter L8 at the source); sitemap only emits `DATE_RE`-valid
      edition dates (L4); `--days >= 1` guard in purge script (L8);
      `baserow_list_rows` paginates + `find_row_by_token` uses
      `hmac.compare_digest` and tolerates null fields (L1); real 404 page
      (`not_found.html`, new) via catch-all + `errorhandler(404)` (L6).

### Phase 4 review follow-ups (automated /code-review of `d61ed94`, high, 2026-08-26)

The review agent stalled before final synthesis; its 8 finder reports and
verifier verdicts were recovered from the transcript and every finding
resolved in the follow-up commit:

- [x] **Double-submit delete-404**: when both racers delete the same loser
      row, the second delete's 404 jumped past the "did my row lose" check
      and the loser still emailed its dead token. Restructured: listing and
      each delete tolerate failure individually; the survivor check always
      runs.
- [x] **`compare_digest` TypeError**: the str overload raises on non-ASCII
      (e.g. `?token=påhitt` → 500 instead of 404). Now compares UTF-8
      bytes.
- [x] **Feedback timing swallowed legit submissions**: a prefilled-rating
      one-click submit (<3s) or a quick retry after the 500 re-render was
      silently dropped with a fake success page. Feedback now uses
      `min_age=1` and the error re-render carries the *submitted* form_ts
      (already age-valid) instead of minting a fresh one. Subscribe keeps
      its 3s gate.
- [x] **ProxyFix spoofable via direct port access**: the app bound
      `0.0.0.0:5680`, so anything reaching the port directly could forge
      X-Forwarded-For (only ufw's default-deny stood in the way). Now binds
      `127.0.0.1` — Caddy proxies via localhost, nothing else can connect.
- [x] **URL filter gap**: the http(s) filter only guarded
      `latest_news.json` while the rendered newsletter still embedded raw
      RSS URLs. Moved to the real sources: `collect_news.py` refuses
      non-http(s) URLs at extraction, and `prepare_news_articles` filters
      as defense-in-depth (covers pre-guard JSON) — which also feeds
      `latest_news.json`, so the narrow filter was removed. This now
      genuinely covers newsletter L8.
- [x] **404 duplication**: catch-all route now `abort(404)`s through the
      single `errorhandler(404)`.
- [x] **Bot-check duplication**: shared `bot_check_failed()` helper +
      shared `_bot_fields.html` Jinja partial included by both forms.
- [x] **Dupe-check efficiency**: `find_rows_by_email()` uses
      `filter__email__equal` (exact, server-side) for both the existing-
      subscriber check and the race cleanup, replacing two full-text
      `search` queries + client-side re-filters.
- [x] **Pagination-collision guard**: `baserow_list_rows` strips
      `page`/`size` from caller filters (a stray `page` would loop
      forever).
- [x] **Baserow helper duplication** (subscriber_app vs
      purge_pending_subscribers): valid cleanup, deferred to Phase 7's
      config-dedup item — the purge script is deliberately standalone ops
      tooling; unify when Phase 7 builds the shared config/client module.

Verify: subscribe/confirm/unsubscribe flows end-to-end against a test row;
rate limit observed per-client after deploy; one-click unsubscribe
POST still works from a real mail client. (26-check Flask test-client
harness passing locally; deploy needs a `musemaniac-subscriber.service`
restart.)

## Phase 5 — Email templates & dark mode (branch: `fix/email-dark-mode`)

Done 2026-08-26 (implementation `979bdce`, then an automated /code-review at
high effort found 10 issues — all resolved in `b804a20`, see follow-ups).
Decisions (user-approved): **auto-tighten then fail** for the 102KB gate,
and **L2 included** (not skipped).

- [x] **[newsletter M6]** `reminder_email.html`: bg+color paired on the
      same element everywhere; CTA got a `.cta` class; `p` added to the
      `[data-ogsc]` set; closing `<p>` paired. (The review then reworked
      the whole `[data-ogsc]` block — see follow-up 1.)
- [x] **[newsletter L3]** All span-based sections (stats bar, most-active,
      tool watch, event_t2, footer incl. its links) pair bg+color on the
      span/a itself; the `[data-ogsc]` span/a rules force those inline
      backgrounds dark for webmail dark mode.
- [x] **[newsletter L4]** `.rate-box` border + link `[data-ogsc]`
      overrides; the `<a>` moved *inside* the cell as `display:block`
      (Word-engine Outlook ignores block anchors wrapped around tables, so
      the rows were unclickable there).
- [x] **[newsletter M7]** Email edition over 102KB auto-tightens
      `section_cap` 4→3→2→1, and exits 1 (→ ERR trap → failure email) if
      even cap 1 exceeds the limit; abort happens before latest_news.json
      and Baserow registration.
- [x] **[newsletter L6]** `split('/')[1]` → `[-1]` in all four template
      spots; slash-less most-active entries skip the org suffix.
- [x] **[newsletter L2]** whats_new anchor styling is regex-based
      (tolerates extra attributes, skips pre-styled anchors); lines are
      dropped per-token when the stat they need is 0.

### Phase 5 review follow-ups (automated /code-review of `979bdce`, high, 2026-08-26)

10 findings, all resolved in `b804a20`:

- [x] **(1, severe)** Reminder's `[data-ogsc]` block pinned text dark but
      not backgrounds light → the new inline `#fbfbfb` backgrounds would
      render dark-on-dark in Outlook webmail dark mode. All element rules
      now pin background AND color light; `.cta` table/td/a re-pinned dark
      with light text afterwards.
- [x] **(2)** `latest_news.json` was built from the tightened
      email_context → now a fixed `cap=4`, so shrinking the email can't
      shrink the website news box.
- [x] **(3)** The gate couldn't converge (tool_watch + individual_events
      were uncapped) → `build_context` caps both under `section_cap`
      (groups and events-per-group for tool watch); both sections gained
      "see all N in the full edition" links.
- [x] **(4)** Rating-box padding sat on the anchor, which Word-engine
      Outlook ignores → padding back on the td, anchor stays
      `display:block` without padding.
- [x] **(5)** whats_new `link_style` violated the CLAUDE.md pairing rule →
      now includes `background-color:#EDEBF5` (links render in the
      lavender What's-new box).
- [x] **(6)** Cap loop re-fetched Baserow source stats per iteration (up
      to 5×, with mid-loop-blip inconsistency risk) → fetched once in
      `main()` and passed into every `build_context`.
- [x] **(7)** Webmail overrides mis-scoped → `[data-ogsc] a` pins
      background dark; `.wn-box a/span` pin the panel tone `#1C1736`.
- [x] **(8)** `confirmation_email.html` (the sibling copy) still had the
      original unpaired-color bug → brought fully in line with the
      reminder (same pairing, same corrected `[data-ogsc]` + `.cta`).
- [x] **(9)** Anchor regex only matched a lone double-quoted href →
      tolerates extra attributes/whitespace, skips anchors with `style=`.
- [x] **(10)** `stats_available` gated both tokens on sources alone
      ("0 countries" could ship) → per-token gating.
- Minors also fixed: dead pre-loop inits, redundant `getsize` recompute,
  Jinja template cached across the 5 renders per run.

Verify: 53-check scratchpad harness green (pairing audits over all three
email templates, both dark-mode pinning directions, cap convergence,
fixed-cap latest_news under a tightened email, hard-fail leaves no side
effects); dry-run on the VPS against real data renders clean (39.9 KB).
**Still open: test send viewed in Outlook desktop on Windows dark mode per
CLAUDE.md** — the one client no harness can simulate.

## Phase 6 — Pipeline coverage & robustness (branch: `fix/pipeline-coverage`)

Done 2026-08-26/27 (implementation `6aa2f88`, review follow-ups `10297da`,
Python 3.10 hotfix `cffaa92`). Decisions: **surface + systemic abort** for
non-rate-limit 403s (warn per URL; abort only when distinct forbidden
owners ≥ max(5, 10% of sources)) — recommended option, question went
unanswered so recorded here; **ai_title column created by hand** in the
Baserow UI (the database token cannot alter schema — POST returned
ERROR_NO_PERMISSION_TO_TABLE), resolved by name at runtime.

- [x] **[pipeline M4]** `github_get` taxonomy: `Retry-After` honored
      (HTTP-date/junk falls back to 60s), exhausted primary quota waits to
      reset, headerless 429 backs off 60s — all retried ≤3× with a 15-min
      per-wait cap (abort promptly instead of stalling the 7AM cron for
      hours). Non-rate-limit 403s recorded per URL, listed in the summary,
      systemic abort by distinct-owner threshold. Abort messages say the
      truth: cron will NOT retry; re-run `cron_newsletter.sh` manually.
- [x] **[pipeline M5]** Event feeds paginate per_page=100 up to 3 pages
      with a date-based stop (bot bursts can't hide real activity);
      `collect_new_repos` paginates past fork padding, stops at cutoff.
      API calls counted centrally in `github_get`.
- [x] **[pipeline M2]** All event types score in `SCORE_BATCH_SIZE=5`
      batches — no more whole-category tier-3 from an overflowing batch.
- [x] **[pipeline M7]** Untrusted content delimited with BEGIN/END
      UNTRUSTED markers + a never-follow-instructions system-prompt clause;
      marker-lookalike lines in feed text neutralized before interpolation
      (escape-proofing); model output length-capped (summary 400,
      writeup 900, ai_title 200, ai_summary 600).
- [x] **[pipeline L7]** Recovery uses a server-side filters-JSON tree:
      tier empty AND (collected_date after window OR empty) — verified
      against production (200; the 93 old unscored rows are exactly the
      backlog this stops re-fetching). A 400 on the filter aborts loudly
      instead of silently disabling recovery.
- [x] **[pipeline L8]** `resolve_ai_title_field()` finds the hand-created
      column by name, type-checks it (long_text/text), and PATCHes
      `ai_title` separately so a title failure can't unpersist tier.
      **Column created by the user 2026-08-27** (field 7299, long_text)
      and verified resolving on the VPS — fully live.

### Phase 6 review follow-ups (automated /code-review of `6aa2f88`, high, 2026-08-26)

The review agent stalled once mid-run (as in Phase 4); a resume nudge
recovered all 14 verdicts (8 confirmed, 5 plausible, 1 refuted). All 10
reported findings resolved in `10297da`:

- [x] **(1)** Headerless 429 was misfiled as "forbidden" → 429 always
      throttling, 60s backoff + retry; only literal 403s can be forbidden.
- [x] **(2)** Abort threshold counted URLs (one source with 6 tracked
      repos, or 3 private-gone orgs, could kill the weekly send) → counts
      distinct owners parsed from URLs, scaled max(5, 10% of sources).
- [x] **(3)** Up-to-hours silent rate-limit sleeps + false "pipeline
      retries" message → 15-min per-wait cap; messages name the manual
      re-run playbook.
- [x] **(4)** A 400 on the new filters would silently kill recovery
      forever → loud SystemExit; both filter forms verified on production.
- [x] **(5)** date_after filter stranded empty-collected_date rows →
      OR-empty filter group keeps them recoverable (old client behavior).
- [x] **(6)** ai_title name-only match + combined PATCH could unpersist
      tier → type check at resolution; ai_title in its own PATCH.
- [x] **(7)** Unguarded `title[:50]`/`[:60]` slices vs Baserow explicit
      nulls → titles normalized once for input-file and recovered rows.
- [x] **(8)** `int(Retry-After)` crashed on RFC-9110 HTTP-date → defensive
      parse, 60s fallback.
- [x] **(9)** Feed text could fake the END marker and escape the
      delimited region → marker-lookalike lines neutralized in the shared
      sanitizer.
- [x] **(10)** Guard prose/markers/clamps/groq_request hand-duplicated
      across both scorers → new `scripts/llm_shared.py` single-sources all
      of it (UNTRUSTED_GUARD, wrap_untrusted, clamp, groq_request); both
      scorers import it. Two weakest cleanup findings were cut by the
      review's 10-finding cap (pagination-loop duplication; the rest of the
      ai_title-machinery cluster) — noted, not actioned.

Hotfix `cffaa92` (found at deploy): backslash inside an f-string
expression needs Python 3.12+; the VPS runs 3.10.12. The untrusted article
block is now built outside the prompt f-string.

Verify: 32-check monkeypatched harness green (throttle taxonomy incl.
HTTP-date/headerless-429, wait cap, owner counting + both e2e threshold
outcomes, filters shape, empty-date recovery, marker-escape neutralization,
null-title survival, split PATCH, wrong-type refusal, 400-abort,
single-source greps); all four files compile on VPS Python 3.10; live
read-only smoke of the recovery filter against production passed.

## Phase 7 — Housekeeping batch (branch: `fix/review-lows`)

Done 2026-08-27 (implementation `d83480a`, review follow-ups `02d22d0`,
exec-bit fix `ea27735`). Originally planned as `chore/review-lows`;
renamed pre-merge per the review — CLAUDE.md's naming scheme only
documents `feature/` and `fix/`, and the branch carries code. Decision
(user, 2026-08-27): **mask emails in pipeline logs** (`ca***@domain` +
Baserow row id); the purge script's eyes-on listing keeps full addresses
as a documented exemption.

**DEPLOY MANIFEST (deployed 2026-08-27, all 18 files verified by
checksum) — the two NEW modules are imported at module load by the Flask
app and the cron pipeline; missing them in an scp takes the site down and
kills the Wednesday send:**

- NEW: `baserow_client.py`, `baserow_config.py`, plus the reworked
  `cron_newsletter.sh` (repo copy is now the source of truth)
- Modified: `add_github_museums.py`, `collect_github_activity.py`,
  `collect_news.py`, `enrich_github.py`, `enrich_github_activity.py`,
  `generate_newsletter.py`, `get_field_ids.py`,
  `purge_pending_subscribers.py`, `run_newsletter.sh`, `score_news.py`,
  `score_newsletter_content.py`, `search_github_museums.py`,
  `send_newsletter.py`, `send_reminders.py`, `subscriber_app.py`
- `subscriber_app.py` changed ⇒ restart `musemaniac-subscriber.service`

- [x] Timeouts on remaining HTTP calls: `enrich_github.py` (Wikidata
      SPARQL 120s, Baserow 30s), `search_github_museums.py`,
      `add_github_museums.py`. (`register_past_edition.py` already had
      them since Phase 2.)
- [x] `run_newsletter.sh`: `set -E` (verified errtrace); failure-email
      tail sleeps 2s so the async `tee` can flush; logs pruned at 30 days
      (hyphen AND underscore patterns) with an honest comment.
- [x] Config dedup: new `baserow_config.py` single-sources the sources
      table id + all field-id maps for 7 importers; dead `TECH_FIELDS`
      and the hardcoded `field_7222`/`field_7192` killed. New
      `baserow_client.py` row CRUD shared by subscriber_app (helpers
      delegate) and the ops/pipeline scripts — closes the Phase 4
      review's deferred subscriber_app/purge duplication finding.
- [x] Log retention + PII: 30-day prune + `mask_email()` in both send
      scripts (decision above).
- [x] `enrich_github_activity.py`: collector stamps an explicit
      `details.description_truncated`; enricher trusts only the flag;
      misleading `remaining` variable removed.
- [x] `get_field_ids.py` unpadded-id printout; `KNOWN_GITHUB` documented
      as a drifting snapshot (add_github_museums dedups against live
      Baserow anyway).
- [x] `cron_newsletter.sh` in the repo (LF, executable), restructured —
      see follow-up 3.

### Phase 7 review follow-ups (automated /code-review of `d83480a`, high, 2026-08-27)

10 findings, all resolved in `02d22d0`:

- [x] **(1, reproduced)** New `set -E` + unguarded SENT_COUNT grep turned
      a SUCCESSFUL send with a bad `.sent` marker into two spurious
      failure emails and no success email → `|| true` inside the
      substitution.
- [x] **(2)** No deploy manifest for the two new module-level-imported
      files → manifest above, recorded before merge.
- [x] **(3)** `cron_newsletter.sh` died silently (no log, no email) if
      `.env` sourcing failed → opens the log first, guards the source,
      leaves a FATAL line (an admin email is impossible there — the
      Resend key lives in the failed .env).
- [x] **(4)** Raw `e.response.text` under the masked ERROR line leaked
      recipients via Resend 4xx bodies → masked in both send scripts.
- [x] **(5)** `mask_email` revealed 1–2 char local parts entirely →
      short locals keep fewer characters.
- [x] **(6)** Half-migration → ALL remaining hand-rolled Baserow
      pagination ported to `baserow_client` (subscriber_app ×3,
      generator stats, collector sources, add/enrich museums scripts,
      both send fetches). `collect_news`/`score_news` keep bespoke loops
      deliberately (custom abort/filter semantics from Phases 1/6).
- [x] **(7)** Dead legacy `len == 300` heuristic deleted — the flag is
      the only truth source (the JSON is transient per-run output).
- [x] **(8)** Purge listing's full addresses documented as a deliberate
      exemption (the listing exists to be reviewed before `--apply`).
- [x] **(9)** `description_truncated` stripped from LLM prompt payloads.
- [x] **(10)** Branch renamed `chore/` → `fix/` per CLAUDE.md.

Verify: 30-check harness green (Flask test-client subscribe/unsubscribe/
sources/archive through the shared client, purge deletes, masked send
output incl. response bodies, truncation matrix, prompt strip, cron
log-before-source ordering, SENT_COUNT guard, no-pagination-left sweep);
py_compile on VPS Python 3.10; service restarted and live routes 200;
purge + generate dry-runs clean against production through the client.

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
| 2026-08-26 | 0 (verify) | — | — | closed same day: FORM_SECRET fixed on VPS + verified (see Phase 0) |
| 2026-08-26 | 1 | fix/silent-failures | 1317844 | 2026-08-26 (5 scripts, verified on VPS) |
| 2026-08-26 | 2 | fix/rerun-safety | 6608d96 + 1c91f6d (merged to master 2026-08-26) | 2026-08-26 (5 scripts; originals in `.bak-20260826-phase2/`; verified compiling on VPS) |
| 2026-08-26 | 3 | fix/dedup-hash | 11741c9 + a905dfa (merged to master 2026-08-26) | 2026-08-26 (4 files incl. new `json_cache.py`; originals in `.bak-20260826-phase3/`; compile + `--commit-seen` guard verified on VPS) |
| 2026-08-26 | 4 | fix/site-hardening | d61ed94 + 04a0935 (merged to master 2026-08-26) | 2026-08-26 (4 scripts + 6 templates; originals in `.bak-20260826-phase4/`; service restarted, now bound to 127.0.0.1; live smoke tests: bot fields, real 404, unsubscribe GET, privacy, sitemap all green) |
| 2026-08-26 | 5 | fix/email-dark-mode | 979bdce + b804a20 (merged to master 2026-08-26) | 2026-08-26 (generate_newsletter.py + 3 templates; originals in `.bak-20260826-phase5/`; compile + checksums + real-data dry-run verified on VPS; pushed to origin 2026-08-26; Outlook-desktop dark-mode eyeball still pending) |
| 2026-08-27 | 6 | fix/pipeline-coverage | 6aa2f88 + 10297da + cffaa92 (merged to master 2026-08-27) | 2026-08-27 (3 scripts + new `llm_shared.py`; originals in `.bak-20260827-phase6/`; compile on VPS Python 3.10 + checksums + read-only recovery-filter smoke verified; pushed to origin 2026-08-27; ai_title column created + verified 2026-08-27) |
| 2026-08-27 | 7 | fix/review-lows | d83480a + 02d22d0 + ea27735 (merged to master 2026-08-27) | 2026-08-27 (15 scripts + 2 new modules + both shell wrappers, all 18 checksum-verified; originals in `.bak-20260827-phase7/`; subscriber service restarted, live routes 200, purge + generate dry-runs clean; pushed to origin 2026-08-27). **All seven phases of this plan are now complete.** |
