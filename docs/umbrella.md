PROJECT: Extend an existing Wikidata-based “Museums” database to also include
umbrella organizations and other non-museum entities that publish technical
or digital-development content.

DESIGN DECISIONS (FIXED)
- Use QID when data comes from Wikidata.
- Use INT:/EXT: prefixed IDs when data does NOT come from Wikidata.
- Do NOT standardize country values at this stage (store human-readable names only).
- Add ONE new field to support filtering by organization type.
- Keep the existing table and fields intact.

──────────────────────────────────────────────────────────────────────────────
1) IDENTIFIERS (QID / URI STRATEGY)
──────────────────────────────────────────────────────────────────────────────

Existing fields:
- qid
- museum_uri

Rules:

1. Wikidata-backed entities
- qid = "Q12345"
- museum_uri = "https://www.wikidata.org/entity/Q12345"

2. Non-Wikidata entities (umbrella orgs, org-level blogs, etc.)
- qid MUST use a non-Wikidata prefix:
  - "INT:<slug>"   (internally created entities)
  - "EXT:<slug>"   (externally discovered but non-Wikidata entities)
- museum_uri should use a stable internal URI format:
  - "urn:entity:<slug>"   OR
  - "https://<your-domain>/entity/<slug>"

Constraints:
- Wikidata QIDs always match: ^Q[0-9]+$
- INT:/EXT: IDs must NEVER start with "Q"
- All relations and Content Entries must reference entities by qid

This guarantees:
- No collisions with Wikidata
- One unified ID system for museums and non-museum entities

──────────────────────────────────────────────────────────────────────────────
2) ENTITY TYPE (NEW FIELD)
──────────────────────────────────────────────────────────────────────────────

Add ONE new field to the existing table:

Field name:
- entity_type

Type:
- Single select (or text enum)

Allowed values:
- MUSEUM
- UMBRELLA_ORG   (organizations that operate or represent multiple museums)
- OTHER_ORG      (non-museum orgs publishing relevant digital/tech content)
- INDIVIDUAL     (individual developers/researchers tracked by specific repos)

Rules:
- All existing rows default to: entity_type = MUSEUM
- New non-museum rows MUST explicitly set entity_type
- entity_type is the primary filter for UI and reporting

──────────────────────────────────────────────────────────────────────────────
2b) TRACKED REPOS (NEW FIELD)
──────────────────────────────────────────────────────────────────────────────

Field name:
- tracked_repos

Type:
- Long text

Format:
- One repo per line in owner/repo format (e.g. "rsimon/tiny-iiif")

Rules:
- If populated: only those specific repos are monitored (via /repos/{owner}/{repo}/events)
- If empty: entire org is monitored (via /orgs/{login}/events + /orgs/{login}/repos)
- Primarily used for INDIVIDUAL entities, but works for any entity type

──────────────────────────────────────────────────────────────────────────────
3) COUNTRY FIELD (NO STANDARDIZATION)
──────────────────────────────────────────────────────────────────────────────

Field:
- country

Rules:
- Store human-readable country names only (e.g. "Sweden", "United States")
- Do NOT normalize or map to ISO codes at this stage
- Consistency is encouraged but not enforced programmatically

This avoids breaking existing data and keeps ingestion simple.

──────────────────────────────────────────────────────────────────────────────
4) USING EXISTING FIELDS FOR NON-MUSEUM ENTITIES
──────────────────────────────────────────────────────────────────────────────

The existing fields are reused for all entity types:

- Museum name        → display name for any entity
- website            → official website
- rss                → RSS/Atom feed (if available)
- rss_status         → current feed status
- rss_last_checked   → timestamp
- rss_last_post_date → timestamp
- github / github_url → GitHub org or primary repo
- social fields      → optional, same semantics for all entities

No field semantics change — only the interpretation of “what a row represents”.

──────────────────────────────────────────────────────────────────────────────
5) CONTENT ENTRIES (UNCHANGED, BUT MORE POWERFUL)
──────────────────────────────────────────────────────────────────────────────

- Content Entries remain the canonical store for:
  - blog posts
  - RSS items
  - GitHub releases / repo activity
- Each Content Entry links to exactly ONE entity via qid
- Entities of any type (MUSEUM, UMBRELLA_ORG, OTHER_ORG) may produce content

──────────────────────────────────────────────────────────────────────────────
6) DISCOVERY PIPELINE (UPDATED FOR INT / EXT ENTITIES)
──────────────────────────────────────────────────────────────────────────────

For each discovered organization:

1. Attempt Wikidata lookup
- If found → use Wikidata QID
- If not found → generate:
  - qid = "INT:<slug>" (preferred) OR "EXT:<slug>"
  - museum_uri = internal canonical URI

2. Classify entity_type
- If Wikidata instance = museum → MUSEUM
- If site describes operating multiple museums → UMBRELLA_ORG
- Otherwise → OTHER_ORG

3. Populate existing fields
- website, rss, github_url, social links

4. Ingest content into Content Entries
- Link using qid

──────────────────────────────────────────────────────────────────────────────
7) OPTIONAL: RELATING UMBRELLA ORGS TO MUSEUMS
──────────────────────────────────────────────────────────────────────────────

If relationships are needed:

- Add a minimal relation table OR a parent reference field
- Only one supported relation type:
  - OPERATES

This is OPTIONAL and can be added later without affecting the core model.

──────────────────────────────────────────────────────────────────────────────
8) ACCEPTANCE CRITERIA
──────────────────────────────────────────────────────────────────────────────

- Rows can represent both museums and non-museum organizations.
- entity_type allows filtering by type.
- qid clearly distinguishes Wikidata vs INT/EXT entities.
- Existing Wikidata import continues to work unchanged.
- No country standardization required.
- Content Entries can be linked to any entity type.

END
