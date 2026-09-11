# Observation store contract (crawl-render-audit)

This skill never fetches (see `PROJECT_CONTEXT.md` D-6, D-2). It reads observations
written by `lib/site_observer` collection. Collection is a separate, shared-lib
concern; this file is the authoritative contract the detectors in `scripts/` are
written against, so collection can be implemented or replaced without touching a
single check.

Each row is an observation `type` (see `lib/common/observations.make_observation`,
which upper-cases and hyphenates the type into the `OBS-<TYPE>-<hash>` id). All are
optional at the store level: a type that never appears means every check whose
`applicability` depends on it does not fire, and is not recorded as a pass — this
skill never invents an observation to make a check run.

| Type | Cardinality | `source_url` | `value` shape |
|---|---|---|---|
| `ROBOTS` | one, site-level | robots.txt URL | `{url, status: ok\|missing\|error\|unparseable, allow_all, document: {groups: [{user_agent, allow[], disallow[]}], sitemap[], rules[]}}` — exactly `lib.common.robots.fetch_robots()`'s return shape |
| `HTTP_FETCH` | one per crawled URL | the requested URL | `{status_code, final_url, redirect_chain[{from,to,status}], headers{}, encoding, elapsed_ms, evidence{status,content_type,redirect_count,final_url}, html}` — `lib.common.http_client.fetch_url()`'s return shape (`elapsed_ms` added for D-CRAWL-10; `None` when unmeasured) |
| `RENDER` | one per *sampled* URL (subset of `HTTP_FETCH`) | the requested URL | `{url, status: ok\|unavailable\|error, reason, final_url, status_code, html, evidence}` — exactly `lib.site_observer.render.render_page()`'s return shape |
| `SITEMAP` | zero or one, site-level | the sitemap URL | `{status: ok\|missing\|error, entries: [{loc, status_code}]}` |
| `PAGE_CLASSIFICATION` | zero or one per URL | the page URL | `{page_type: product\|article\|organization\|local_business\|faq\|event\|other}` — deterministic semantic-markup classifier, `lib/site_observer/classify.py` |
| `PROBE` | zero or one per URL | the page URL | `{questions: [{id, category: factual\|identity\|engagement, relevant: bool, expects_explicit_statement: bool, answered: bool, answer, evidence_span}], source_text_hash}` — local positive-span instrument, `lib/site_observer/probe.py` |

Detectors read `html` directly off `HTTP_FETCH`/`RENDER` observations and call
`lib.common.extract` on demand (metadata, JSON-LD, links, headings, text) rather than
requiring collection to pre-extract every derived field. This keeps the contract
small and keeps extraction logic in one place shared by every skill.

## Derived grouping this skill computes itself

Nothing upstream is required to hand back a link graph or template clusters for this
skill to function — both are cheap to derive from `HTTP_FETCH`/`RENDER` html directly,
and deriving them locally means the detectors are testable against a handful of
synthetic observations with no dependency on an unfinished crawler:

- **Link graph** — union of `extract_links()` over every fetched page's `html`,
  restricted to same-registrable-domain hrefs.
- **Template clusters** — if the store carries a top-level `template_clusters` array,
  use it. Otherwise fall back to a local URL-shape grouping: path segments that are
  purely numeric or look like a long slug/id are replaced with `*`, so
  `/blog/2024/my-post-title` and `/blog/2023/another-post` both key to `/blog/*/*`.
  This is what D-7 (`PROJECT_CONTEXT.md`) means by "finding unit is `(check_id,
  template_cluster)`, never `(check_id, url)`" — every check in this skill aggregates
  on this key before emitting a finding.

## Utility-path recognition (shared false-positive guardrail)

A path is treated as a utility path — never a discoverability defect on its own —
when its final segment structurally matches cart/search/checkout/login/account/
wishlist/admin behaviour. A query string alone is not utility evidence: it may
identify primary content, a language version, or attribution. This is a
conservative role-name fallback on generic path *verbs*, not a brand, CMS, or
vertical name, so it holds across unseen sites (`references/archetype-applicability.md`
generalization rule).

The collector now emits SITEMAP and PAGE_CLASSIFICATION observations and positive
factual PROBE spans. Unchecked sitemap entries omit status_code and are unknown.
Negative semantic answers and identity/engagement model questions are not generated.
The local Q6 price span is a deterministic sample, not proof of a user citation.
RENDER may include measured viewport dimensions, blocking overlay and paragraph
positions; absent geometry must never be described as a visual measurement.
