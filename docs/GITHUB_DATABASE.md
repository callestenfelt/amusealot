# Museum GitHub Database

## Overview

The Baserow Museums table (745) at http://77.42.40.207/database/195/table/745/ has been enriched with GitHub account data for museums worldwide.

## Fields

| Field | ID | Type | Description |
|-------|----|------|-------------|
| github | field_7222 | text | GitHub username/org login |
| github_url | field_7223 | url | Full GitHub profile URL |

## Current Data (2026-02-07)

**Total museums with GitHub accounts: 133**

### By source

| Source | Count | Method |
|--------|-------|--------|
| Wikidata P2037 (existing rows updated) | 17 | SPARQL query, matched by QID |
| Wikidata P2037 (new rows added) | 40 | SPARQL query, added to DB |
| GitHub API search (curated) | 76 | Org search + manual curation |

### By country (top)

| Country | Count |
|---------|-------|
| United States | ~50 |
| United Kingdom | ~12 |
| Australia | ~8 |
| Germany | ~7 |
| Denmark | ~5 |
| Netherlands | ~4 |
| Switzerland | ~4 |
| Sweden | ~3 |
| Finland | ~3 |
| Israel | ~3 |
| Others | ~34 |

### Notable institutions

**Highest GitHub activity (by repo count):**
- Det Kgl. Bibliotek / Royal Danish Library (353 repos)
- SFO Museum (251 repos)
- Europeana (214 repos)
- Fitzwilliam Museum (112 repos)
- British Museum Digital Humanities (95 repos)
- Wellcome Collection (95 repos)
- Netwerk Digitaal Erfgoed (86 repos)
- museum4punkt0 (79 repos)
- Jerusalem Science Museum (77 repos)
- Luomus / Finnish Museum of Natural History (62 repos)

## Scripts

All scripts are in `scripts/` and interact with the Baserow API.

### enrich_github.py
Queries Wikidata for museums with GitHub accounts (P2037 property) and updates/adds them to Baserow.

```
python scripts/enrich_github.py           # dry run
python scripts/enrich_github.py --apply   # write to Baserow
```

### search_github_museums.py
Searches GitHub API for museum-related organizations. Two phases:

```
python scripts/search_github_museums.py --search    # find org candidates
python scripts/search_github_museums.py --details   # fetch org details (resumable)
```

Requires a GitHub token (configured in script) for reasonable rate limits.

### filter_github_museums.py
Filters raw GitHub search results to actual museums. Excludes student projects, NFT galleries, software companies, etc. Outputs `github_museums_curated.json`.

```
python scripts/filter_github_museums.py
```

### add_github_museums.py
Adds curated GitHub museums to Baserow as new rows.

```
python scripts/add_github_museums.py           # dry run
python scripts/add_github_museums.py --apply   # write to Baserow
```

## Data files

| File | Description |
|------|-------------|
| `scripts/github_museum_candidates.json` | Raw search results (411 orgs) |
| `scripts/github_museum_details.json` | Detailed org info from GitHub API (411 orgs) |
| `scripts/github_museums_curated.json` | Filtered list of real museums (76 orgs) |

## Adding more museums manually

To add a museum GitHub account manually:
1. Add a row in Baserow with the museum name, country, website
2. Set `github` (field_7222) to the GitHub username
3. Set `github_url` (field_7223) to `https://github.com/{username}`

Or add it to `github_museums_curated.json` and re-run `add_github_museums.py`.
