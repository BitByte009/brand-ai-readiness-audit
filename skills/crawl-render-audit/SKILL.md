---
name: crawl-render-audit
description: Detects machine-access failures on a website - whether a crawler is allowed in, whether it can read the page, and whether it can pull a specific fact out. Covers robots and meta-robots permissions, robots.txt fetch faults, status codes and redirect chains, canonical conflicts, duplicate hosts, orphaned pages, raw-HTML versus rendered-DOM content gaps, render-only navigation and facts, encoding and content-type faults, title and meta uniqueness, structured-data validity and agreement with visible text, heading usability, and facts that cannot be extracted from text alone. Use as part of a website AI-readiness audit. Does not judge identity, freshness, or human experience.
license: MIT
allowed-tools: Bash Read
---

# Crawl / Render / Extract Audit

## When to use

Invoked by `audit-orchestrator` against a completed observation store.
Answers the three gates: can a machine reach it, read it, extract from it.


## Tool requirements

Read [shared runtime and safety requirements](../../references/skill-runtime.md)
before execution. Keep the full marketplace and shared library together. Commands
below run from this skill directory; use absolute input/output paths when needed.
Only the orchestrator collects remotely; other skills read local evidence. Do not
repeat stages already run by the orchestrator. Local `--out` files may be overwritten.

## Inputs

Path to the immutable observation store (`--store path/to/store.json`). Performs no
fetching of its own. The exact observation shapes each detector reads are in
[references/store-contract.md](references/store-contract.md).

## Scripts

Each script is deterministic. Supplied probe/classification observations are optional
inputs; the current collector does not supply external model/search results. Never
make fresh model or network calls from this detector:

| Script | Checks | CLI |
|---|---|---|
| [scripts/detect_crawl.py](scripts/detect_crawl.py) | D-CRAWL-01..15 (reachability) | `python scripts/detect_crawl.py --store <path> [--out <path>]` |
| [scripts/detect_render.py](scripts/detect_render.py) | D-RENDER-01..05 (readability) | `python scripts/detect_render.py --store <path> [--out <path>]` |
| [scripts/detect_extract.py](scripts/detect_extract.py) | D-EXTRACT-01..07, 09 as findings; D-EXTRACT-08 as `proactive_opportunities()` only | `python scripts/detect_extract.py --store <path> [--out <path>] [--include-proactive]` |

[scripts/_util.py](scripts/_util.py) is shared, not a public entrypoint: observation-store accessors,
the utility-path test, and the local template-cluster fallback used when the store
carries no `template_clusters`.

## Explicitly NOT this skill's job

- Whether the extracted identity is correct or ambiguous -> `entity-semantic-audit`
- Whether a date is stale or a claim unsupported -> `trust-freshness-audit`
- Whether a human arriving cold can orient -> `engagement-audit`
- A wall blocking the *fetch* is D-CRAWL-09; a wall blocking the *reader* after a
  successful fetch is E-ANSWER-02 and belongs to `engagement-audit`
- Assigning final severity

## Procedure

Run [crawl checks](references/crawl-checks.md), [render checks](references/render-checks.md)
and [extraction checks](references/extract-checks.md) in ID order. For every check, evaluate the
applicability precondition first; if it fails, the check does not fire and is not a pass.

## Evidence rules

Every finding cites observation IDs and separates observation from interpretation.
Raw-vs-rendered findings must quote text present in one lens and absent in the other.

## False-positive rules

See [references/fp-guardrails.md](references/fp-guardrails.md). Normal JavaScript use, missing structured data on
its own, short pages, and legitimately disallowed utility paths are never findings.

## Outputs

Unscored findings: `check_id, category, title, severity, confidence, mechanism,
impact, observed_signal, evidence, observation_ids, source_urls, affected, suggested_action`
— a proposed base severity and bound evidence, never a final `id` or final severity
(`evidence-prioritization`'s job). One finding per `(check_id, template_cluster)`,
never per URL — `affected` carries `{count, sample_urls, total_in_scope}`.

## Dependencies

- [../../lib/](../../lib/) — shared instrumentation. This skill reads the observation
  store; it never fetches. See [project context](../../PROJECT_CONTEXT.md) decision D-6.
- [../../references/failure-taxonomy.md](../../references/failure-taxonomy.md) — check ID registry

## Tests

[../../tests/test_crawl_render_audit.py](../../tests/test_crawl_render_audit.py) — synthetic observation stores,
no network. Covers each check's fire/suppress pair, evidence-ID binding, report-schema
conformance, and a clean-site zero-findings regression. Run from the marketplace root:
`python -m pytest tests/test_crawl_render_audit.py`.


Shared output semantics: [finding contract](../../references/finding-contract.md).
