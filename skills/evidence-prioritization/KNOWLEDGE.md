# evidence-prioritization — Engineering Study Guide

> Companion to `SKILL.md`. Shared vocabulary and the finding contract are in the
> root `KNOWLEDGE.md` (§6, §8). This skill is the only one with **no check IDs**.

---

## A. PURPOSE AND MENTAL MODEL

**Mental model:** think of this skill as a *pure function over findings*. It
takes the pooled, unscored output of the four detector skills and returns a
ranked, deduplicated, ID-assigned list plus three audit trails. It never looks at
a website, never re-reads HTML, and — importantly — **never needs the store** to
do its job.

```
pooled_findings ──► normalize ──► dedupe ──► score ──► demote
                       │            │         │          │
                    rejected     merge_log  trace   demoted[]
                                                       │
                                            distribution-guard
                                                       │
                                      rank ──► assign ids ──► link related
```

**The question it answers:** "Given four detectors that each proposed a base
severity in isolation, which of these are actually the same defect, which deserve
attention first, and which are not supported well enough to assert at all?"

**Why it exists as a separate skill.** Each detector proposes a base severity for
its own check in isolation. Only something with a view of *all* findings can
decide that two of them are the same defect, that one affects 90% of the site
while another affects one page, or that a `low`-confidence claim should not be
asserted at all. Putting that logic in each detector would produce four
inconsistent scoring policies.

**What it explicitly does not do** (`SKILL.md` lists these): fetching anything,
detecting anything, or inventing evidence. From the source docstring of
`prioritize_findings`: `store` is accepted "for forward compatibility … but is not
required — every factor here is self-contained on the findings themselves, which
is what keeps this skill's output reproducible from the findings alone."

**Mental model refinement:** the skill has three separable jobs, and it is worth
holding them apart — **rejection** (this finding is malformed, drop it),
**demotion** (this finding is well-formed but not confident enough to assert),
and **scoring** (this finding is real; how much does it matter?). Rejected and
demoted findings go to different places and mean different things.

---

## B. COMPLETE FILE MAP

### `scripts/normalize.py` (114 lines) — the gate
- **Purpose:** validate finding shape; split into `(normalized, rejected)`.
- **Called by:** `score.prioritize_findings` (first stage) and available as a CLI.
- **Key symbols:** `REQUIRED_STRING_FIELDS` (7), `REQUIRED_LIST_FIELDS` (2),
  `THIN_SAMPLE_FLOOR = 3`, `_rejection_reason`, `normalize_findings`.
- **Output shape:** rejected entries are `{"finding": <original>, "reason": <str>}`
  and — per the source comment — "never enter `findings[]` or `demoted[]`".

### `scripts/aggregate_dedupe.py` (139 lines) — the merger
- **Purpose:** collapse findings that describe the same defect.
- **Key symbols:** `_dedupe_key`, `_merge_group`, `merge_duplicate_findings`.
- **Output:** `(deduped, merge_log)`.

### `scripts/score.py` (309 lines) — the scorer, ranker and pipeline driver
- **Purpose:** modifiers, critical floor/ceiling, demotion, distribution guard,
  ranking, ID assignment, cross-linking, and `prioritize_findings` itself.
- **Key constants:**
  - `CRITICAL_ALLOWLIST = {D-CRAWL-01, D-CRAWL-03, D-CRAWL-09, D-CRAWL-15}`
  - `URGENT_CHECK_IDS = {D-CRAWL-15, D-CRAWL-09, D-CRAWL-04, D-TRUST-02}`
  - `DISTRIBUTION_GUARD_THRESHOLD = 0.3`, `DISTRIBUTION_GUARD_MIN_FINDINGS = 5`

### `scripts/_prioritization_util.py` (43 lines) — ordering primitives
`SEVERITY_ORDER = ["low","medium","high","critical"]` (ascending — index 3 is
critical), `CONFIDENCE_ORDER = ["low","medium","high"]`, `severity_index`,
`confidence_index`, `finding_url_set`, `affected_url_set`.

The distinction between `finding_url_set` (all cited URLs, including context) and
`affected_url_set` (only URLs in `affected.sample_urls`) is load-bearing — see §J.

### References
`evidence-validation.md` (what makes a finding admissible), `dedupe-rules.md`,
`severity-matrix.md` (the modifier cell table and the critical allowlist),
`confidence-model.md` (the demotion floor).

### Shared library
Only `lib/common/findings.py` conceptually (the contract it validates against).
It does **not** import `lib.common.observations` or `lib.common.extract` — a
useful signal that it genuinely never touches site data.

### Tests
`tests/test_evidence_prioritization.py` (687 lines) — the second-largest test
module, and the one with the densest adversarial coverage.

---

## C. END-TO-END WORKFLOW

`prioritize_findings(pooled_findings, store=None)` runs eight stages in a fixed
order. The order matters and is worth memorizing:

1. **`normalize_findings`** → `(normalized, rejected)`. Malformed findings leave
   the pipeline permanently.
2. **`merge_duplicate_findings`** → `(deduped, merge_log)`. Same-defect findings
   become one with unioned evidence.
3. **`score_finding`** per finding → adds `severity` (possibly changed) and
   `scoring_trace`.
4. **`demote_low_confidence`** → `(kept, demoted)`. `confidence == "low"` moves to
   `demoted[]`. **Note this runs *after* scoring**, so a demoted finding still
   carries its full severity reasoning — which is what makes the proactive layer
   able to reframe it usefully.
5. **`apply_distribution_guard`** → `(kept, calibration_log)`. Warns; never
   rewrites.
6. **`rank_findings`** → stable sort.
7. **`assign_ids(prefix="F")`** → `F-001`, `F-002`, … Demoted get `D-` ids.
8. **`link_related_findings`** → populates `related_findings` by URL overlap.

**Returns:** `{findings, demoted, rejected, merge_log, calibration_log}`.

```
pooled (from 4 detectors, unscored, no ids)
   │
   ├─ normalize ──────────► rejected[]      (never reaches the report's findings)
   │
   ├─ dedupe ────────────► merge_log[]      (run.merge_log)
   │
   ├─ score  (scope, confidence, importance modifiers + critical floor/ceiling)
   │
   ├─ demote ────────────► demoted[]        (report.demoted; feeds proactive)
   │
   ├─ distribution guard ► calibration_log[] (run.calibration_log)
   │
   ├─ rank → assign F-ids → link related
   ▼
findings[]  (ordered, ID'd, cross-linked)
```

**Failure behaviour.** If `prioritize_findings` raises, `run_audit._prioritize`
catches it, records a `SKILL_FAILED` coverage entry scoped to "all findings for
this audit", and returns `{"findings": [], "demoted": [], "rejected": pooled, …}`
— every finding is preserved in `rejected` rather than lost.

---

## D. INPUT CONTRACT

| Input | Type | Origin | Required | If missing / malformed |
|---|---|---|---|---|
| `pooled_findings` | `list` | the four detectors, concatenated by `_invoke_detectors` | yes | empty list ⇒ empty result, no error |
| each finding | `dict` | `lib/common/findings.make_finding` | — | **rejected** with a reason string; see the table below |
| `store` | `dict` or `None` | `collect.py` | **optional** | `_importance_modifier` returns `(0, None)`; everything else is unaffected |

**Rejection reasons** (`_rejection_reason`, evaluated in order):
1. not a dict → `"not a finding object"`
2. any of `check_id, category, title, evidence, mechanism, impact, observed_signal`
   missing/empty/non-string → `"missing or empty required field '<f>'"`
3. `observation_ids` or `source_urls` not a list → `"'<f>' must be a list"`
4. `severity` not in `SEVERITY_ORDER` → `"invalid severity '<v>'"`
5. `confidence` not in `CONFIDENCE_ORDER` → `"invalid confidence '<v>'"`
6. `affected` not a dict, or missing `count` / `total_in_scope` →
   `"missing or malformed 'affected' block"`
7. `suggested_action` not a dict or missing `summary` / `priority` →
   `"missing or malformed 'suggested_action' block"`

Note what is **not** required: `observation_ids` must be a list but may be
**empty**. That is what permits absence findings (see root KNOWLEDGE §8); the
orchestrator's `bind_evidence` applies the stricter anchor rule later.

---

## E. OUTPUT CONTRACT

| Key | Reaches the report as | Meaning |
|---|---|---|
| `findings` | `report.findings` | ranked, `F-`prefixed, cross-linked |
| `demoted` | `report.demoted` | well-formed but `low` confidence; `D-`prefixed; also feeds the proactive layer's `demoted_finding` source |
| `rejected` | `report.run.rejected_findings` | malformed; kept for debugging, never presented as defects |
| `merge_log` | `report.run.merge_log` | which findings were merged and why |
| `calibration_log` | `report.run.calibration_log` | severity-distribution warnings |

**Fields this skill adds to a finding:** `id`, `scoring_trace` (a list of human-readable
modifier notes), `related_findings`, and a possibly-changed `severity`.

**Fields it must never mutate** — stated in `score_finding`'s docstring: `title`,
`mechanism`, `impact`, `observed_signal`, `evidence`, `observation_ids`,
`source_urls`, `affected`, `suggested_action.summary/how_to_fix/validation`.
Severity may change; the evidence describing *why* may not.

**A schema consequence:** `report.schema.json` requires
`suggested_action.priority == severity` (checked in `lib/common/schema.validate_report`).
Since this skill can change `severity`, it must keep `priority` in step — and the
schema validator will fail the whole report if it does not.

---

## F. CHECK-BY-CHECK BREAKDOWN

**This skill implements no check IDs.** It is a support skill. `grep` for
`check_id="` in `skills/evidence-prioritization/` returns nothing; the only check
IDs in the source are the two policy sets, `CRITICAL_ALLOWLIST` and
`URGENT_CHECK_IDS` in `score.py`, which reference *other* skills' checks.

For completeness, the equivalent of a check-by-check table here is the modifier
cell table in §H.

---

## G. SUPPORTING FUNCTIONS AND ALGORITHMS

### `_dedupe_key(finding)` — `aggregate_dedupe.py:24`
Returns `(check_id, finding.get("dedupe_key") or finding.get("mechanism", ""))`.

**Why the mechanism fallback:** one check ID can contain genuinely different
sub-defects. The source names the real example — `D-ENTITY-04` covers *description*
conflicts and *address* conflicts, which are different defects with different
fixes. Keying on `check_id` alone would merge them into one incoherent finding.
Detectors may supply an explicit `dedupe_key`; none currently does, so the
mechanism prose is the operative key. `OVERFITTING_AUDIT.md` lists "stable
detector-supplied subtype IDs" as the appropriate next mechanism — using prose as
a key is acknowledged as a fallback, not a design goal.

### `merge_duplicate_findings(findings)` — `aggregate_dedupe.py:67`
Groups by `_dedupe_key`, then **requires overlapping affected instances** before
merging — two findings with the same key but disjoint affected sets are distinct
defects on distinct pages. Grouping joins *connected components*: A overlaps B,
B overlaps C ⇒ all three merge, even if A and C do not overlap directly.

### `_merge_group(sources)` — `aggregate_dedupe.py:34`
The field-by-field merge policy, and the function most worth reading closely:
- `observation_ids`, `source_urls`: **union**, sorted.
- `affected.sample_urls`: union of `affected_url_set`.
- `affected.count`: `max(len(affected_urls), max(declared counts))` — a **lower
  bound**, never a sum. Summing overlapping counts would inflate scope.
- `affected.total_in_scope`: max of the **measured** totals only; stays `None` if
  none was measured.
- `confidence`: highest in the group.
- All other fields come from the source with highest confidence, then largest
  `affected.count`, with **canonical JSON as the final tie-break** — so the merge
  does not depend on detector execution order. This is what makes the pipeline
  permutation-invariant.

### `_scope_modifier(finding)` — `score.py:48`
```
total = affected.total_in_scope
if total is not numeric or total <= 0:  return 0     # unknown denominator
if total <= 1:                          return 0     # singular target
ratio = count / total
if ratio >= 0.8:                        return +1
if count == 1:                          return -1
return 0
```
The `total <= 1` floor carries an explicit comment: a check whose target is
inherently singular (one `robots.txt`, one homepage) is not "broad scope" just
because its one instance is affected. Without the floor, every such finding scored
100% and silently inflated.

### `_importance_modifier(finding, store)` — `score.py:82`
`+1` only when the **explicitly requested audit target** is among the finding's
`affected_url_set` (compared via `_url_identity`, which normalizes for comparison).
Note it uses `affected_url_set`, not `finding_url_set` — a URL cited merely as
context does not promote a finding. Returns `(0, None)` when `store` is absent.

### `score_finding(finding, store)` — `score.py:101`
1. `index = severity_index(original_severity)`.
2. Apply `_scope_modifier` and `_confidence_modifier`, then `_importance_modifier`,
   accumulating notes into `trace`.
3. Clamp: `index = max(0, min(index, 3))`.
4. **Critical allowlist as both ceiling and floor:** if `check_id ∈ CRITICAL_ALLOWLIST`
   and the computed severity is not `critical`, restore it to `critical` and note
   it. Conversely nothing outside the allowlist may reach `critical`.
5. Attach `scoring_trace`.

The floor half has a stated rationale worth quoting in effect: a low-confidence
robots.txt-disallow is *still* a critical-severity finding. Confidence decides
whether it is later demoted out of `findings[]`; it must not quietly deflate the
severity label.

### `apply_distribution_guard(findings, threshold=0.3)` — `score.py:176`
If `len(findings) >= 5` and the high+critical ratio exceeds `0.3`, append a
`severity_distribution_warning` to the calibration log. **It changes nothing.**
The docstring is explicit: adding unrelated findings must never change an existing
finding's severity. This is the remains of an earlier quota rule that was removed
(§J).

### `rank_findings(findings)` — `score.py:233`
Sort key, all ascending after negation:
```
(-severity_index, -confidence_index,
 0 if check_id in URGENT_CHECK_IDS else 1,
 -affected.count,
 check_id)
```
The final `check_id` term makes the sort **total**, so ranking is deterministic
for identical inputs. `URGENT_CHECK_IDS` is ranking-only and is never a severity
input — the source comment says so explicitly.

### `link_related_findings(findings)` — `score.py:212`
Populates `related_findings` with the IDs of other findings sharing affected URLs.
The orchestrator later prunes any reference to a dropped finding
(`run_audit.py`, the `related_findings` filter after `bind_evidence`).

---

## H. ALGORITHMS AND HEURISTICS

### The modifier cell table
| Modifier | Condition | Δ | Rationale status |
|---|---|---|---|
| scope +1 | `count/total >= 0.8` with a measured total > 1 | +1 | **Chosen boundary.** `OVERFITTING_AUDIT.md` calls the 80% line "explicit calibration policy, not a universal fact" |
| scope −1 | `count == 1` with a measured total > 1 | −1 | Chosen |
| scope 0 | no measured total, or total ≤ 1 | 0 | **Principled** — refuses to infer sitewide scope from a sample |
| confidence −1 | `confidence == "low"` | −1 | Chosen |
| importance +1 | the requested audit target is affected | +1 | Principled — the operator asked about that URL |
| critical floor/ceiling | `check_id ∈ CRITICAL_ALLOWLIST` | force `critical` | Policy from `severity-matrix.md` |

Final index is clamped to `[0, 3]`.

### The confidence floor
`demote_low_confidence` moves every `low`-confidence finding to `demoted[]`. The
floor is the tier itself, not a numeric score. **Consequence to understand:** a
`low`-confidence finding never appears in `report.findings` and therefore never
appears in the severity counts, no matter how severe. It surfaces instead as a
proactive opportunity via the `demoted_finding` source.

### `THIN_SAMPLE_FLOOR = 3` (`normalize.py`)
Applies only to findings that **explicitly claim extrapolation**. A direct
observation of one or two instances keeps its confidence — see §J.

### Distribution guard: `0.3` over `>= 5` findings
Telemetry only. The threshold is arbitrary and the guard's whole point is that it
does not act on it.

**Honest summary:** every numeric constant here (0.8, 0.3, 5, 3) is a chosen
policy value. The repository states this in `OVERFITTING_AUDIT.md` rather than
claiming empirical derivation, and no independent calibration dataset exists.

---

## I. EVIDENCE MODEL

This skill's relationship to evidence is *custodial*: it must not damage
evidence while reorganizing findings. Three mechanisms enforce that.

1. **Rejection over repair.** `_rejection_reason` never fills in a missing field.
   A finding without `evidence` or `mechanism` is rejected, not defaulted.
2. **Union, never invention, on merge.** `_merge_group` unions
   `observation_ids`/`source_urls` and takes a **maximum** for counts. It never
   sums, and never promotes context URLs into affected instances.
3. **Immutable evidence fields during scoring.** `score_finding` changes
   `severity` and appends `scoring_trace`; the evidence-bearing fields are listed
   in its docstring as untouched.

**Example 1 — a merge.** Two `D-EXTRACT-02` findings, one for missing titles on
`/a` and `/b`, one for missing descriptions on `/b` and `/c`, with the **same**
mechanism prose and overlapping affected sets, merge into one finding with
`source_urls = {a,b,c}`, `affected.count = 3` (not 4 — no summing), and the
higher of the two confidences.

**Example 2 — a rejection.** A hand-constructed finding with
`severity: "urgent"` is rejected with `"invalid severity 'urgent'"` and appears
in `report.run.rejected_findings`. It never reaches `findings[]` or `demoted[]`,
so it cannot influence the severity counts.

---

## J. FALSE POSITIVES / FALSE NEGATIVES — historical record

Every row here is a case where the *prioritization policy itself* was wrong.

| Issue | Old behaviour | Why wrong | Fix | Regression test |
|---|---|---|---|---|
| **Severity quota** | a report should contain ≤~30% high/critical findings, enforced by rewriting severities | Adding an unrelated low finding could silently change another finding's severity. Severity must be a property of the evidence, not of the report's composition | The ratio became a **warning** in `calibration_log`; nothing is rewritten | `test_distribution_guard_warns_but_preserves_evidence_backed_severities`; `test_finding_severity_is_invariant_to_unrelated_findings` |
| **Sample = population** | an unmeasured `total_in_scope` was treated as "the sample is the whole population" | Manufactured sitewide scope from a handful of URLs | `total_in_scope` stays `None`; no scope modifier without a measured denominator | `test_unknown_population_does_not_infer_sitewide_scope` |
| **Singular targets scored 100%** | `count/total` with `total == 1` gave ratio 1.0 ⇒ +1 | One `robots.txt` is not "broad scope" | the `total <= 1` floor | covered by the scope-modifier tests |
| **Blanket confidence demotion on small samples** | one or two observed errors could not be high confidence | Sampling uncertainty applies to *extrapolated* claims, not direct observations | `THIN_SAMPLE_FLOOR` applies only to explicitly extrapolated claims | `test_normalize_preserves_single_direct_observation_confidence`; `test_normalize_drops_confidence_only_for_explicit_thin_extrapolation` |
| **Jaccard-overlap dedupe** | same `check_id` + a text-overlap cutoff meant "duplicate" | Merged genuinely different sub-defects under one check ID | Require same subtype (`dedupe_key` or mechanism) **and** overlapping affected instances; join connected components | `test_dedupe_never_merges_distinct_subchecks_on_the_same_pages` |
| **Context URLs counted as scope** | merge scope reconstructed from all cited URLs | A URL mentioned as context inflated the affected count | Use `affected_url_set`, not `finding_url_set` | `test_dedupe_uses_affected_urls_not_context_urls_for_scope` |
| **Order-dependent merges** | tied merges depended on detector execution order | Non-deterministic reports | Canonical-JSON tie-break | `test_dedupe_is_permutation_invariant_for_equal_confidence`; `test_dedupe_merge_does_not_double_count_heavily_overlapping_urls` |
| **Shallow URL ⇒ important** | shallow path depth implied an important page | A deep page can be the audit target; a shallow one can be trivial | Boost only the **explicitly requested** target, and only when actually affected | `test_score_explicitly_requested_deep_page_raises_severity`; `test_score_does_not_infer_importance_from_shallow_url_shape`; `test_context_url_does_not_promote_affected_page_importance` |

There is no *unavailable-instrument* entry for this skill — it depends on no
instrument at all.

---

## K. TESTING

`tests/test_evidence_prioritization.py` (687 lines) is unusually adversarial
because the failure modes here are silent: a bad merge or a rewritten severity
produces a plausible-looking report.

- **Normalization tests** — one per rejection reason, plus the two thin-sample
  cases proving direct observations keep their confidence.
- **Dedupe tests** — distinct subchecks on the same pages must *not* merge;
  context URLs must not count as scope; permutation invariance; no double
  counting on heavily overlapping URL sets.
- **Scoring tests** — each modifier in isolation, the clamp, the critical floor
  *and* ceiling, and the invariance property (adding an unrelated finding must
  not change an existing finding's severity).
- **Ranking tests** — determinism and the urgent-check tie-break.
- **CLI tests** — `normalize.py`, `aggregate_dedupe.py` and `score.py` each expose
  `--findings`/`--out` and are exercised as processes.

**Weak spots.**
1. `link_related_findings` has thinner coverage than the rest of the pipeline.
2. The mechanism-prose dedupe key is tested for *not over-merging*, but nothing
   tests the failure mode where two detectors write near-identical mechanism prose
   for genuinely different defects — the key would collide.
3. No test asserts `suggested_action.priority` is kept in step with a changed
   `severity`; that invariant is caught only by the report-schema validator.

---

## L. LIMITATIONS

**Implementation.** Mechanism prose as a dedupe key is a fallback, not an
identity. `affected.count` after a merge is a **lower bound**, not an exact union
size — sampled URLs cannot reconstruct a true population. `related_findings` is
URL-overlap only, with no notion of causal relationship (e.g. "this render gap
*causes* that extraction failure").

**Data limitations.** `total_in_scope` is `None` for most findings because most
detectors cannot measure a denominator, so the scope modifier is inert most of the
time. This is honest but means scope rarely influences ranking in practice.

**Environment.** None — the skill is pure computation with no I/O beyond its CLI.

**Generalization.** All numeric constants (0.8, 0.3, 5, 3) are chosen policy.
`CRITICAL_ALLOWLIST` and `URGENT_CHECK_IDS` hard-code four check IDs each and must
be maintained alongside the detectors.

**Deliberately unsupported.** No quota on severity distribution. No re-judging of
a detector's evidence — `evidence-validation.md` states the check is
"intentionally narrow — never a paraphrase judgment", because re-judging would
duplicate what `confidence` already encodes.

---

## M. HOW A HUMAN WOULD IMPROVE THIS SKILL

### Low-risk
- **Assert the `priority`/`severity` invariant inside `score_finding`** rather than
  relying on the report schema to catch a drift. Files: `score.py`. Tests: add one.
  Risk: very low.
- **Add a `dedupe_key` to the detectors that have genuine subtypes** (`D-ENTITY-04`
  description vs address; `D-EXTRACT-02` empty vs duplicate; `D-EXTRACT-04` parse
  error vs missing property). Files: the four detector scripts + `dedupe-rules.md`.
  Risk: low, but it changes merge behaviour, so re-run the corpus.

### Architectural
- **Give detectors a way to report a measured denominator.** Current: nearly every
  `total_in_scope` is `None`, so `_scope_modifier` almost never fires. Better: each
  detector declares the population it examined. Tradeoff: every detector's
  `affected_block` call must change; the schema already permits it. Files: all
  detectors, `lib/common/findings.py`. Tests: scope-modifier and corpus.
- **Causal `related_findings`.** Current: URL overlap. Better: an explicit
  "caused-by" relation (a `D-RENDER-01` gap explains a `D-EXTRACT` miss on the same
  page). Tradeoff: needs a cross-check dependency model that does not exist.
- **Replace mechanism-prose keys with stable subtype IDs** — named in
  `OVERFITTING_AUDIT.md` as the appropriate next mechanism.

### Research / future work
- Calibrating the 0.8 scope boundary and the demotion floor against labelled
  reports. Until then they should keep being described as policy, not fact.

---

## N. READ THESE FILES NEXT

1. `references/severity-matrix.md` — the policy this skill implements; read before
   any code.
2. `scripts/_prioritization_util.py` — 43 lines; note `SEVERITY_ORDER` is
   **ascending** and that `finding_url_set` ≠ `affected_url_set`.
3. `scripts/normalize.py::_rejection_reason` — the admissibility gate, top to bottom.
4. `scripts/score.py::prioritize_findings` — the eight-stage order, then follow it
   stage by stage.
5. `scripts/score.py::score_finding` — then `_scope_modifier`, reading the
   `total <= 1` comment.
6. `scripts/aggregate_dedupe.py::_merge_group` — the densest policy in the skill.
7. `references/confidence-model.md` and `dedupe-rules.md` — after the code.
8. `tests/test_evidence_prioritization.py` — the dedupe and invariance tests.
9. `skills/audit-orchestrator/KNOWLEDGE.md` §14–§16 for how this output becomes
   the report.
