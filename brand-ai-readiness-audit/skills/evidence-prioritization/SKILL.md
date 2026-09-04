---
name: evidence-prioritization
description: Owns the scoring and prioritization policy for the marketplace - the single place where a finding's importance is decided. Normalizes findings from every detector into one shape, aggregates per-URL repetitions of a template-level defect into one finding with an affected-scope count, deduplicates overlapping findings across skills, assigns confidence from evidence strength, computes severity from a published matrix rather than judgement, demotes low-confidence findings to proactive suggestions, applies a distribution guard against severity inflation, and ranks the result. Fully deterministic. Use as part of a website AI-readiness audit.
license: MIT
allowed-tools: Bash, Read
---

# Evidence Prioritization

## When to use
Invoked by `audit-orchestrator` after all four detectors have returned unscored findings.

## This is a policy, not a pipeline stage
Scoring must be consistent across all four detectors. If it lived inside each of them,
four different severity philosophies would emerge. It is isolated for the same reason a
pricing policy is isolated from the four teams that quote prices.

## Inputs
Pooled unscored findings plus store metadata for scope and page importance.

## Explicitly NOT this skill's job
- Detecting anything about the site
- Creating a finding. It may only merge, demote, rank or drop.
- Fetching anything

## Procedure
1. Normalize to the finding schema.
2. Aggregate by `(check_id, template_cluster)` — never by URL.
3. Deduplicate across skills per `references/dedupe-rules.md`.
4. Assign confidence per `references/confidence-model.md`.
5. Compute severity per `references/severity-matrix.md`. `critical` is capped to the
   total-invisibility list in that file and is unreachable by modifiers.
6. Demote findings below the confidence floor into `demoted[]` (proactive suggestions).
7. Distribution guard: if more than 30% land in high+critical, re-check scope and
   importance modifiers and write a calibration log.
8. Rank.

## Scripts
Deterministic throughout — no model call is required or used:

| Script | Role | CLI |
|---|---|---|
| `scripts/normalize.py` | Normalizes severity/confidence casing, rejects unsupported findings (`references/evidence-validation.md`), drops confidence for thin-sample findings | `python normalize.py --findings <path> [--out <path>]` |
| `scripts/aggregate_dedupe.py` | Merges same-check_id findings whose affected URLs overlap (Jaccard >= 0.5) per `references/dedupe-rules.md` | `python aggregate_dedupe.py --findings <path> [--out <path>]` |
| `scripts/score.py` | Runs the full pipeline: normalize -> dedupe -> score (`references/severity-matrix.md`) -> demote (`references/confidence-model.md`) -> distribution guard -> rank -> cross-link | `python score.py --findings <path> [--out <path>]` |

## Determinism
No model calls. Given the same findings and store metadata, output is byte-identical.

## Outputs
Scored, aggregated, deduplicated, ranked findings plus `demoted[]` and a scoring trace.

## Dependencies
- `<marketplace-root>/lib/` — reads store metadata for scope and page importance only.
  Never fetches, never detects. See PROJECT_CONTEXT.md decision D-6.
- `<marketplace-root>/references/failure-taxonomy.md` — check ID registry
