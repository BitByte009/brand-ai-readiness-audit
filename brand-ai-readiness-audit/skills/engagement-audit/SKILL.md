---
name: engagement-audit
description: Detects on-site engagement failures for visitors who arrive cold from an AI answer, deep-linked with no homepage context and no session. Checks whether a deep page identifies the site it belongs to on arrival, whether path context exists, whether the fact an assistant could cite is actually locatable on the landing screen, whether interstitials or gates block the content that was cited, whether the page delivers what its title promised, and whether the visitor has a relevant next step rather than a dead end. Judged on structural and positional measurements only, never on visual design or aesthetics. Use as part of a website AI-readiness audit.
license: MIT
allowed-tools: Bash, Read
---

# Engagement Audit (AI-referred arrival)

## When to use
Invoked by `audit-orchestrator` against a completed observation store.
The only skill that audits the human lens: what a person receives after a machine
sent them there.

## Inputs
Observation store (rendered lens, first-paint geometry, answer positions) plus
`entity_profile` for brand tokens. Performs no fetching of its own. Exact
observation shapes: `references/store-contract.md`.

## Scripts
| Script | Role | CLI |
|---|---|---|
| `scripts/detect_engagement.py` | E-ORIENT/E-ANSWER/E-CONTINUE (11 checks) | `python detect_engagement.py --store <path> [--entity-profile <path>] [--out <path>]` |

`scripts/_engagement_util.py` is shared, not a public entrypoint.
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
1. Load the cold-arrival persona in `references/ai-referral-persona.md`.
2. For each sampled deep page, evaluate `references/engagement-checks.md` in ID order.

## Evidence rules
Positional findings cite measured values (DOM order index, scroll depth percentage,
overlay coverage). LLM-judged findings must quote both strings compared and are
capped at medium confidence and medium severity.

## Outputs
Unscored findings built with the common finding contract (`lib/common/findings.py`
— `check_id, category, title, severity, confidence, mechanism, impact,
observed_signal, evidence, observation_ids, source_urls, affected,
suggested_action`). A proposed base severity and bound evidence only — never a
final `id` or final severity.

## Governing principle
No finding may rest on aesthetics, brevity, or a missing call-to-action where
none is appropriate. A page is never flagged merely for being short, having few
buttons, or looking visually simple — every check requires a positional or
structural measurement, and E-CONTINUE-05 (viewport/overflow) was cut from the
taxonomy for exactly this reason. See `references/fp-guardrails.md`.

## Dependencies
- `<marketplace-root>/lib/` — shared instrumentation, including the common finding
  contract (`lib/common/findings.py`). This skill reads the observation store; it
  never fetches. See PROJECT_CONTEXT.md decision D-6.
- `<marketplace-root>/references/failure-taxonomy.md` — check ID registry
- `<marketplace-root>/references/archetype-applicability.md` — check gating by site archetype

## Tests
`<marketplace-root>/tests/test_engagement_audit.py` — unit tests per check
covering both good and bad engagement patterns, edge cases (flat sites, terminal
pages, missing renders), and regression tests. No network. Run from the
marketplace root: `python -m pytest tests/test_engagement_audit.py`.
