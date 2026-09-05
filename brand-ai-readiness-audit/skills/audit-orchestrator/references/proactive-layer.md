# Proactive opportunities

Required by the brief: suggestions may go beyond detected problems. Generated from
*gaps*, not defects, which is what makes them non-obvious.

Sources:
1. Questions the probe was never able to ask because the site never addresses the fact.
2. Identity anchors the site does not occupy (no sameAs, no authoritative profiles).
3. Corroboration surface the entity does not occupy.
4. Findings demoted below the confidence floor by `evidence-prioritization`.
5. The proactive-only list in `<marketplace-root>/references/failure-taxonomy.md`.
6. Questions the page answers well in prose but does not mark up as answers.
7. Substantive sections a citation cannot address individually.

Rules: each opportunity states expected mechanism and effect, is never phrased as a
defect, is never counted in severity totals, and is never generic ("blog more",
"add FAQs"). It must name the specific fact, page or anchor.

## FINDING vs OPPORTUNITY

The two are not degrees of the same thing, and the report must never blur them:

| | FINDING | OPPORTUNITY |
|---|---|---|
| Claim | something is wrong or missing | the observed state is healthy |
| Trigger | evidence of a defect | evidence of *health* to build on |
| Counted in severity totals | yes | never |
| Carries a severity | yes | no — it carries a confidence |

Every source below therefore requires positive evidence of health as a
precondition. That is what structurally prevents an opportunity from being a
demoted defect in softer wording, and what makes "no opportunities" a correct
answer rather than a failure.

## Current implementation status (`scripts/proactive.py`)

Implemented, all computable from the single collection pass with no extra
fetch, no model call and no new dependency:

| Source | Fires when | Health precondition | Confidence |
|---|---|---|---|
| 2. identity anchors (`identity_anchor_gap`) | Organization/Person JSON-LD carries no `sameAs` | the markup parses and identifies the entity | high |
| 4. demoted findings (`demoted_finding`) | evidence-prioritization demoted a finding | — (already evidence-bound upstream) | low |
| 6. answered questions, unmarked (`answer_markup_gap`) | >=3 question-shaped headings each followed by >=25 words of answer prose, and no FAQPage/QAPage markup | the page already answers its own questions in readable prose | high at >=5 questions, else medium |
| 7. citable sections, unanchored (`section_anchor_gap`) | >=4 sections of >=40 words each and *no* heading carries an `id` | the page is long-form and properly sectioned | medium |

Sources 6 and 7 exist because a healthy site should still get useful output.
Both are disjoint from the checks that could otherwise cover the same ground:
`D-EXTRACT-03` fires only when a fact is *unextractable* in prose, whereas
source 6 requires the prose to answer the question; `E-ORIENT-04` fires on
fragment links whose target id is missing, whereas source 7 fires only where
no such links exist to break.

Thresholds are floors on observed health, not on defect severity. Below them
the page has not demonstrated the thing the opportunity would build on, so
nothing is offered — a missed opportunity costs nothing, a forced one is
exactly the generic advice the brief rules out.

Not implemented: sources 1 and 3 (both require the CORROBORATION/probe
instrument, still blocked on OQ-3 — see `lib/site_observer/probe.py`), and the
`llms.txt`/feed-API/author-expertise items in source 5 (each would need an
additional targeted fetch beyond the single collection pass this audit
performs, or a corroboration lookup). These are documented gaps, not silently
skipped — the same "coverage over fabrication" principle as `coverage-policy.md`
applies here: an opportunity source that cannot run yet produces nothing,
never a plausible-sounding guess it never actually checked.

## Emission guards

- Every opportunity is rejected before emission unless it carries a title,
  evidence, why-it-matters, a concrete action, a validation step, a valid
  confidence, and at least one observation ID or source URL (`_is_grounded`).
- Opportunities are deduplicated on (source, title, scope), so one page seen
  through both the raw and rendered lens yields one entry.
- A page that already carries a `D-EXTRACT` finding is suppressed: it has a
  defect to fix first, and an enhancement beside it would read as noise.
- At most three pages per source appear; the evidence states the true count.
