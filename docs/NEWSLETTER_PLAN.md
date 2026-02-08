# Musemaniac Newsletter Plan

## Vision

A periodic newsletter (weekly or biweekly) covering technical development activity in the museum sector. Two sections:

1. **GitHub Radar** - What museums are building, releasing, and open-sourcing
2. **Article Digest** - Curated articles about museum digital/tech topics (sources TBD)

Inspired by [heripo-research-radar](https://github.com/heripo-lab/heripo-research-radar), an AI-powered newsletter for Korean cultural heritage that costs $0.2-1 per issue to run.

---

## Part 1: GitHub Radar — Detailed Data Analysis

### What we have now (collect_github_activity.py)

The collection script monitors 133 museum GitHub orgs and produces a JSON file. A 3-day window yields ~37 events from ~20 active orgs.

**Three event types collected:**

#### 1. `new_repo` — A museum created a new public repository
| Field | Source | Quality |
|-------|--------|---------|
| `repo` | Events API | Always present, e.g. `Naturhistoriska/specify-iiif-manifest` |
| `title` | repo name | Always present |
| `description` | repo description | **Often empty** — many repos have no description at creation |
| `url` | html_url | Always present |
| `date` | created_at | Always present |
| `details.language` | GitHub detection | Often `null` at creation (no code yet) |
| `details.stars` | repo metadata | Always 0 for new repos |
| `details.topics` | repo topics | **Usually empty** — rarely set at creation |

**Newsletter value:** HIGH — a museum starting a new project is inherently newsworthy. But the raw data often lacks context (no description, no language, no topics).

#### 2. `release` — A museum published a release
| Field | Source | Quality |
|-------|--------|---------|
| `repo` | Events API | Always present |
| `title` | release name or tag | Present but **often poor quality** (e.g. "similar uniquie constraint", "delete portraitimagefile old") |
| `description` | release body, truncated to 300 chars | **Often empty** |
| `url` | release html_url | Always present |
| `date` | created_at | Always present |
| `details.tag` | tag_name | Always present, e.g. `v1.0.108` |
| `details.prerelease` | boolean | Always present |

**Newsletter value:** MEDIUM-HIGH — releases signal a project is active and shipping. But many releases are trivial patches with meaningless titles. A museum releasing v2.0 of a IIIF viewer is very different from a patch fixing a typo.

#### 3. `push` — Commits pushed to a default branch
| Field | Source | Quality |
|-------|--------|---------|
| `repo` | Events API | Always present |
| `title` | Generated: "N commit(s) to branch" | **Low value** — often just "Push to main" |
| `description` | First 5 commit messages joined | **Almost always empty** — Events API rarely includes commit details |
| `url` | Compare URL (before...head) | Present when hashes available |
| `date` | created_at | Always present |
| `details.branch` | ref | Always present |
| `details.commit_count` | payload.size | **Often 0** — Events API doesn't reliably provide this |
| `details.distinct_count` | payload.distinct_size | Often 0 |

**Newsletter value:** LOW as-is — "Push to main" with no context tells the reader nothing. This is the bulk of events but currently the least useful.

### The data gap

Looking at real output (2026-02-07, 37 events):
- **31 of 37 events are pushes** with empty descriptions and `commit_count: 0`
- Only 3 new repos, only 2 releases
- Push events are just "Push to main" — no commit messages, no file change info
- This is **not enough to write about** without enrichment

The GitHub Events API is designed for activity feeds, not detailed analysis. It gives us the _signal_ that something happened, but not the _substance_ of what changed.

### Enrichment: What we CAN fetch additionally

For each event detected by the collector, we can make follow-up API calls to get richer data:

#### For all events — Repo metadata
**API:** `GET /repos/{owner}/{repo}`
| Field | Newsletter use |
|-------|---------------|
| `description` | What the project is about |
| `language` | Primary programming language |
| `topics` | Tags like "iiif", "collection-management", "digital-preservation" |
| `stargazers_count` | Community interest indicator |
| `forks_count` | Reuse indicator |
| `license` | Open source license |
| `homepage` | Live project URL (demo, docs) |
| `created_at` | Project age |
| `pushed_at` | Last activity |
| `open_issues_count` | Project health signal |

**Cost:** 1 API call per unique repo. ~20-30 per collection run.

#### For push events — Commit details
**API:** `GET /repos/{owner}/{repo}/compare/{base}...{head}`
| Field | Newsletter use |
|-------|---------------|
| `total_commits` | Actual number of commits in the push |
| `commits[].message` | What was changed (the real content) |
| `commits[].author` | Who made the changes |
| `files[].filename` | Which files changed |
| `files[].changes` | Lines added/removed |
| `files` count | Scope of the change |

**Cost:** 1 API call per push event. ~20-30 per run. This is the key enrichment — it turns "Push to main" into "Added IIIF manifest support with 3 new endpoints (15 files changed)".

#### For new repos — README content
**API:** `GET /repos/{owner}/{repo}/readme` (returns base64 content)
| Field | Newsletter use |
|-------|---------------|
| README text | Full project description, setup instructions, goals |

**Cost:** 1 API call per new repo. Usually just 1-5 per run.

#### For releases — Full release body
Already fetched but truncated to 300 chars. Could fetch full body if needed via `GET /repos/{owner}/{repo}/releases/tags/{tag}`.

### Enrichment budget

Per collection run (14-day window, ~37 events):
| Call type | Estimated count |
|-----------|----------------|
| Base collection (repos + events per org) | ~266 calls |
| Repo metadata (unique repos) | ~25 calls |
| Compare view (push events) | ~25 calls |
| README (new repos only) | ~3 calls |
| **Total** | **~319 calls** |

GitHub rate limit: 5,000/hour with token. Plenty of headroom.

### Newsletter sections from GitHub data

The GitHub Radar part of the newsletter has 5 sections. Each issue won't necessarily
have all sections — some weeks have no releases, some have no new repos. The stats
bar and most-active section will always have content.

#### Section 1: Stats bar (always present)
A single-line pulse of the museum GitHub ecosystem. Appears as a header or banner.

> *This week: 20 museums active on GitHub · 37 pushes across 28 repos · 3 new projects · 2 releases*

**Data source:** Aggregated counts from all events. No enrichment needed.
**LLM role:** None — pure numbers.

#### Section 2: New repos (3-8 items per biweekly issue)
The strongest signal: a museum decided to open-source something new.

Format per item:
> **The Swedish Museum of Natural History** published **specify-iiif-manifest** — a Python tool
> for generating IIIF manifests from Specify collection management systems.
> `Python` `IIIF` `collections`
> [GitHub →]

**Data source:** `new_repo` events. REQUIRES enrichment — descriptions and topics are
usually empty at creation. Fetch repo metadata + README to get real context.
**LLM role:** Write the 1-2 sentence description from repo metadata + README.
**Filter:** Skip config repos, empty repos, forks-of-templates.

#### Section 3: Release roundup (2-5 items when available)
Museums shipping new versions. High signal — someone decided something was ready.

Format per item:
> **Museum für Naturkunde** shipped **Naturblick Django v1.0.108** — their citizen science
> nature identification backend.

**Data source:** `release` events. Enrichment helps (full release body, repo description).
**LLM role:** Summarize what the release means in context of the project.
**Filter:** Skip trivial patches with no meaningful changes. Major versions (v2+, first
stable) get priority.

#### Section 4: Most active repos (3-5 items, always available)
Development intensity — what museums are actively building right now. Replaces the
"trending" concept (star counts don't work in this niche).

Format:
> **Most active this week:**
> 1. `luomus/lajistore` — 4 pushes, 23 files changed — Finnish biodiversity data store
> 2. `Digital-Repository-of-Ireland/dri-app` — 3 pushes across main+develop — digital repository platform
> 3. `Naturhistoriska/specify-iiif-manifest` — new repo with rapid development, 12 commits in 2 days

**Data source:** `push` events, ranked by: number of pushes, commits, files changed
(from enriched compare data). Deduplicate by repo.
**LLM role:** Write the short description from repo metadata.
**Ranking criteria (computed, not LLM):**
- Number of distinct pushes to default branches
- Total commits (from compare API)
- Total files changed (from compare API)
- Bonus: multiple contributors, multiple days of activity

#### Section 5: Spotlight (1 item per issue)
The editorial centerpiece. The single most interesting event gets a 3-4 sentence writeup.
This is where enrichment data (README, commit messages, file changes) gets fully used.

Format:
> **Spotlight:** NMAAHC (Smithsonian African American History Museum) released **mkvnote** —
> a suite of tools for embedding metadata tags in Matroska video files. This is significant
> for digital preservation: MKV is increasingly used for archival video, and standardized
> metadata embedding helps museums manage large AV collections. The project comes from the
> museum's media conservation team. [GitHub →]

**Data source:** Best item from any event type, with full enrichment (README, commits, repo metadata).
**LLM role:** Write the full spotlight paragraph. This is the most LLM-intensive section.
**Selection:** LLM picks from all enriched events, biased toward:
- New repos with clear museum-tech relevance (IIIF, collections, digital preservation, accessibility)
- Repos from well-known institutions
- Projects that would be reusable by other museums

### Content tiers (for filtering)

#### Tier 1: Always include (if any exist)
- New repos with descriptions mentioning museum-relevant tech
- Major releases (v2+, first stable release, significant features)
- Push activity showing substantial new functionality

#### Tier 2: Include if newsworthy (LLM judgment after enrichment)
- Active development on interesting projects
- New languages/frameworks adopted by a museum
- Incremental releases on significant projects

#### Tier 3: Aggregate or skip
- Routine CI/infrastructure pushes (uptime monitors, config repos)
- Trivial releases (patch bumps, typo fixes)
- Automated data updates (e.g. eht-met-data daily refreshes)
- Repos that are clearly internal/non-reusable

### Revised pipeline for GitHub Radar

```
Step 1: COLLECT (existing script)
  collect_github_activity.py
  → github_activity.json (skeleton events)

Step 2: ENRICH (new script)
  enrich_github_activity.py
  → github_activity_enriched.json
  For each event:
    - Fetch repo metadata (description, language, topics, stars)
    - For pushes: fetch compare view (commit messages, files changed)
    - For new repos: fetch README
    - For releases: fetch full release body if truncated

Step 3: SCORE (new script)
  score_newsletter_content.py
  → scored_newsletter_content.json
  Send enriched data to LLM for:
    - Relevance scoring (1-10)
    - 1-2 sentence newsletter summary
    - Category/tag assignment

Step 4: GENERATE (later)
  generate_newsletter.py
  → newsletter HTML
```

---

## Part 2: Article Digest — ON HOLD

The current RSS content pipeline (234 feeds, 2,092 articles in Baserow table 746) is **not producing content relevant enough** for a museum tech newsletter. Most feeds are general museum news/events, not tech/digital content.

**Status:** Researching alternative content sources manually. Options being explored:
- Curated tech-focused museum blogs and feeds
- IIIF community channels
- Museum tech conference proceedings
- GitHub Discussions / issues from tracked orgs
- Museum tech Twitter/Mastodon/Bluesky accounts
- Dedicated museum technology publications

Will revisit this section once better sources are identified.

---

## Architecture (revised)

```
DATA SOURCES                    PROCESSING                 OUTPUT
============                    ==========                 ======

GitHub API (133 museums)
  - New repos
  - Releases             →  Collect → Enrich → Score  →  Newsletter HTML
  - Significant pushes         (API)    (API)   (LLM)      - Email
                                                            - RSS feed
                                                            - Web archive
[TBD content sources]
  - Tech articles        →  [On hold — researching]  →
  - Blog posts
```

## Tech Stack

- **Python** — matches existing scripts, Groq/Llama already set up
- **Groq/Llama 3.3** — AI scoring and summarization (free tier: 20 req/min)
- **Jinja2** — HTML email templates
- **Resend API** — email delivery
- **Baserow** — data storage

## Estimated Cost Per Issue

| Component | Cost |
|-----------|------|
| GitHub API calls (~320) | Free (with token) |
| Groq/Llama 3.3 scoring | Free tier |
| Groq/Llama 3.3 generation | Free tier |
| Resend email | Free tier |
| **Total** | **$0** (within free tiers) |

## Timeline (revised)

### Phase 1: GitHub activity collection — DONE
- `collect_github_activity.py` built and tested
- 133 orgs, ~37 events per 3-day window

### Phase 2a: GitHub activity enrichment — NEXT
- Build `enrich_github_activity.py`
- Fetch repo metadata, compare views, READMEs
- Output enriched JSON with full context

### Phase 2b: Scoring pipeline
- Build `score_newsletter_content.py`
- LLM scoring of enriched GitHub data
- Filter and rank for newsletter

### Phase 3: Newsletter generation
- Build `generate_newsletter.py`
- HTML email template (Jinja2)
- Preview and archive

### Phase 4: Article Digest content sources
- Research and select better content sources (manual work)
- Build collection pipeline for chosen sources

### Phase 5: Distribution
- Email delivery via Resend
- RSS feed output

## Reference

- [heripo-research-radar](https://github.com/heripo-lab/heripo-research-radar) - AI newsletter for Korean cultural heritage
