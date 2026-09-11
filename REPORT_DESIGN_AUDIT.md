> Historical review. Current changes and verification are in [SUBMISSION_FIXES.md](SUBMISSION_FIXES.md). Statements about missing wiring, failing tests, paths or deadlines below may describe the earlier revision.

# Final report design audit

The required top-level fields remain `site`, `audited_at`, `summary`, and
`findings`. Every finding still requires `id`, `title`, `severity`, `evidence`,
and `suggested_action`. Existing summary counters and action summary/priority
requirements are unchanged. Optional extension fields remain supported.

## Field design

| Information | JSON location | Human-readable presentation |
| --- | --- | --- |
| Audit subject and time | `site`, `audited_at` | Report heading and timestamp |
| Category and evidence strength | finding `category`, `confidence` | Category and confidence labels |
| Cause and consequence | finding `mechanism`, `impact` | “Why this happens” and “Why it matters” |
| Finding scope | finding `affected` | Observed count and measured denominator, or explicit unknown scope |
| Audit scope | report `scope` | Finding scope is explicitly distinguished from whole-site coverage |
| Evidence provenance | `evidence`, `source_urls`, `observation_ids` | Evidence, sources, observation references |
| Remediation | `suggested_action.summary`, `.how_to_fix`, `.validation` | Suggested action, implementation steps, verification |
| Related issues | `related_findings` | References to surviving findings only |
| Missing coverage | report `coverage` | Up-front warning and detailed Coverage section |

No duplicate `scope`, `how_to_fix`, or `validation` aliases were introduced:
the existing nested fields carry those meanings. Minimal reports remain valid
without optional enhancements; the report does not invent absent evidence or fixes.

## Changes and regressions

| Old assumption | Generalized rule | New regression |
| --- | --- | --- |
| Correct JSON types imply a coherent report | Counts match findings; IDs are unique; priorities agree; related references resolve; scope counts are consistent | Invalid counters, IDs, priorities, references, and scope examples |
| A declared timestamp format is always enforced | Enforce zoned timestamps without an optional format dependency | Invalid dates and timezone-less examples |
| Required strings can be empty | Subject, title, evidence, and action summary must contain text | Blank and missing required-field examples |
| JSON serialization necessarily produces interoperable JSON | Reject nonfinite values and nonserializable extensions | NaN extension example |
| Distinct IDs imply distinct issues | Reject exactly duplicated content; retain existing mechanism/overlap-based aggregation | Duplicate content under different IDs; existing distinct-mechanism tests |
| JSON-only cause, impact, and citations are sufficient for readers | Expose these fields alongside fixes and verification in Markdown | Enriched report rendering example |
| Unknown denominator can be displayed as an ordinary count | Label the denominator as unmeasured, never imply whole-site scope | Unknown-scope rendering example |
| No coverage warnings means every check completed | State only that no limitations were recorded; warn before findings when limitations exist | Empty and degraded coverage examples |
| Fetched text is safe to interpolate into Markdown | Escape HTML and Markdown control characters; prevent injected block structure | Script, link, and heading injection example |
| Evidence filtering cannot affect relationships | Remove references to dropped findings without renumbering surviving IDs | Unsupported related finding integration test |
| Logging schema failure is sufficient | Both artifact-writing commands reject invalid reports before writing | Audit and renderer CLI refusal tests |
| Every affected sample is a fetched absolute URL | Robots path patterns are valid scope samples; source URLs remain absolute HTTP(S) URLs | Robots pattern scope example |

## Assessment and limits

- Machine-readable: schema plus `lib.common.schema.validate_report` enforce
  structure and cross-field consistency. External consumers must run the semantic
  validator as well as JSON Schema to check counts and references.
- Understandable and actionable: readers can see cause, impact, scope, evidence,
  action, and verification together. Severity and confidence are distinguished.
- Evidence-backed: existing observation binding is retained. References identify
  collection evidence; schema validity alone cannot establish that a claim is true.
  The final report does not embed the complete observation store.
- Prioritization: existing severity order and within-tier ranking are preserved;
  action priority must agree with severity. Detector calibration was not changed.
  In particular, critical-allowlist floors can still produce critical findings
  on narrow scopes; this requires a separate scoring-policy decision.
- Duplicates: existing deterministic mechanism-and-overlap merging is preserved.
  Exact repeated content is rejected; differently worded semantic duplicates
  are not universally detectable by a structural validator.

## Validation

- 43 new report-design cases, including valid minimal, enriched, and degraded
  examples and invalid structural/semantic examples.
- Full suite: **481 passed**.
- Browser corpus: **19 fixtures**, 27/27 scored check presences and 34/34 finding
  evidence/recommendation/severity checks passed; no measured false positives,
  false negatives, or guard violations. This is not an unseen-site guarantee.
- Marketplace validation, including official `skills-ref`: **passed**.

Run tests from the marketplace root with `python -m pytest`. Report examples
are executable builders in `tests/test_report_design.py`.
