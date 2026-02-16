# Tool Watch Feature

The Tool Watch feature tracks museum-sector technologies (IIIF, Omeka, CollectiveAccess, etc.) and surfaces their activity in a dedicated newsletter section.

## Why Tool Watch?

Museums don't just build projects — they also adopt and contribute to shared tools. Tool Watch highlights updates to key technologies used across the sector, even when they span multiple GitHub organizations.

## How it works

1. **Collection**: `collect_github_activity.py` fetches events from tracked repos listed in the Technologies table
2. **Scoring**: Technology events are scored like source events, with `source_type: "technology"` tags
3. **Grouping**: `score_newsletter_content.py` groups technology events by parent (e.g., "IIIF") and picks the top-scored items per group
4. **Display**: Newsletter renders a "🔧 Tool Watch" section showing updates grouped by technology family

## Baserow Technologies Table Setup

### Required Fields

| Field Name | Field Type | Description | Example |
|------------|-----------|-------------|---------|
| `name` | Text | Technology/project name | Mirador |
| `parent` | Text | Parent technology (optional) | IIIF |
| `category` | Single Select | Technology category | viewer, cms, standard, preservation, framework, toolkit |
| `tracked_repos` | Long Text | GitHub repos to track (one per line) | `ProjectMirador/mirador`<br>`IIIF/mirador3` |
| `website` | URL | Official website | https://projectmirador.org |
| `description` | Text | Brief description | IIIF-compatible image viewer |
| `active` | Boolean | Track this technology? | ✓ |

### Category Options

Create these single_select options for the `category` field:
- `viewer`
- `cms`
- `standard`
- `preservation`
- `framework`
- `toolkit`

### Example Entries

#### IIIF Ecosystem

| name | parent | category | tracked_repos | active |
|------|--------|----------|---------------|--------|
| Mirador | IIIF | viewer | ProjectMirador/mirador | ✓ |
| Cantaloupe | IIIF | framework | cantaloupe-project/cantaloupe | ✓ |
| IIIF Validator | IIIF | toolkit | IIIF/validator | ✓ |

#### CMS/Collection Management

| name | parent | category | tracked_repos | active |
|------|--------|----------|---------------|--------|
| Omeka S | Omeka | cms | omeka/omeka-s | ✓ |
| Omeka Classic | Omeka | cms | omeka/Omeka | ✓ |
| CollectiveAccess | | cms | collectiveaccess/providence | ✓ |
| AtoM | | cms | artefactual/atom | ✓ |

#### Standards

| name | parent | category | tracked_repos | active |
|------|--------|----------|---------------|--------|
| Darwin Core | | standard | tdwg/dwc | ✓ |
| IIIF Presentation API | IIIF | standard | IIIF/api | ✓ |

## Configuration

### Environment Variables

Add to `.env`:

```bash
TECHNOLOGIES_TABLE_ID=your-baserow-table-id
```

### Optional

The feature gracefully degrades if `TECHNOLOGIES_TABLE_ID` is not set. The newsletter pipeline works exactly as before without it.

## Newsletter Output

When technology events exist, a "Tool Watch" section appears between "Notable Pushes" and the feedback section:

```
🔧 Tool Watch

IIIF
  Mirador — v4.1.0 released. New annotation panel with
  improved touch support.
  View on GitHub

  Cantaloupe — 8 commits to main. Added HEIF input format
  support.
  View on GitHub

Omeka
  Omeka S — v4.2.1 patch release. Bug fixes for CSV import
  and REST API pagination.
  View on GitHub
```

## Future Enhancements

- **Discovery script**: Auto-suggest technologies from GitHub topics (`iiif`, `glam`, `digital-preservation`)
- **Cross-reference**: Detect when museums fork/adopt tracked technologies
- **/sources page**: Add Technologies tab showing tracked tools grouped by category
- **Technology spotlight**: Dedicated spotlight when major versions ship

## Notes

- Technology events can overlap with source events (if a museum contributes to a tracked tool) — both are kept
- Tier 3 (routine) technology events are filtered out of Tool Watch but still appear in stats
- The `parent` field groups related technologies (e.g., Mirador + Cantaloupe both under IIIF)
- Leave `parent` empty for standalone technologies (CollectiveAccess, AtoM, etc.)
