# Agent Skills compliance audit

## Result

All **six skills pass** the official reference validator and the stricter local
marketplace gate. The manifest is valid under the challenge's project schema,
has exactly one entrypoint (`audit-orchestrator`), resolves every listed skill,
and leaves no skill, owned reference or script unreachable. The six skill roles
remain distinct; no detector or useful deterministic check was removed.

Format baseline: the [official Agent Skills specification](https://agentskills.io/specification).
It defines the skill file/frontmatter and optional tool metadata, but does **not**
define this challenge's marketplace manifest or mandate our body headings. Those
additional checks are explicitly project requirements, not invented standards.

## Per-skill verification

“Pass” means the declared contract was inspected and its structural requirements
validated; it is not a claim that every detector is semantically perfect.

| Skill | SKILL.md / YAML | Name / description | Purpose | Inputs | Procedure | Outputs | Tools | References / scripts |
|---|---|---|---|---|---|---|---|---|---|
| audit-orchestrator | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| crawl-render-audit | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| entity-semantic-audit | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| trust-freshness-audit | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| engagement-audit | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |
| evidence-prioritization | Pass | Pass | Pass | Pass | Pass | Pass | Pass | Pass |

All names match both directory names and manifest IDs. Descriptions are nonempty,
within the 1,024-character limit and describe the capability and when to use it.
Each skill is below 500 lines and declares its tested environment through the
[shared runtime reference](references/skill-runtime.md). All **27 owned references**
are directly discoverable from their skill. All **21 scripts** are linked or
reachable through imports; **15 public CLIs** were exercised with `--help` from an
unrelated working directory, without relying on the repository being on PYTHONPATH.

## Fixes

| Issue | Correction | Verification |
|---|---|---|
| Comma-separated allowed-tools tokens | Space-separated tokens in all six frontmatters; removed unwired WebSearch from trust | Strict tool-field regressions and official validation |
| Implicit environment and working-directory assumptions | Shared runtime/safety requirements; full-package dependency explicit; CLI paths include scripts/ | All 15 CLI portability tests |
| Ambiguous root-relative resource references and missing composition links | Navigable skill-relative links, direct owned-reference links and five sibling links from the entrypoint | Resource existence, path containment, reachability and orphan tests |
| Incorrect command/input documentation | Corrected nonexistent CLI toggles and evidence field path; distinguished API-only schema validation from its evidence-binding CLI | CLI inspection, smoke tests and existing orchestrator tests |
| Scoring CLI omitted advertised store metadata | Added optional --store and passed it to the existing prioritization API | Regression verifies the exact loaded metadata reaches the API |
| Stale capability/consumer claims | Corrected live-search, viewport geometry, profile consumers, successful-page evidence gates, robots exceptions, cross-origin redirects and always-valid-report claims | Source/contract review; existing runtime/error-page/robots tests remain green |
| Marketplace validator was a NotImplementedError stub | Implemented an offline strict gate and a local manifest schema; optional official validation fails if unavailable rather than silently skipping | 49 compliance tests, including adversarial malformed packages |
| Copied shared mechanics | Centralized observation accessors, the crawl skill's duplicate finding builder, page-selection re-exports, title segmentation, word containment and URL depth | Function-identity regressions, full test suite and browser corpus |

The existing manifest content was already correct and was preserved. No new skill
or mandatory live-audit dependency was added. PyYAML is a development/validation
dependency; official skills-ref was installed separately in a temporary environment.

## Composition and duplication review

| Owner | Exclusive concern | Why retained separately |
|---|---|---|
| audit-orchestrator | Collection lifecycle, evidence binding and final emission | Coordinates consumers; does not own detector rules or final scoring policy |
| crawl-render-audit | Machine access, two-lens readability and extraction | Owns crawl/HTTP/render/extract checks, not identity or visitor intent |
| entity-semantic-audit | Entity identity and its provenance | Produces the profile and owns name/type/offering/location consistency |
| trust-freshness-audit | Asserted values, dates, attribution and supplied corroboration | Checks what is asserted and when, not the brand's identity |
| engagement-audit | Cold-arrival orientation, answer access and continuation | Uses the human arrival lens rather than duplicating crawl reachability |
| evidence-prioritization | Shared scoring, merging and ranking policy | Takes pooled findings as input; does not fetch or create defects |

Repeated finding-contract and runtime guidance now has shared references rather
than separate authoritative definitions. Shared pure mechanics are imported, not
copied. Small detector dispatch functions intentionally retain different check
registries. Similar utility-path functions intentionally retain different domain
rules (for example, a terminal contact page is relevant to engagement but is not
automatically a crawler-exclusion utility). Merging those would change behavior,
not merely remove duplication. Similar artifacts used by different mechanisms are
not duplicate skills; existing deduplication/cross-link tests protect that boundary.

## Validation tooling and results

Used the official [skills-ref reference implementation](https://github.com/agentskills/agentskills/tree/main/skills-ref),
package version **0.1.0**, pinned to commit
`69ef37e9424c0a7ea9dd2293b559e43ec8176379`. All six individual
`skills-ref validate skills/<name>` commands exited zero. The skill-creator
quick validator also passed all six skills; its workflow guided the narrow
instruction/resource corrections and behavioral validation.

The official reference validator checks basic frontmatter but currently does not
enforce every optional-field semantic or marketplace relationship. The local gate
adds duplicate JSON/YAML keys, optional-field types, tool-token formatting, required
project sections, unique IDs/paths, one Boolean entrypoint, safe paths, resource
reachability, script syntax/copies, valid schemas and a conservative uncompressed
50 MB package-size check. This package is approximately **2.2 MB**, including the
existing tracked artifacts; no files were deleted to pass the size gate.

Reproduce from the marketplace root after installing requirements-dev.txt:

```sh
python tests/validate_marketplace.py
python tests/validate_marketplace.py --official
python -m pytest -q -p no:cacheprovider
python tests/harness/run_corpus.py
```

The pinned official-tool installation command is documented in requirements-dev.txt.
It is optional for the offline local gate, required for --official, and is never
downloaded automatically by validation.

Final results: **438 tests passed**, including **49 compliance regressions**;
**all 19 Chromium fixtures passed**, preserving 27/27 scored check presences,
34 findings, and zero measured FP/FN or guardrail violations. No fixture expectation
was changed. `git diff --check` is clean.

This is format, packaging and declared-workflow compliance, not an official
certification of detection accuracy, security or worst-case runtime. Existing
limitations remain documented in the performance and red-team audits. External
reference links were not treated as authorization to perform new live-site audits.
