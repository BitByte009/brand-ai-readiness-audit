# False-positive guardrails

Evaluated BEFORE the detection test. If the applicability precondition fails, the
check does not fire and is not recorded as a pass. Full mechanism/threshold detail
lives with each check in `trust-checks.md`; this file is the compiled
cross-reference. This is the marketplace's highest-FP-risk skill
(`PHASE1B` Part 1.4) and gets the tightest evidence rules of any detector.

## Never flag (marketplace-wide, verbatim from the design brief)
- irrelevant absence of a feature the site does not need
- normal JavaScript use
- structured data that is unnecessary for the page type
- short pages
- unusual visual design
- an LLM subjective opinion unsupported by a measurement

## This skill's two governing principles
1. **Never claim external corroboration unless it was actually checked.** D-TRUST-05
   cannot fire without a real `CLAIM_CORROBORATION` record (`corroboration-honesty.md`).
2. **Distinguish observed facts from inference.** Every finding states what was
   mechanically found (a pattern matched, a value differed, a record's contents),
   never a subjective read on whether a claim "seems" true, current, or trustworthy.

## Skill-specific suppressions

| Check ID | Suppression condition | Effect |
|---|---|---|
| D-TRUST-01 | No time-sensitive phrase match on the page | never fires |
| D-TRUST-01 | Any date signal present on the page (schema, visible, or header) | never fires |
| D-TRUST-01 | Archetype is `documentation` or `personal-portfolio` | re-thresholded down |
| D-TRUST-01 | Archetype is `publisher-editorial` | re-thresholded up |
| D-TRUST-02 | Forward-framing pattern without an extractable date, or vice versa | never fires — both required |
| D-TRUST-02 | A more recent date signal exists alongside a stale copyright year | never fires (copyright sub-trigger only) |
| D-TRUST-02 | Historical/archival page with no forward-framing language | never fires — old is not itself stale |
| D-TRUST-02 | The page's own date inventory has a date on or before the claim's extracted date | never fires — the claim was true when the page was published (a hostile review confirmed this on archival news/blog content) |
| D-TRUST-03 | Claim is price, spec, phone, or any per-product/plan/department fact | **never extracted as a comparable claim at all** — structurally out of scope, not merely suppressed (phone was removed after a hostile review found sales-vs-support lines flagged as contradictions) |
| D-TRUST-03 | Claims share no common `key` | never compared |
| D-TRUST-04 | Claim is an ordinary marketing adjective, not a falsifiable pattern | never matched |
| D-TRUST-04 | A citation exists within the fixed word window | never fires for that claim |
| D-TRUST-05 | No `CLAIM_CORROBORATION` observation, or `performed: false` | never fires — logged as a coverage gap, not a finding |
| D-TRUST-05 | A source exists but `entity_match: false` (different, confusable entity) | **never counted as corroboration** — reported as an identity-confusion signal, not conflated with "nothing found" |
| D-TRUST-05 | Source text names the entity but also disambiguates ("not affiliated", "not to be confused with", ...) | `entity_match` forced `false` regardless of other signals — a disclaimer is not corroboration |
| D-TRUST-05 (upstream) | Claim is `time_sensitive`/`dated_offer`/`dated_event`, or an already-attributed `superlative_stat` | `is_corroboration_worthy()` returns `false` — an external lookup for it would be unnecessary and is flagged as such by `corroborate.py`'s CLI |
| D-TRUST-06 | Archetype is `personal-portfolio` | never fires |
| D-TRUST-06 | Only one of {about, contact} is absent, not both | never fires (sub-trigger a) |
| D-TRUST-06 | Zero `article`-classified pages exist | never fires (sub-trigger b) — not applicable |

## Compound-trigger checks (two independent signals required)
D-TRUST-01 (time-sensitive phrase + date-signal absence), D-TRUST-02
(forward-framing pattern + a past date, independently for each sub-trigger),
D-TRUST-05 (a real corroboration record + either zero sources or all
entity-mismatched), D-TRUST-06 (both about-absence and contact-absence for
sub-trigger a; an article page existing at all for sub-trigger b).
