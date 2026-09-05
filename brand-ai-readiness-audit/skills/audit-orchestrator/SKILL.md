---
name: audit-orchestrator
description: Entrypoint for the brand-ai-readiness-audit marketplace. Takes a URL, establishes audit scope and budget, drives a single site-observation pass, invokes the four detector skills and the scoring skill, validates that every finding's evidence resolves to a real observation, enforces the report schema, and emits one audit report of findings plus prioritized suggested actions. Use when asked to audit a website for AI discoverability (whether AI assistants can reach, read, extract, trust and cite it) or on-site engagement (whether visitors arriving from AI answers can orient, get their answer, and continue). Read-only; never modifies the audited site.
license: MIT
allowed-tools: Bash Read Write
---

# Audit Orchestrator (entrypoint)

## When to use

Invoked with a single URL or domain. This is the only skill in the marketplace that
should be called directly. It composes the others; they are not standalone entrypoints.


## Tool requirements

Read [shared runtime and safety requirements](../../references/skill-runtime.md)
before execution. Keep the full marketplace and shared library together. Commands
below run from this skill directory; use absolute input/output paths when needed.
Only the orchestrator collects remotely; other skills read local evidence. Do not
repeat stages already run by the orchestrator. Local `--out` files may be overwritten.

## Inputs

- `url` (required)
- Optional CLI `--max-pages N` and `--out-dir DIR`.
- The Python API also accepts `options.budget`. The CLI has no render/search toggle;
  rendering is capability-detected and external corroboration is not integrated.

## Responsibility

Lifecycle only. Scope, capability detection, budget, invocation, evidence-binding
validation, schema enforcement, proactive layer, emission.

## Explicitly NOT this skill's job

- Detecting any site defect. All check logic lives in the four detector skills.
- Scoring. Severity, confidence, aggregation and ranking belong to
  `evidence-prioritization`. This skill never assigns a severity.

## Procedure

Run `python scripts/run_audit.py <url> [--out-dir DIR] [--max-pages N]` once.
The executable performs the stages below; do not manually repeat its requests.

1. Resolve target; record requested vs audited host if redirected.
2. Detect runtime capabilities (renderer, outbound search). Record in the capability matrix.
3. Fetch robots before pages. Check each target path, including allowed deep exceptions;
   unreachable policy or excluded paths produce partial coverage, not permission to bypass.
4. Drive [../../lib/site_observer](../../lib/site_observer) for exactly one collection pass into an immutable store.
5. Invoke `crawl-render-audit`, `entity-semantic-audit`, `trust-freshness-audit`,
   `engagement-audit`. Each returns unscored findings.
6. Invoke `evidence-prioritization` over the pooled findings.
7. Bind top-level `observation_ids` against the store, or known `source_urls` for
   absence findings with no IDs. Drop unresolvable evidence anchors.
8. Generate proactive opportunities from gaps, not defects.
9. Validate against [../../schemas/report.schema.json](../../schemas/report.schema.json) and emit `report.json` and `report.md`.
10. Inspect `run.schema_valid`, `run.skill_failures` and coverage. Exit zero alone
    does not prove a complete or valid audit; report unexpected emission failures.

## Evidence rules

Every cited observation ID must resolve. Absence findings without IDs instead
require known source URLs. Resolution establishes provenance, not interpretation accuracy.

## Outputs

`report.json` and `report.md` in the selected output directory. Expected partial
runs carry coverage entries. Unexpected lifecycle errors can still prevent emission;
do not claim a schema-valid report when `run.schema_valid` is false.

## Scripts

| Script | Role | CLI |
|---|---|---|
| [scripts/run_audit.py](scripts/run_audit.py) | The entrypoint. `run_audit(url, options)` drives the full lifecycle; `main()` is the CLI wrapper that writes `report.json`/`report.md`. | `python scripts/run_audit.py <url> [--out-dir DIR] [--max-pages N]` |
| [scripts/validate_report.py](scripts/validate_report.py) | Evidence-binding CLI (`bind_evidence`); `validate_final_report(report)` is a Python API, not the CLI. | `python scripts/validate_report.py --findings <path> --store <path> [--out <path>]` |
| [scripts/proactive.py](scripts/proactive.py) | Generates `proactive_opportunities[]` from gaps per [references/proactive-layer.md](references/proactive-layer.md). | (library only, no CLI) |
| [scripts/render_report.py](scripts/render_report.py) | Renders `report.json` to `report.md`. | `python scripts/render_report.py --report <path> [--out <path>]` |

Collection itself lives in [../../lib/site_observer/](../../lib/site_observer/) (`collect.py`
drives `crawl.py`, `render.py`, `classify.py`, `probe.py`), not in this skill's
own `scripts/` — see [project context](../../PROJECT_CONTEXT.md) decision D-6.

## References

[references/orchestration-rules.md](references/orchestration-rules.md), [references/coverage-policy.md](references/coverage-policy.md),
[references/degraded-mode.md](references/degraded-mode.md), [references/proactive-layer.md](references/proactive-layer.md)

## Dependencies

- [../../lib/site_observer](../../lib/site_observer) — the single collection pass this skill drives
- [../../schemas/report.schema.json](../../schemas/report.schema.json) — emission contract
- [../../references/](../../references/) — shared failure taxonomy and archetype matrix
- The five sibling skills listed in [marketplace manifest](../../marketplace.json)

Composition links (invoke these through the single workflow, not as new audits):

- [Crawl/render/extract](../crawl-render-audit/SKILL.md)
- [Entity identity](../entity-semantic-audit/SKILL.md)
- [Trust/freshness](../trust-freshness-audit/SKILL.md)
- [Visitor engagement](../engagement-audit/SKILL.md)
- [Evidence prioritization](../evidence-prioritization/SKILL.md)

Shared output semantics: [finding contract](../../references/finding-contract.md).
