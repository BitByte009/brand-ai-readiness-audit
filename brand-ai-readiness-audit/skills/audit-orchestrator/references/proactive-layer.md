# Proactive opportunities

Required by the brief: suggestions may go beyond detected problems. Generated from
*gaps*, not defects, which is what makes them non-obvious.

Sources:
1. Questions the probe was never able to ask because the site never addresses the fact.
2. Identity anchors the site does not occupy (no sameAs, no authoritative profiles).
3. Corroboration surface the entity does not occupy.
4. Findings demoted below the confidence floor by `evidence-prioritization`.
5. The proactive-only list in `<marketplace-root>/references/failure-taxonomy.md`.

Rules: each opportunity states expected mechanism and effect, is never phrased as a
defect, is never counted in severity totals, and is never generic ("blog more",
"add FAQs"). It must name the specific fact, page or anchor.

## Current implementation status (`scripts/proactive.py`)

Implemented: source 4 (demoted findings, reframed) and the `sameAs` half of
source 2 (identity anchors), both computable from the store alone. Not yet
implemented: sources 1 and 3 (both require the CORROBORATION/probe
instrument, still blocked on OQ-3 — see `lib/site_observer/probe.py`), and
the `llms.txt`/feed-API/author-expertise items in source 5 (each would need
an additional targeted fetch beyond the single collection pass this audit
performs, or a corroboration lookup). These are documented gaps, not silently
skipped — the same "coverage over fabrication" principle as `coverage-policy.md`
applies here: an opportunity source that cannot run yet produces nothing,
never a plausible-sounding guess it never actually checked.
