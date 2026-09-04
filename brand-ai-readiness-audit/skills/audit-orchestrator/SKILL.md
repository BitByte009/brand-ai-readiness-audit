---
name: audit-orchestrator
description: Entrypoint for the brand-ai-readiness-audit marketplace. Takes a URL, establishes audit scope and budget, drives a single site-observation pass, invokes the four detector skills and the scoring skill, validates that every finding's evidence resolves to a real observation, enforces the report schema, and emits one audit report of findings plus prioritized suggested actions. Use when asked to audit a website for AI discoverability (whether AI assistants can reach, read, extract, trust and cite it) or on-site engagement (whether visitors arriving from AI answers can orient, get their answer, and continue). Read-only; never modifies the audited site.
license: MIT
allowed-tools: Bash, Read, Write
---

# Audit Orchestrator (entrypoint)

## When to use
Invoked with a single URL or domain. This is the only skill in the marketplace that
should be called directly. It composes the others; they are not standalone entrypoints.

## Inputs
- `url` (required)
- `options` (optional): page budget, render on/off, corroboration on/off

## Responsibility
Lifecycle only. Scope, capability detection, budget, invocation, evidence-binding
validation, schema enforcement, proactive layer, emission.

## Explicitly NOT this skill's job
- Detecting any site defect. All check logic lives in the four detector skills.
- Scoring. Severity, confidence, aggregation and ranking belong to
  `evidence-prioritization`. This skill never assigns a severity.

## Procedure
1. Resolve target; record requested vs audited host if redirected.
2. Detect runtime capabilities (renderer, outbound search). Record in the capability matrix.
3. Fetch and parse `robots.txt`. If disallow-all or unreachable, enter degraded mode.
4. Drive `<marketplace-root>/lib/site_observer` for exactly one collection pass into an immutable store.
5. Invoke `crawl-render-audit`, `entity-semantic-audit`, `trust-freshness-audit`,
   `engagement-audit`. Each returns unscored findings.
6. Invoke `evidence-prioritization` over the pooled findings.
7. Validate every finding's `evidence.observation_ids` against the store. Drop unresolvable ones.
8. Generate proactive opportunities from gaps, not defects.
9. Validate against `<marketplace-root>/schemas/report.schema.json`. Emit `report.json` and `report.md`.

## Evidence rules
A finding survives only if every observation ID it cites resolves in the store.
This is enforced mechanically, not by instruction.

## Outputs
`report.json` (schema-valid, always emitted, including in degraded mode) and `report.md`.

## Scripts
| Script | Role | CLI |
|---|---|---|
| `scripts/run_audit.py` | The entrypoint. `run_audit(url, options)` drives the full lifecycle; `main()` is the CLI wrapper that writes `report.json`/`report.md`. | `python run_audit.py <url> [--out-dir DIR] [--max-pages N]` |
| `scripts/validate_report.py` | Evidence-binding validation (`bind_evidence`) and final schema enforcement (`validate_final_report`). | `python validate_report.py --findings <path> --store <path> [--out <path>]` |
| `scripts/proactive.py` | Generates `proactive_opportunities[]` from gaps per `references/proactive-layer.md`. | (library only, no CLI) |
| `scripts/render_report.py` | Renders `report.json` to `report.md`. | `python render_report.py --report <path> [--out <path>]` |

Collection itself lives in `<marketplace-root>/lib/site_observer/` (`collect.py`
drives `crawl.py`, `render.py`, `classify.py`, `probe.py`), not in this skill's
own `scripts/` — see PROJECT_CONTEXT.md decision D-6.

## References
`references/orchestration-rules.md`, `references/coverage-policy.md`,
`references/degraded-mode.md`, `references/proactive-layer.md`

## Dependencies
- `<marketplace-root>/lib/site_observer` — the single collection pass this skill drives
- `<marketplace-root>/schemas/report.schema.json` — emission contract
- `<marketplace-root>/references/` — shared failure taxonomy and archetype matrix
- The five sibling skills listed in `marketplace.json`
