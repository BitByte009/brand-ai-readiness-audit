# brand-ai-readiness-audit

An Agent Skill Marketplace that audits a public website for two things: whether AI
systems can reach, read, understand, trust and cite it, and whether visitors who arrive
from an AI answer can orient, get what they came for, and continue.

Read-only. The marketplace audits and reports. No skill in it ever modifies a live site.

> **Status: feature-complete, pending fixture-corpus validation.** All four
> audit skills — `crawl-render-audit` (D-CRAWL/D-RENDER/D-EXTRACT, 29
> checks), `entity-semantic-audit` (D-ENTITY, 6 checks), `trust-freshness-audit`
> (D-TRUST, 6 checks), and `engagement-audit` (E-ORIENT/E-ANSWER/E-CONTINUE, 11
> checks) — are fully implemented and tested against synthetic observation
> stores. `evidence-prioritization` (normalize, reject, dedupe, five-factor
> severity scoring, distribution guard, rank) and `lib/site_observer`
> (robots.txt-first single-pass collection: raw crawl, optional render
> sampling, archetype classification, an honestly-unavailable corroboration
> seam) are also fully implemented. `audit-orchestrator` — the marketplace's
> one entrypoint — composes all of the above end to end: one collection
> pass, the four detectors (each isolated so one skill's failure degrades to
> a coverage gap rather than ending the audit), scoring, evidence-binding
> validation, the proactive layer, and schema-enforced emission, always
> producing a valid report even in degraded mode (unreachable host,
> disallow-all robots.txt, budget exhaustion). 290 tests pass across the
> marketplace. The fixture corpus (19 sites, 18 named site-condition
> categories) and `tests/harness/run_corpus.py` are complete and green: 27
> expected findings, 27 actual, 0 false positives, 0 false negatives, 34/34
> on evidence/recommendation/severity quality. The corpus run itself found
> and fixed two real defects the unit tests could not catch (a two-function
> orchestrator wiring gap, and an extension-blind template-clustering bug);
> see `PROJECT_CONTEXT.md`'s Day 7 entry for what was fixed and what was
> deliberately left open. Not yet done: the CORROBORATION instrument behind
> D-ENTITY-03/D-TRUST-05, blocked on an open model/search-integration
> decision (OQ-3) — a documented gap, never silently papered over. This
> README describes what the
> marketplace *is built to do* and will be corrected before submission if
> anything ships unimplemented — it must never claim a capability the code
> does not have.

## Design philosophy

    OBSERVATION -> EVIDENCE -> MECHANISM -> IMPACT -> FIX -> VALIDATION

Deterministic scripts observe. The model interprets, diagnoses and recommends. The
model is never the source of a fact about the site.

## Architecture

    URL
     -> audit-orchestrator        scope, capabilities, budget
     -> lib/site_observer         ONE collection pass -> immutable observation store
     -> four detectors            read the same store, in parallel, never re-fetch
     -> evidence-prioritization   normalize, aggregate, dedupe, score, rank
     -> audit-orchestrator        bind-validate, schema-enforce, proactive layer, emit

## The skills

| Skill | The one question it answers |
|---|---|
| **audit-orchestrator** (entrypoint) | Lifecycle. Owns no checks and assigns no severity. |
| **crawl-render-audit** | Can a machine reach this page, read it, and pull a fact out of it? |
| **entity-semantic-audit** | Can a machine tell who this is, unambiguously? |
| **trust-freshness-audit** | Would a machine believe this claim and repeat it? |
| **engagement-audit** | Can a cold, deep-linked visitor orient, get the answer, and continue? |
| **evidence-prioritization** | How important is each finding, consistently across all detectors? |

The skills partition the *question space*, not the artifact space. Three skills read the
same JSON-LD blob; what never overlaps is the question they ask of it. Each SKILL.md
states its boundaries against its siblings explicitly.

## How the entrypoint composes them

The orchestrator drives one observation pass, then invokes the four detectors as pure
functions over an immutable store. They return unscored findings. `evidence-prioritization`
applies one scoring policy across all of them. The orchestrator then validates that every
finding's evidence resolves to a real observation, enforces the report schema, and emits a
single report.

## Evidence-first

Every finding cites observation IDs. The orchestrator drops any finding whose IDs do not
resolve in the store. Fabricated evidence is structurally impossible, not merely discouraged.

Three related commitments:
- **A check that could not run never looks like a check that passed.** Unrunnable checks go
  in a `coverage` block with a reason code, never into findings.
- **Corroboration is never claimed unless it was performed.** The finding class cannot be
  emitted without a real corroboration record.
- **Absence is not a defect.** Every check declares when it should stay silent before it
  declares how it fires.

## Safety

GET/HEAD only. One honest self-identifying user-agent, no spoofing. robots.txt parsed
before anything else is fetched, disallowed paths never requested, crawl-delay honoured.
Concurrency capped, backoff on 429/503, global request cap. No credentials, no
authenticated areas, no form submission. Writes only to a sandboxed working directory.

## Usage

    python skills/audit-orchestrator/scripts/run_audit.py --url https://example.com

Outputs `report.json` (schema at `schemas/report.schema.json`) and `report.md`.
A schema-valid report is emitted under every failure mode, including unreachable hosts
and total robots disallow.

## Validation

    python tests/validate_marketplace.py     # manifest, entrypoint, frontmatter, schemas, size
    python tests/harness/run_corpus.py       # adversarial fixture corpus, FP/FN rates

## Path convention

`<marketplace-root>/` prefixes any path resolved from the marketplace root rather than
from the file citing it. Unprefixed relative paths resolve from the citing file's own folder.

## Layout

    marketplace.json          manifest; exactly one entrypoint
    schemas/                  report + observation schemas
    references/               shared: failure taxonomy, archetype applicability matrix
    lib/                      instrumentation (collection, probe, classification) - not a skill
    skills/                   six skills, each with SKILL.md + scripts/ + references/
    tests/                    marketplace validator and fixture corpus harness
    LICENSE                   MIT, matching the license field in every SKILL.md

## License
MIT
