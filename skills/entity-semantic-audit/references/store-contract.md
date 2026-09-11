# Observation store contract (entity-semantic-audit)

This skill never fetches (`PROJECT_CONTEXT.md` D-6, D-2). It reads observations
written by `lib/site_observer` collection and, where deterministic extraction is
inconclusive, the two named LLM instruments' outputs. Mirrors
`skills/crawl-render-audit/references/store-contract.md`'s convention — the same
`HTTP_FETCH`/`PAGE_CLASSIFICATION`/`PROBE` types are shared across skills; this file
states only the parts this skill actually reads.

| Type | Cardinality | `value` shape (fields this skill reads) |
|---|---|---|
| `HTTP_FETCH` | one per crawled URL | `{status_code, final_url, headers, html}` — `lib.common.http_client.fetch_url()`'s shape. This skill parses `html` for name/type/offering/location candidates itself; it never requires collection to pre-extract them. |
| `RENDER` | zero or one per sampled URL | `{url, status, status_code, final_url, html}` — prefer an ok render with 2xx HTTP status and nonempty HTML. Otherwise use valid 2xx raw HTML, never failed-page content. This preserves render-only identity facts without treating error pages as the brand. See shared [page selection](../../../lib/common/pages.py). |
| `PAGE_CLASSIFICATION` | zero or one per URL | `{page_type}` — used only to interpret D-ENTITY-06's offering signal per page type, never to gate identity checks generally. |
| `PROBE` | zero or one per URL | `{questions: [{id, category, answered, answer, evidence_span}], source_text_hash}`. This skill reads only `category == "identity"` questions **Q2** (entity type), **Q3** (offering), **Q4** (operating location) from `references/probe-questions.md`'s canonical numbering — never `factual` or `engagement` questions, which belong to `crawl-render-audit` and `engagement-audit` respectively. |
| `CORROBORATION` | zero or one per candidate name, site-level | `{performed: bool, query, matches: [{name, source_url, category}], timestamp}`. New in this skill: the external-lookup record D-ENTITY-03 requires. Absent or `performed: false` means the check does not fire — never a fabricated "no collision found" (mirrors `trust-freshness-audit`'s D-TRUST-05 corroboration-honesty rule; OQ-3 in `PROJECT_CONTEXT.md` is still open, so this observation is expected to be absent in most stores today). |

Archetype gating reads the store's top-level `archetype` field
(`schemas/observation.schema.json`), set once by `lib/site_observer/classify.py`
before any check runs.

## Deterministic-first extraction (this skill's own, not collection's)

Per this skill's design brief: prefer deterministic extraction, fall back to the
probe only where a fact genuinely cannot be pulled from markup or structural text
patterns. `scripts/build_entity_profile.py` extracts, per page, before ever
consulting `PROBE`:

- **Name candidates** — `<title>` (split on brand/page separators — see
  `title_segments()` — so 'Acme - About' contributes 'Acme' as its own
  candidate, not a whole-string mismatch against the homepage's plain 'Acme'),
  `<h1>`, JSON-LD `Organization`/`LocalBusiness`/`Person.name`, and a
  copyright-line pattern found **inside an actual `<footer>` element** (or an
  element whose class/id names it as one) — never a whole-document scan, which
  would catch an unrelated copyright notice (a photo credit, a syndicated
  widget) anywhere on the page and mislabel it as the site's own attribution.
- **Type candidate** — JSON-LD `@type` mapped to a human-readable label, confirmed
  against a structural keyword match in visible prose (never asserted from markup
  alone — see `entity-checks.md` D-ENTITY-02).
- **Offering candidates** — JSON-LD `Product`/`Service`/`Offer` nodes, and a
  structural "we `<verb>` ..." sentence pattern in prose (generic across verticals,
  never a brand/vertical-specific phrase).
- **Location candidates** — JSON-LD `PostalAddress` (via `address` on an
  `Organization`/`LocalBusiness` node).
- **Identity anchors** — JSON-LD `sameAs` array, or a self-referencing `url`
  property, on an `Organization`/`LocalBusiness`/`Person` node.

Only when a field has zero deterministic candidates does `build_entity_profile.py`
fall back to the corresponding `PROBE` identity question, and only when a `PROBE`
observation exists for that page — never fabricated, never silently invented.

## Output: the entity profile

See [entity-profile contract](entity-profile-contract.md) for the exact shape and
its current detector, engagement and optional recorder consumers.
