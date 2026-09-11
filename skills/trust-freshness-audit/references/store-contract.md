# Observation store contract (trust-freshness-audit)

This skill consumes collected HTTP/render and optional corroboration observations.
It does not fetch or search. The optional offline recorder can use a supplied
entity_profile for source disambiguation; the detector itself reads the recorded
entity_match values, not that profile. The current orchestrator does not obtain
external search results. See [corroboration honesty](corroboration-honesty.md).

| Type | Cardinality | `value` shape (fields this skill reads) |
|---|---|---|
| `HTTP_FETCH` | one per crawled URL | `{status_code, final_url, headers, html}` — `lib.common.http_client.fetch_url()`'s shape. |
| `RENDER` | zero or one per sampled URL | `{status, status_code, html}` — preferred when status is ok, HTTP status is 2xx and HTML is nonempty. Otherwise use valid 2xx raw HTML; failed-page HTML is not site-content evidence. Shared selection is implemented by [pages.py](../../../lib/common/pages.py). |
| `PAGE_CLASSIFICATION` | zero or one per URL | `{page_type}` — used only to scope D-TRUST-06's named-author check to substantive content (`article`), never to gate the other checks. |
| `CLAIM_CORROBORATION` | zero or one per claim | `{claim_id, performed: bool, query, method, timestamp, sources: [{url, title, snippet, entity_match: bool}]}`. New in this skill, distinct from `entity-semantic-audit`'s `CORROBORATION` type (that one records an entity-*name* collision lookup; this one records a lookup for one specific *claim*). Absent or `performed: false` means D-TRUST-05 does not fire — never a fabricated "no corroboration found" (`corroboration-honesty.md`). Each source's own `entity_match` records whether it was confirmed to be about *this* entity and not a similarly-named one — see D-TRUST-05's identity-confusion guard. |

Archetype gating reads the store's top-level `archetype` field
(`schemas/observation.schema.json`), set once by `lib/site_observer/classify.py`.

## Deterministic-first extraction

Per this skill's design brief: prefer deterministic extraction and comparison,
never an LLM judgment where a structural pattern or a normalized-value comparison
will do. `scripts/build_claim_table.py` extracts, per page, entirely from
`html`/`headers` — no model call:

- **Date signals** — JSON-LD `datePublished`/`dateModified`, a visible
  "Updated/Published <date>" text pattern, the `Last-Modified` HTTP header, and
  a copyright year.
- **Time-sensitive language** — a fixed, generic phrase-pattern list (`currently`,
  `this year`, `upcoming`, `now available`, `limited time`, `as of`, `latest`, ...),
  never a brand/vertical-specific phrase.
- **Entity-level factual claims** — founding year and employee/customer count,
  keyed and normalized so the same fact in different formatting compares equal
  (`$1,000` == `$1000.00`), and scoped to facts that don't legitimately vary by
  product/plan/region/department (see `trust-checks.md` D-TRUST-03's scope
  note — contact phone was cut from this list after a hostile review found
  sales-vs-support lines being flagged as contradictions).
- **Falsifiable superlatives/statistics** — a fixed pattern list (`#1`, `leading`,
  `best-selling`, a percentage, a "N,NNN+ customers" count), each checked for a
  citation (a link, footnote marker, or "according to ...") within a fixed word
  window.
- **Organizational signals** — classified roles or exact conventional path segments,
  structured operator identity and actionable contact methods, and
  a named-author byline (`<author name>` text pattern or JSON-LD `author`) on
  `article`-typed pages.

No sentence-level claim classification or conflict judgment requires a model call
in this implementation — see `trust-checks.md` for the one place (D-TRUST-03 prose
claims) where a future LLM-instrument upgrade is a documented, not required,
extension point.

## Output: the claim table

See `claim-table-contract.md` for the exact shape `build_claim_table.py` produces
and `detect_trust.py` consumes.
