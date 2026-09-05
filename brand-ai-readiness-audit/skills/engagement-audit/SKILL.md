---
name: engagement-audit
description: Detects on-site engagement failures for visitors who arrive cold from an AI answer, deep-linked with no homepage context and no session. Checks whether a deep page identifies the site it belongs to on arrival, whether path context exists, whether the fact an assistant could cite is actually locatable on the landing screen, whether interstitials or gates block the content that was cited, whether the page delivers what its title promised, and whether the visitor has a relevant next step rather than a dead end. Judged on structural and positional measurements only, never on visual design or aesthetics. Use as part of a website AI-readiness audit.
license: MIT
allowed-tools: Bash Read
---

# Engagement Audit (AI-referred arrival)

## When to use

Invoked by `audit-orchestrator` against a completed observation store.
The only skill that audits the human lens: what a person receives after a machine
sent them there.

## Tool requirements

Read [shared runtime and safety requirements](../../references/skill-runtime.md)
before execution. Keep the full marketplace and shared library together. Commands
below run from this skill directory; use absolute input/output paths when needed.
Only the orchestrator collects remotely; other skills read local evidence. Do not
repeat stages already run by the orchestrator. Local `--out` files may be overwritten.

## Inputs

Observation store with available raw/rendered HTML, plus optional
`entity_profile` for brand tokens. The standard collector does not measure viewport
geometry or perform engagement model calls; never invent those measurements. Performs no fetching of its own. Exact
observation shapes: [references/store-contract.md](references/store-contract.md).

## Scripts

| Script | Role | CLI |
|---|---|---|
| [scripts/detect_engagement.py](scripts/detect_engagement.py) | E-ORIENT/E-ANSWER/E-CONTINUE (11 checks) | `python scripts/detect_engagement.py --store <path> [--entity-profile <path>] [--out <path>]` |

[scripts/_engagement_util.py](scripts/_engagement_util.py) is shared, not a public entrypoint.
`--entity-profile` is optional — only `E-ORIENT-01` needs it; every other check
runs without it.

## Explicitly NOT this skill's job

- Visual design, colour, layout taste, CTA styling. **No finding in this skill may
  rest on aesthetics.** Every check requires a positional or structural measurement.
- Machine reachability of links -> `crawl-render-audit`
- Machine-facing brand identifiability -> `entity-semantic-audit`
- Page speed as a user complaint -> fetch cost is a crawler-timeout mechanism and
  belongs to `crawl-render-audit`

## Procedure

1. Load the cold-arrival persona in [references/ai-referral-persona.md](references/ai-referral-persona.md).
2. For each sampled deep page, evaluate [references/engagement-checks.md](references/engagement-checks.md) in ID order.

## Evidence rules

Use only measurements actually present in the store or derived by the scripts.
DOM position is a structural proxy, not a measured viewport or first-paint result.
Comparison findings must quote both strings; preserve the documented confidence
caps. Do not substitute raw HTML for render-dependent evidence.

> **Capability note.** E-ANSWER-04 (answer buried below the fold) needs a per-page
> extraction probe, which is not wired into this environment. It is reported as an
> `UNAVAILABLE_INSTRUMENT` coverage entry rather than evaluated; silence from it is not a
> pass. The other E-* checks run from the ordinary collection pass.

## Outputs

Unscored findings built with the common finding contract ([../../lib/common/findings.py](../../lib/common/findings.py)
— `check_id, category, title, severity, confidence, mechanism, impact,
observed_signal, evidence, observation_ids, source_urls, affected,
suggested_action`). A proposed base severity and bound evidence only — never a
final `id` or final severity.

## Governing principle

No finding may rest on aesthetics, brevity, or a missing call-to-action where
none is appropriate. A page is never flagged merely for being short, having few
buttons, or looking visually simple — every check requires a positional or
structural measurement, and E-CONTINUE-05 (viewport/overflow) was cut from the
taxonomy for exactly this reason. See [references/fp-guardrails.md](references/fp-guardrails.md).

## Dependencies

- [../../lib/](../../lib/) — shared instrumentation, including the common finding
  contract ([../../lib/common/findings.py](../../lib/common/findings.py)). This skill reads the observation store; it
  never fetches. See [project context](../../PROJECT_CONTEXT.md) decision D-6.
- [../../references/failure-taxonomy.md](../../references/failure-taxonomy.md) — check ID registry
- [../../references/archetype-applicability.md](../../references/archetype-applicability.md) — check gating by site archetype

## Tests

[../../tests/test_engagement_audit.py](../../tests/test_engagement_audit.py) — unit tests per check
covering both good and bad engagement patterns, edge cases (flat sites, terminal
pages, missing renders), and regression tests. No network. Run from the
marketplace root: `python -m pytest tests/test_engagement_audit.py`.

Probe numbering, when supplied observations need interpretation:
[canonical questions](../entity-semantic-audit/references/probe-questions.md).

Shared output semantics: [finding contract](../../references/finding-contract.md).
