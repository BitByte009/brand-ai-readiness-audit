# Evidence validation — what gets rejected, and why

This is the first thing that happens to a pooled finding, before normalization
touches its content, aggregation groups it, or scoring assigns it a severity.
A finding that fails this pass is **rejected** — dropped from the run entirely,
logged with a reason, never entering `findings[]` or `demoted[]`. Rejection is
a stronger outcome than demotion: demotion means "this may be real but we're
not confident enough to assert it as a defect"; rejection means "this is not a
usable finding at all," structurally.

## Scope note: this is not evidence-ID *binding* validation

Confirming that a finding's `observation_ids` actually resolve against the
observation store is the **audit-orchestrator's** job (`PROJECT_CONTEXT.md` D-3,
`PHASE1B` Defect B: "evidence binding validation stays with the orchestrator
because it is schema enforcement, not scoring"). This skill never touches the
observation store and never fetches anything (`SKILL.md`). What it validates
here is purely **structural**: does the finding, as a self-contained object,
carry everything the rest of this pipeline needs to reason about it honestly.

## Rejection criteria

A pooled finding is rejected if any of the following is true:

| Check | Rejection reason |
|---|---|
| Not a JSON object | `"not a finding object"` |
| `check_id`, `category`, `title`, `evidence`, `mechanism`, `impact`, or `observed_signal` missing, not a string, or empty/whitespace-only | `"missing or empty required field '<field>'"` |
| `observation_ids` or `source_urls` not a list | `"'<field>' must be a list"` |
| `severity` not one of `low`/`medium`/`high`/`critical` (case-insensitive) | `"invalid severity '<value>'"` |
| `confidence` not one of `low`/`medium`/`high` (case-insensitive) | `"invalid confidence '<value>'"` |
| `affected` missing, not an object, or missing `count`/`total_in_scope` | `"missing or malformed 'affected' block"` |
| `suggested_action` missing, not an object, or missing a non-empty `summary`/`priority` | `"missing or malformed 'suggested_action' block"` |

This is deliberately the same required-field floor every detector skill's own
`lib.common.findings.make_finding()` already produces — a well-formed finding
from any of the four detectors always passes this pass. Rejection exists to
catch **unsupported or speculative findings** that skip that contract:
anything hand-assembled outside `make_finding()`, a finding from a future or
misbehaving skill, or a finding some other bug in this pipeline mutated into a
malformed shape. This is intentionally narrow — never a paraphrase judgment
about whether the finding's *content* seems believable (that is what
`confidence` already encodes, and re-judging it here would exactly be this
skill overstepping into "detecting things about the site," which is
explicitly not its job).

## Normalization applied to everything that survives

Case is normalized (`severity`/`confidence` lowercased) so a skill's minor
capitalization inconsistency doesn't itself cause a spurious rejection. The
thin-sample confidence adjustment (`confidence-model.md`) is applied here,
before aggregation, so every later stage sees the already-adjusted tier.

## Worked examples

- A finding missing `suggested_action.priority` entirely → rejected,
  `"missing or malformed 'suggested_action' block"` — this is exactly the
  "reject unsupported/speculative findings" requirement: without a priority,
  there is nothing for this skill to normalize a final priority *onto*.
- A finding with `severity: "Critical"` (capitalized) → normalized to
  `"critical"`, not rejected — a spelling/casing difference is not evidence of
  an unsupported finding.
- A finding with `severity: "urgent"` → rejected, `"invalid severity 'urgent'"`
  — not a value this pipeline's four-tier model can reason about at all.
