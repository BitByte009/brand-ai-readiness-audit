# PROJECT_CONTEXT

Living document. Updated at the end of every build day.

## Goal
An Agent Skill Marketplace that audits any public website for AI discoverability and
on-site engagement, and emits one evidence-backed, prioritized, schema-valid report.
Graded on the marketplace itself - its checks, logic and composition - not on any single
report it produces.

## Hard requirements (from the handout)
- One marketplace.json listing every skill, exactly one entrypoint
- Every skill folder independently agentskills.io compliant
- Report contains site, audited_at, counts-by-severity summary, findings[]
- Every finding: id, title, severity, evidence, suggested_action
- Suggested actions may go beyond detected problems (proactive)
- Recommend-only, read-only, robots.txt respected, no auth, no rate abuse
- Zip <= 50 MB, no model weights, runtime < 5 minutes
- Deterministic, portable, self-contained manifest
- README describing each skill and how the entrypoint composes them

Full traceability matrix: `PHASE1-ANALYSIS.md` sections 1.1-1.4.

## Architecture decisions
| ID | Decision |
|---|---|
| D-1 | Coverage gaps live in a `coverage` block, never in findings[] |
| D-2 | Crawl once, analyse many. Immutable observation store. |
| D-3 | Evidence binding: findings citing unresolvable observation IDs are dropped |
| D-4 | The LLM never observes, except two named instruments (probe, classify), temperature 0, inputs hashed |
| D-5 | Severity is computed from a published matrix, with a distribution guard |
| D-6 | Collection lives in lib/, invoked by the entrypoint. All five audit skills are symmetric consumers. |
| D-7 | Finding unit is (check_id, template_cluster), never (check_id, url) |
| D-8 | Site-archetype classification gates check applicability |
| D-9 | Degraded mode: a schema-valid report is emitted under every failure |
| D-10 | One honest user-agent. No UA spoofing anywhere. |

## Failure taxonomy
53 checks across 8 categories. Registry: `references/failure-taxonomy.md`.
Frozen at Day 4. Per-check 12-field definitions live in each skill's references/.

## Finding schema
`schemas/report.schema.json`. Required floor from the handout, plus check_id, category,
confidence, mechanism, impact, observed_signal, source_urls, observation_ids, affected,
related_findings, how_to_fix, validation.

## Test results
Harness: `tests/harness/run_corpus.py`. Metrics tracked: expected, actual,
FP, FN, evidence correct, recommendation correct, severity reasonable.
Day 7 (post-fix) result across all 19 fixtures: 27 expected findings, 27
actual, 0 false positives, 0 false negatives, 34/34 on evidence,
recommendation, and severity quality — see `tests/harness/results.json` and
the Day 7 status entry below for what changed since the Day 6 24/24 number.

## Known weaknesses / accepted risks
- Non-English sites: language-dependent heuristics self-disable and log coverage gaps
- Very large sites: 30-page stratified sample; confidence lowered for thin clusters
- Geo variance: we audit from one location; recorded as a caveat
- Corroboration depends on outbound search availability (see OQ-3)
- The probe and classifier are model instruments, so the pipeline is not end-to-end
  deterministic. Claimed precisely in the README, not overclaimed.

## Open questions
| ID | Question | Status |
|---|---|---|
| OQ-1 | Shared lib/ vs vendored per skill | RESOLVED: shared lib/, declared in each SKILL.md |
| OQ-2 | Headless renderer dependency | RESOLVED: optional, capability-detected, degrades gracefully |
| OQ-3 | Outbound search availability in the grading environment | **OPEN - blocks D-TRUST-05 and half of D-ENTITY-03** |
| OQ-4 | Shell access to scripts/, or model reads SKILL.md and improvises? | **OPEN - most consequential unknown** |
| OQ-5 | Round-2 material to fold into the taxonomy | OPEN |

## Status
Day 0 complete: analysis, architecture review, skeleton.
`crawl-render-audit` is fully implemented and tested: all 29 owned checks
(D-CRAWL-01..15, D-RENDER-01..05, D-EXTRACT-01..09), deterministic detection code,
and a synthetic-store test suite (`tests/test_crawl_render_audit.py`, 63 cases).
`entity-semantic-audit` is now also fully implemented and tested: all 6 owned
checks (D-ENTITY-01..06) have full 12-field definitions in
`skills/entity-semantic-audit/references/`, deterministic-first extraction (falling
back to the `PROBE` identity questions Q2/Q3/Q4 only when a field has zero
deterministic candidates) in `scripts/build_entity_profile.py` +
`scripts/detect_entity.py`, and a unit/integration/regression test suite
(`tests/test_entity_semantic_audit.py`, 28 cases). Every check enforces "absence
alone is never a finding" via an archetype gate, a compound trigger with a sibling
check, or a requirement that a real corroboration record exists.
`trust-freshness-audit` and `engagement-audit` are now also fully implemented and
tested, completing all four audit skills:
- `trust-freshness-audit`: all 6 owned checks (D-TRUST-01..06), fully deterministic
  (`scripts/build_claim_table.py` + `scripts/detect_trust.py`), plus a
  capability-detected corroboration recorder (`scripts/corroborate.py`) that never
  fetches the web itself and cross-checks identity against `entity_profile` to
  guard against corroborating a different, confusably-named entity. A hostile
  review found and fixed five real defects (archival content mislabeled stale,
  sales-vs-support phone numbers flagged as contradictions, a disclaimer
  defeating the identity-confusion guard, no selectivity on external lookups,
  and 3x redundant HTML re-parsing) — `tests/test_trust_freshness_audit.py`, 40
  cases including regression tests for each.
- `engagement-audit`: all 11 owned checks (E-ORIENT-01/03/04, E-ANSWER-01..04,
  E-CONTINUE-01..04 — E-ORIENT-02 merged into E-ANSWER-04 and E-CONTINUE-05 was
  cut, both per the taxonomy's own revision log), evaluated against the
  AI-referred cold-arrival persona, DOM-structural/positional measurement only
  (`scripts/detect_engagement.py`) — `tests/test_engagement_audit.py`, 46 cases.
New shared infrastructure: `lib/common/findings.py` (the common unscored-finding
contract, `make_finding`/`affected_block`) and `lib/common/http_client.py`'s
`elapsed_ms` (additive, for D-CRAWL-10) — used across skills without modifying
any other skill's own detection logic.
All four audit skills follow the same pattern: a skill-scoped, uniquely-named
`_util.py` (avoiding the module-name collision a full-suite run surfaced early
on), an `effective_pages()` that prefers the `RENDER` lens over raw `HTTP_FETCH`,
deterministic-first detection with a `PROBE` fallback only where a real judgment
is unavoidable, and full 12-field check references.
`evidence-prioritization` is now implemented: normalize -> reject
unsupported/speculative findings (`references/evidence-validation.md`) ->
dedupe same-check_id overlaps via Jaccard on affected URLs
(`references/dedupe-rules.md`) -> score via the five-factor model — impact
(the detecting skill's own calibrated severity, deliberately not re-derived
from a coarser table), confidence, scope, importance, urgency (ranking-only)
— per `references/severity-matrix.md`, with `critical` reachable only by the
four-check total-invisibility allowlist -> demote low-confidence findings to
`demoted[]` -> a distribution guard that recalibrates `high` findings down
when more than 30% of the report would land in high+critical -> rank ->
cross-link legitimate cross-skill co-occurrences without merging them
(`tests/test_evidence_prioritization.py`, 34 cases, including an integration
test running real crawl-render-audit and entity-semantic-audit detectors
against a synthetic store). `lib/site_observer` (collection) and
`audit-orchestrator` (the marketplace's one entrypoint) are now implemented
too: `collect()` drives robots.txt-first, single-pass, budget- and
politeness-bounded raw crawling (`crawl.py`, injectable fetch/sleep, no
network dependency of its own), optional rendering (`render.py`, already
capability-gated), a deterministic archetype heuristic in place of the
originally-envisioned LLM instrument (`classify.py`), and an honestly-unavailable
probe/corroboration seam (`probe.py`, still blocked on OQ-3). `run_audit.py`
composes one collection pass, the four detectors (each wrapped so one
skill's exception degrades to a coverage gap rather than ending the audit),
`evidence-prioritization`, evidence-binding validation (`validate_report.py` —
drops any finding whose `observation_ids` don't resolve, with a `source_urls`
fallback for the marketplace-wide "absence" finding pattern that cites no
positive observation ID), the proactive layer (`proactive.py`), and final
schema validation, always emitting a schema-shaped report even in degraded
mode. One honest, self-identifying user-agent (D-10) is now enforced at the
one shared HTTP layer (`lib/common/http_client.py`) rather than merely
documented. `tests/test_audit_orchestrator.py` (35 cases) integration-tests
the whole thing end to end against an injected, synthetic site, including
graceful skill-failure handling, evidence-binding drops, budget limits, and
both robots.txt degraded-mode paths.
Known gap, documented rather than papered over: robots.txt disallow-all
correctly crawls nothing, but `crawl-render-audit`'s own D-CRAWL-01 needs at
least one already-discovered disallowed URL to fire, which a zero-fetch crawl
structurally cannot produce — the block is communicated through `coverage`
and `scope.disallowed` instead of a fabricated finding (see
`skills/audit-orchestrator/references/degraded-mode.md`).
Day 6 complete: the fixture corpus (19 static sites under `tests/fixtures/`,
generated by `tests/harness/build_fixtures.py`) and `tests/harness/run_corpus.py`
are now real, not stubs. Full-suite result against the real pipeline: 24
findings, 0 false positives, 0 false negatives, 28/28 on evidence,
recommendation and severity quality (`tests/harness/results.json`).

**Critical bug found by this exercise, not caught by any of the 290 unit
tests, FIXED Day 7**: `run_audit.py::_invoke_detectors()` never imported or
called `detect_render.detect_render()` or `detect_extract.detect_extract()`
— only `detect_crawl.detect_crawl()` was wired in from crawl-render-audit.
All 5 D-RENDER and all 9 D-EXTRACT checks (14 of 53 taxonomy checks) were
dead code in every real audit, regardless of site content. The 63
crawl-render-audit unit tests all call `detect_render()`/`detect_extract()`
directly, so they passed despite this; only an end-to-end run through the
real entrypoint could catch it, which `invalid-structured-data` and
`js-render-gap` did (each verified the check's own logic was correct via a
direct call, then showed `run_audit()` returned nothing for the identical
fixture). Fixed with the two-line addition the corpus predicted: both
detectors are now imported and invoked in `_invoke_detectors()`. Re-verified:
290/290 unit tests still pass, and the corpus now gets real (non-empty)
findings on `invalid-structured-data`, `js-render-gap`, and `large-site`
where it previously got none.

Other confirmed defects found and root-caused via the corpus (full detail in
each fixture's `expected.json` and the corpus report):
- `lib/site_observer/crawl.py`'s seed-URL handling double-counts the
  homepage when a bare seed (`http://host:port`) is paired with an internal
  `href="/"` link (two different URL strings, one resource) — inflates every
  cross-page count-based check. Fixed at the harness level by always seeding
  with a trailing slash; a real caller could still hit this.
- `build_entity_profile.py`'s D-ENTITY-01 name-consistency threshold (70%)
  is fragile on small sites: ordinary per-page `<h1>`/title text dilutes an
  otherwise 100%-consistent brand name below threshold unless reinforced by
  a footer or repeated schema anchor.
- `_aliases_field()` dumps every non-dominant name candidate sitewide,
  unfiltered, into `entity_profile.fields.aliases`, which
  `detect_engagement.py` then searches for on E-ORIENT-01 — so a deep page's
  own distinctive title always self-matches as its own "alias" and E-ORIENT-01
  can essentially never fire on a realistically-titled page.
- D-ENTITY-04 treats any page carrying `Organization`/`LocalBusiness` JSON-LD
  as "entity-level" for description comparison, so a common real pattern
  (sitewide Organization schema + unique per-page meta descriptions, the
  latter required to avoid D-EXTRACT-02) produces a false conflict.
- `template_shape()`'s numeric-ID clustering (`^\d+$`) doesn't strip file
  extensions, so `/product/123.html`-style URLs (the most common real
  templated-URL shape) never cluster — defeating the one-finding-per-cluster
  aggregation promise for that entire URL family. **FIXED Day 7**: the
  actually load-bearing copy of this logic is
  `skills/crawl-render-audit/scripts/_util.py::cluster_key()` (which is what
  `group_by_cluster()` falls back to, since `collect.py` never populates
  `store['template_clusters']` in the declared-list shape it looks for
  first) — both it and `lib/site_observer/crawl.py::template_shape()` now
  strip a trailing extension before testing the numeric/hex/slug/UUID
  patterns and reattach it after. Re-verified on `large-site`: D-EXTRACT-02
  now correctly aggregates all 23 sampled `/product/N.html` pages into one
  finding instead of firing zero times.
- `PAGE_CLASSIFICATION` and `SITEMAP` observation types are read by several
  checks (E-CONTINUE terminal-page suppression, D-TRUST-06b bylines,
  D-CRAWL-08/13) but never produced by `lib/site_observer/collect.py`.
- `capabilities.crawl.budget_exhausted` is read by D-CRAWL-14 but never set
  by collection — D-CRAWL-14 cannot fire in any real audit.
- Real Playwright rendering introduces mojibake into non-ASCII characters
  (`©` → `�` observed directly) — a render-pipeline-induced false positive
  risk for D-EXTRACT-09 on any real site with non-ASCII content.

D-ENTITY-03, D-TRUST-05 and E-ANSWER-04 remain confirmed unreachable via the
real pipeline (PROBE/CORROBORATION are never wired, per OQ-3/D-4) — consistent
with what was already documented, now empirically reconfirmed end to end.

**Day 7: the corpus was re-run against a live external request to build an
end-to-end test suite mapped explicitly onto 18 named site-condition
categories** (strong static / JS-heavy / render-only facts / image-locked
facts / missing structured data / invalid structured data / ambiguous entity
/ stale content / conflicting content / strong-disc-weak-engage /
weak-disc-strong-engage / both-weak / both-strong / deep-page-poor-
orientation / small site / large site / unusual structure / FP-trap). All 18
already had a 1:1 fixture (the existing 19-fixture corpus plus `robots-5xx`
was already this exact suite). Two of the confirmed Day 6 defects were fixed
rather than left as documented gaps, since both had a precise, already
unit-tested root cause and low blast radius:
1. The `_invoke_detectors()` wiring gap (above) — two-line fix, 290/290 unit
   tests still pass.
2. The `cluster_key()`/`template_shape()` extension-blind clustering bug
   (above) — confirmed to be the *actually* load-bearing copy in
   `_util.py`, not just the one in `lib/site_observer/crawl.py` that the
   Day 6 note originally pointed at (both were fixed identically).

Fixing (1) alone was not sufficient for `large-site`: it surfaced (2) as
predicted in that fixture's own pre-written `expected.json`, which correctly
anticipated a real audit would need both fixes to detect the deliberately-
injected `/product/N.html` duplicate-title defect. Fixing both together made
it work end to end, confirmed by re-running the corpus.

One further, distinct gap was found and *not* fixed, since it is a scope
question rather than a bug with an obvious safe answer: `both-weak`'s
`widget.html`/`gadget.html` share an identical title, but D-EXTRACT-02 only
compares titles *within* one template cluster, and these two pages are
different templates (no shared id-shaped segment) — so a real, human-visible
duplicate-title defect goes undetected because it happens to cross a
cluster boundary. Widening the check to compare site-wide risks new false
positives (e.g. intentionally-identical print/AMP variants), so this was
left open and documented precisely in `tests/fixtures/both-weak/expected.json`
rather than patched speculatively.

Post-fix corpus result: 27 expected findings, 27 actual, 0 false positives,
0 false negatives, 34/34 on evidence/recommendation/severity quality (up
from 24/24 findings and 28/28 quality on Day 6 — the increase is real
findings the tool previously silently missed, not relaxed grading; three
fixtures' `expected.json` files were updated from `confirmed_false_negative`
to `expected_findings` specifically because the underlying code changed, not
because the bar moved).

## TODO
- [ ] Close OQ-3 and OQ-4 before Day 1 build starts
- [x] Complete archetype-applicability.md for D-ENTITY/D-TRUST/E-* (24 rows) —
      D-CRAWL/D-RENDER/D-EXTRACT's 29 checks are deliberately *not* duplicated in
      here: they're mechanism/gate checks that apply uniformly across archetypes,
      documented as such in `crawl-render-audit`'s own `store-contract.md` rather
      than as 29 near-identical "APPLIES" rows in the shared file
- [x] Expand crawl-render-audit's 29 checks to the 12-field form
- [x] Expand entity-semantic-audit's 6 checks to the 12-field form
- [x] Expand trust-freshness-audit's 6 checks to the 12-field form
- [x] Expand engagement-audit's 11 checks to the 12-field form — **all 53 taxonomy
      checks now have full references and passing tests across the four
      detector skills**
- [x] Fill severity matrix cell table and ranking key (evidence-prioritization)
- [x] Implement lib/site_observer collection (crawl, render sampling, probe,
      classify) so all four audit skills can run against a real site, not just
      fixtures — CORROBORATION/CLAIM_CORROBORATION (`probe.py`) remains an
      honestly-unavailable capability, still blocked on OQ-3
- [x] Implement evidence-prioritization (normalize, dedupe, score, rank) — **34
      tests passing, 247 total across the marketplace**
- [x] Implement the audit-orchestrator entrypoint (invoke all four detectors,
      bind-validate evidence against the store, schema-enforce, emit) to
      compose everything into one report — **35 tests passing, 290 total
      across the marketplace**
- [ ] Implement tests/validate_marketplace.py
- [x] Add LICENSE file to match the MIT declaration in frontmatter
- [x] Build fixture content (Day 6) — 19 fixtures, `tests/harness/run_corpus.py`
      implemented and run: 0 FP / 0 FN against corrected expectations, 28/28
      evidence/recommendation/severity quality; found the detect_render/
      detect_extract wiring gap plus 7 other confirmed defects (see Status)
- [x] Day 7: fixed the detect_render/detect_extract wiring gap and the
      cluster_key() extension-blind clustering bug; re-ran the full corpus:
      27/27 findings, 0 FP / 0 FN, 34/34 evidence/recommendation/severity
      quality; left the both-weak cross-cluster-duplicate-title scope
      question open and documented rather than patched speculatively (see
      Status)
