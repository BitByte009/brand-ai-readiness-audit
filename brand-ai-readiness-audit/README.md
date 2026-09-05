# brand-ai-readiness-audit

An Agent Skill Marketplace that audits a public website for two things: whether AI
systems can reach, read, understand, trust and cite it, and whether visitors who arrive
from an AI answer can orient, get what they came for, and continue.

Read-only. The marketplace audits and reports. No skill in it ever modifies a live site.

> **Status: deterministic audit prototype with known coverage gaps.** Four
> detector skills share one collection pass and evidence-prioritization pipeline.
> Tests include a 19-site synthetic browser corpus, not an unseen-site benchmark.
> Its scored check-presence results exclude documented untestable/known-missing
> cases; its evidence/action/severity checks are structural proxies, not proof
> of diagnostic correctness. External corroboration remains unavailable.
> See [REDTEAM_FIXES.md](REDTEAM_FIXES.md) for fixes, regression tests, and
> remaining safety, accuracy, schema, and packaging limitations.

## Design philosophy

    OBSERVATION -> EVIDENCE -> MECHANISM -> IMPACT -> FIX -> VALIDATION

The current implementation observes, detects and recommends deterministically.
Future model instruments must not invent facts about the site; no model/search
integration is currently wired into the audit.

## Architecture

    URL
     -> audit-orchestrator        scope, capabilities, budget
     -> lib/site_observer         ONE collection pass -> immutable observation store
     -> four detectors            read the same store sequentially, never re-fetch
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

Every finding cites observation IDs. The orchestrator drops findings whose IDs do not
resolve in the store. ID resolution establishes provenance, not whether an observation
actually supports the detector's interpretation.

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

    python skills/audit-orchestrator/scripts/run_audit.py https://example.com

Outputs `report.json` (schema at `schemas/report.schema.json`) and `report.md`.
Expected collection failures are represented as coverage gaps. Unexpected lifecycle
exceptions can still abort report emission; do not rely on an always-valid-report guarantee.

The network policy permits credential-free, same-origin GET/HEAD requests only,
with per-path robots checks, a shared 200-request safety cap, pacing, and no retries
after HTTP 429/503. Raw redirects are checked hop by hop. Robots redirects and
browser redirects are conservatively blocked; blocked browser resources invalidate
the rendered lens and appear as coverage gaps. This can reduce coverage on sites
using CDNs or alternate canonical origins. Playwright is optional (version 1.48+
for WebSocket interception); no browser means explicit renderer-unavailable coverage.
HTTP sockets are pinned to validated public addresses; private and mixed public/private
DNS answers are rejected. Browser fetches cannot forward cookies or site-provided
headers. Active background requests, forms, secondary navigation, workers and WebRTC
are restricted. The sandboxed rendered lens runs only on successful sampled pages.
HTTP bodies are capped at 2 MiB, robots policy at 512 KiB; compressed responses are
conservatively excluded. Limits produce missing coverage, never proof of a site defect.
Use an unprivileged host sandbox with no secrets and explicit process/CPU/memory limits:
the CLI does not create that OS boundary or impose a hard whole-process deadline.
Do not parallelize independent audits against the same origin to bypass per-run pacing.
Full scope, residual risks, and adversarial tests: [SAFETY_AUDIT.md](SAFETY_AUDIT.md).

## Validation

Runtime measurements, optimizations and remaining worst-case risks are documented
in [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md).

    python tests/validate_marketplace.py     # manifest, entrypoint, frontmatter, schemas, size
    python tests/harness/run_corpus.py       # adversarial fixture corpus, FP/FN rates

Install `requirements-dev.txt` for validation/tests. If the official `skills-ref`
tool is installed, use `python tests/validate_marketplace.py --official` to run
both validators; this flag fails rather than silently skipping a missing tool.
The pinned installation command is in `requirements-dev.txt`. The six-skill audit,
fixes and validation scope are recorded in [SKILLS_COMPLIANCE.md](SKILLS_COMPLIANCE.md).

## Path convention

SKILL.md resource links are relative to the skill root; its CLI examples run from
that directory. Supporting Markdown links resolve relative to their containing
file. Older design notes use `<marketplace-root>/` to denote the package root.

## Layout

    marketplace.json          manifest; exactly one entrypoint
    schemas/                  report + observation + project marketplace schemas
    references/               shared: failure taxonomy, archetype applicability matrix
    lib/                      instrumentation (collection, probe, classification) - not a skill
    skills/                   six skills, each with SKILL.md + scripts/ + references/
    tests/                    marketplace validator and fixture corpus harness
    LICENSE                   MIT, matching the license field in every SKILL.md

## License
MIT
