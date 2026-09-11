---
name: entity-semantic-audit
description: Detects entity-identity failures that stop AI systems describing a brand correctly or distinguishing it from similarly named things. Checks whether a canonical name, entity type, primary offering, operating scope and location are stated explicitly in machine-readable text rather than implied; whether naming and descriptions stay consistent across pages; whether machine-readable identity anchors exist; and whether an observed name collision is left unresolved. Applies archetype gating so documentation, institutional, editorial and personal sites are not judged as commercial brands. Use as part of a website AI-readiness audit.
license: MIT
allowed-tools: Bash Read
---

# Entity / Semantic Audit

## When to use

Invoked by `audit-orchestrator` against a completed observation store.
Answers one question: can a machine tell who this is, unambiguously.

## Tool requirements

Read [shared runtime and safety requirements](../../references/skill-runtime.md)
before execution. Keep the full marketplace and shared library together. Commands
below run from this skill directory; use absolute input/output paths when needed.
Only the orchestrator collects remotely; other skills read local evidence. Do not
repeat stages already run by the orchestrator. Local `--out` files may be overwritten.

## Inputs

Observation store, including probe results for identity questions and the detected
site archetype. Performs no fetching of its own. Exact observation shapes:
[references/store-contract.md](references/store-contract.md).

## Scripts

Deterministic extraction first; the `PROBE` identity questions (Q2/Q3/Q4,
[references/probe-questions.md](references/probe-questions.md)) are consulted only when a field has zero
deterministic candidates:

| Script | Role | CLI |
|---|---|---|
| [scripts/build_entity_profile.py](scripts/build_entity_profile.py) | Builds the entity fact table ([references/entity-profile-contract.md](references/entity-profile-contract.md)) | `python scripts/build_entity_profile.py --store <path> [--out <path>]` |
| [scripts/detect_entity.py](scripts/detect_entity.py) | D-ENTITY-01..06 over the profile | `python scripts/detect_entity.py --store <path> [--profile <path>] [--out <path>]` |

[scripts/_entity_util.py](scripts/_entity_util.py) is shared, not a public entrypoint (named distinctly
from other skills' own `_util.py` helpers so both can be imported in the same
test session without a module-name collision). If `--profile` is omitted,
`detect_entity.py` builds one itself from `--store`.

## Explicitly NOT this skill's job

- Malformed structured data -> `crawl-render-audit` (this skill reads schema for
  identity content only)
- Staleness or corroboration -> `trust-freshness-audit`
- Boundary with trust: this skill owns **who** (name, type, offering, address).
  Trust owns **what is asserted and when** (price, statistic, date, availability).
- Whether a visitor can tell what site they are on -> `engagement-audit`

## Procedure

1. Read the archetype and its implemented exceptions in [../../references/archetype-applicability.md](../../references/archetype-applicability.md).
2. Build the entity fact table with per-page, per-field provenance.
3. Run [references/entity-checks.md](references/entity-checks.md) in ID order, applicability precondition first.

## Evidence rules

Every consistency finding quotes both conflicting strings with both source URLs.
A collision may only be asserted if it was actually observed, never inferred from a
name "sounding generic."

> **Capability note.** D-ENTITY-03 (unresolved name collision) needs an outbound
> corroboration search, which is not wired into this environment. It is reported as an
> `UNAVAILABLE_INSTRUMENT` coverage entry rather than evaluated; silence from it is not a
> pass. The other D-ENTITY checks run from the ordinary collection pass.

## Outputs

Unscored findings built with the common finding contract ([../../lib/common/findings.py](../../lib/common/findings.py)
— `check_id, category, title, severity, confidence, mechanism, impact,
observed_signal, evidence, observation_ids, source_urls, affected,
suggested_action`), plus `entity_profile` passed to `engagement-audit`.
The optional trust corroboration recorder can also consume it; the current trust
detector and proactive layer do not receive that artifact. A proposed base severity and bound
evidence only — never a final `id` or final severity.

## Governing principle

Absence alone is never a finding. Every check first establishes the missing fact
is one this archetype/situation actually needs — via an archetype gate, a
compound trigger with a sibling check, or a requirement that a real corroboration
record exists — before it fires. See [references/fp-guardrails.md](references/fp-guardrails.md).

## Dependencies

- [../../lib/](../../lib/) — shared instrumentation, including the common finding
  contract ([../../lib/common/findings.py](../../lib/common/findings.py)). This skill reads the observation store; it
  never fetches. See [project context](../../PROJECT_CONTEXT.md) decision D-6.
- [../../references/failure-taxonomy.md](../../references/failure-taxonomy.md) — check ID registry
- [../../references/archetype-applicability.md](../../references/archetype-applicability.md) — check gating by site archetype

## Tests

[../../tests/test_entity_semantic_audit.py](../../tests/test_entity_semantic_audit.py) — unit tests per check,
an integration test running `build_entity_profile.py` -> `detect_entity.py`
end-to-end on synthetic multi-page stores, and regression tests (clean/unambiguous
site, and archetype-suppressed sites, both yield zero findings). No network. Run
from the marketplace root: `python -m pytest tests/test_entity_semantic_audit.py`.

Shared output semantics: [finding contract](../../references/finding-contract.md).
