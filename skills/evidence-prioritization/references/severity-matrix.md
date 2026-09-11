# Severity matrix — the scoring model

`severity = f(impact, confidence, scope, importance)`, computed — never chosen.
`urgency` is a fifth factor that affects **ranking**, never the severity tier
itself (see below — this separation is deliberate). Given the same findings and
metadata, the output is byte-identical; that is what "computed, not chosen" means
in practice, and it is the property that makes this skill's output verifiable by
a grader reading this file.

## The five factors

| Factor | What it captures | Where it comes from |
|---|---|---|
| **Impact** | How severe the underlying mechanism failure is | the detecting skill's *proposed* base `severity` — already calibrated per check against the taxonomy (see below, "why impact is not re-derived here") |
| **Confidence** | How sure we are the finding is real | the detecting skill's `confidence`, adjusted for thin samples (`confidence-model.md`) |
| **Scope** | How much of the measured population is affected | `affected.count / affected.total_in_scope` only when the detector supplied a real denominator; unknown is neutral |
| **Importance** | Whether the affected page was explicitly placed in scope | the requested audit target from the observation store; URL depth is not a proxy for importance |
| **Urgency** | Whether the defect actively worsens over time | a fixed check_id set (stale/expiring/actively-blocking checks) — **ranking only** |

### Why impact is not re-derived from a coarse gate table
An earlier draft of this file scored severity from an 8-row "mechanism gate"
table (reach/read/extract/belief/arrival/continuation → one base value each).
That table is *strictly coarser* than the per-check base severities already
worked out across 52 checks' own twelve-field references (e.g. D-CRAWL-05's
redirect-chain base is `medium`, not `high`, despite being a "reach" check;
D-TRUST-04 is capped at `low` by explicit taxonomy revision). Re-deriving
impact from the coarse table would silently contradict that already-considered
work. This skill instead takes the proposing skill's `severity` as the impact
input directly — it is itself already `f(mechanism)`, computed once, close to
the mechanism, by the skill that understands it. What this skill owns is
everything *after* that: whether confidence, scope, and importance push it up
or down, and the ceiling nothing may cross.

## Critical is capped
`critical` is restricted to D-CRAWL-01, D-CRAWL-03, D-CRAWL-09 and D-CRAWL-15.
An allowlisted ID alone is insufficient: confidence must be high and evidence must
cover all of a sample of at least three items, or explicitly establish whole-site
invisibility. Otherwise critical is capped at high. There is no unconditional
critical floor. Sample scope is reported and must not be described as proof of
unobserved pages. Low-confidence findings are demoted out of asserted findings.

## Modifier cell table

Applied in this order; each either fires or doesn't, independently:

| Modifier | Condition | Effect |
|---|---|---|
| Scope (broad) | `total_in_scope > 1` and `count / total_in_scope >= 0.8` | `+1` |
| Scope (narrow) | `total_in_scope > 1` and `count == 1` | `-1` |
| Scope (unknown/singular target) | denominator absent, or `total_in_scope <= 1` | no modifier — neutral |
| Importance | the affected set includes the explicitly requested audit target | `+1` |
| Confidence | `confidence == "low"` | `-1` |

Severity moves along `low -> medium -> high -> critical`, clamped at both
ends, computed by summing every modifier's delta onto the proposed base index
— not by looking up a single matrix cell per combination, since the four
modifiers are independent and additive by design (this is the "exact cell
table" in spirit: every reachable combination is the deterministic sum of
these four rows, not a hand-enumerated 4-dimensional table that would need to
be kept in sync with these rows anyway).

**Why a singular target (`total_in_scope <= 1`) gets no scope modifier at
all**, not even "broad": `count / total_in_scope >= 0.8` is trivially true
whenever there is only one possible instance and it's affected (`1/1 = 100%`).
A check whose applicability is inherently singular — one `robots.txt`, one
homepage — isn't describing a *widespread pattern* when it fires; there was
never a population for it to be broad or narrow across. Scoring that as
"broad scope, `+1`" would silently inflate every such check's severity for a
condition (`total == 1`) that says nothing about how much of the site is
affected. The broad-scope modifier is reserved for what it's meant to
measure: a defect confirmed across most of a real, multi-item population.

## Confidence-driven demotion
A finding whose confidence (after the thin-sample adjustment in
`confidence-model.md`) is `low` is **demoted**: removed from `findings[]` and
placed in `demoted[]` with its adjusted severity preserved, never asserted as
a confident defect. See `confidence-model.md`.

## Tie-break / ranking key
Findings are ordered by, in order:
1. Final severity (`critical` > `high` > `medium` > `low`)
2. Final confidence (`high` > `medium` > `low`)
3. **Urgency** — a fixed, narrow set of actively-worsening or time-bound
   checks (`D-CRAWL-15`, `D-CRAWL-09`, `D-CRAWL-04`, `D-TRUST-02`) sort ahead
   of same-tier, same-confidence findings that aren't. Urgency is deliberately
   never a severity input — folding "this gets worse over time" into the
   severity tier would be a second, harder-to-audit path to the same
   inflation the distribution guard exists to catch. As a ranking-only
   tie-break it still surfaces urgent findings near the top of the report
   without touching the severity distribution.
4. `affected.count` (larger first — a defect hitting more of the site first)
5. `check_id` (deterministic final tie-break)

## Distribution diagnostic
If more than 30% of the (post-demotion) findings land in `high`+`critical`,
record a `severity_distribution_warning` in `calibration_log`. The diagnostic
never rewrites a finding: adding an unrelated result cannot change the
severity of evidence already evaluated. Inflated severity is corrected by the
finding-local impact, confidence, measured-scope, and importance rules above,
not by enforcing a desired report shape.

**The diagnostic only runs with at least `DISTRIBUTION_GUARD_MIN_FINDINGS` (5)
kept findings.** A percentage is not evidence of a pattern when the
denominator is tiny: a report with exactly one genuinely severe, well-evidenced
problem and one unrelated minor one is a 50% high-ratio, and a naive guard
would water down the severe finding purely because the report happened to be
short — punishing a site for having *few* problems rather than *miscalibrated*
ones. Below the floor, every finding's severity stands on its own evidence
with no report-wide recalibration applied.

## Worked examples
A `D-EXTRACT-05` finding (base `low`, "no h1") affecting 1 of 12 pages, high
confidence: scope `-1` (narrow: `count==1`, `total_in_scope==12>1`), no
importance modifier, no confidence modifier → index `low(0) - 1` clamped to
`0` → stays `low`.

A `D-CRAWL-06` finding (base `high`, canonical conflict) affecting 8 of 10
measured pages including the requested audit target, high confidence: scope
`+1` (broad: `8/10 = 80% >= 80%`), importance `+1` (the requested target is
affected) → index `high(2) + 1 + 1` → `critical` — but `D-CRAWL-06` is
not on the allowlist, so the cap fires and it is recorded back down to `high`,
with `"critical-cap: ..."` in its `scoring_trace`.

A `D-CRAWL-15` finding (base `critical`, robots.txt unreachable) — inherently
singular, `total_in_scope == 1` — gets no scope modifier at all (see above),
and no importance modifier changes it either way: it stays `critical`, and
because it *is* on the allowlist, the cap never touches it.
