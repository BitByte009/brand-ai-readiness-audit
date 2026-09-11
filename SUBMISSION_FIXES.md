> Superseded by the final submission pass in [FINAL_COMPLIANCE.md](FINAL_COMPLIANCE.md); the test counts below describe the preceding revision.

# Submission fixes — 2026-09-11

This document supersedes implementation-status claims in the earlier audit notes.
The official Round 3 handout is preserved at the marketplace root. Its page 4 says
it does not provide a checklist: D-EXTRACT/E-ORIENT/E-CONTINUE identifiers belong
to this project's internal taxonomy, not an official mandatory PDF catalog.
E-ORIENT-02 remains consolidated into answer orientation and E-CONTINUE-05 remains
outside the current taxonomy. Their absence alone is not a handout compliance failure.

## Root and packaging

The nested marketplace was moved into the workspace root, preserving its files.
The root now directly contains marketplace.json, README.md, all six skills, lib,
references, schemas and tests. Relative imports and manifest paths resolve here.
The missing SAFETY_AUDIT.md is supplied with the implemented safety boundary.
The handout and design documents are preserved; older reviews are marked historical.

`scripts/package_submission.py` builds `dist/submission.zip` with marketplace.json
at ZIP root. It excludes Git metadata, caches, bytecode, environments and generated
reports, rejects recognized model-weight extensions, checks archive integrity, and
checks the 50 MB limit. .gitignore and .gitattributes supplement this explicit filter.

## Collection and pipeline

- D-EXTRACT-08 is called by the entrypoint and included in Markdown proactive output.
- Bounded robots-aware sitemap discovery supplies crawl seeds and SITEMAP evidence.
  Unchecked sitemap URLs are unknown, not dead; unavailable XML is not a missing sitemap.
- PAGE_CLASSIFICATION records semantic page types. Local PROBE records verify actual
  positive text spans and allow factual raw/render comparisons and boilerplate suggestions.
  These probes do not invent negative answers or claim OCR/model capabilities.
- Crawl-budget exhaustion is recorded for D-CRAWL-14. Incomplete crawl graphs cannot
  establish orphaned pages. English vocabulary checks abstain on declared non-English
  content and coverage reports LANGUAGE_UNSUPPORTED.
- Optional --save-evidence writes observations.json. Absence findings receive IDs for
  their observed source pages; report counts remain derived from final findings only.

## Accuracy and reliability

- Page topics are excluded from brand aliases. Explicit identity names take precedence;
  declared alternateName values remain aliases. The official domain uses the self URL,
  rather than the first social sameAs link. Early brand checks include header text and
  label their text-sample limitation honestly.
- Rendered external links are excluded from internal navigation gaps. Missing raw facts
  must actually appear in rendered text. Finite lists require explicit continuation
  evidence before a missing-pagination finding can fire.
- Browser overlay checks use computed visibility, viewport area and occlusion. Answer
  position uses measured paragraph geometry when available; text-order fallback is
  labelled and has lower confidence. Hidden/closed dialogs are suppressed.
- Duplicate-summary checks can compare distinct paths, require matching title AND
  description, and suppress identical representations, canonical aliases and pagination.
- Explicitly different time contexts suppress employee/customer-count contradictions.
  JSON-LD recursion errors are handled; schema type normalization is shared by proactive
  suggestions. Non-HTML resources and valid XHTML are not wrongly diagnosed as HTML MIME faults.
- Local network/robots-policy failures are coverage limitations, not site defects.
  Critical severity requires strong scope evidence; an allowlisted check ID does not
  impose an unconditional critical floor.
- Detector import failures are isolated. Unexpected lifecycle failures emit an explicit
  incomplete report. The CLI uses a 280-second worker deadline; POSIX worker descendants
  share a process group for timeout cleanup. Collection shares a 270-second budget.

## Verification

The previous claimed 716 passed / 1 failed / 2 errors did not reproduce in this
checkout. In an isolated Python 3.12 environment, the initial baseline was 540 passed,
1 failed, 0 errors. The failure was the missing safety-document link in marketplace
validation; tests/test_safety.py passed without modifying that test file.

Verified in an isolated Python 3.12 environment:

| Check | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider` | 558 passed, 0 failed, 0 errors |
| `python tests/validate_marketplace.py` | PASS: manifest, skills, references, composition, scripts, schemas and size |
| `python tests/harness/run_corpus.py` with Chromium | 19 fixtures; 0 unexpected false positives/negatives; 0 guardrail violations; 38/38 evidence anchors resolve; 2 explicitly recorded known capability gaps |
| `python tests/harness/run_safety.py` | 9/9 real-browser adversarial scenarios pass |
| `python tests/harness/benchmark_runtime.py` | 30-page CPU-only fixture: 2.773 seconds with profiling overhead; not a network benchmark |
| Real browser corpus runtime | 0.005–11.296 seconds per synthetic fixture; no unseen-site runtime claim |
| CLI smoke check against a refused private target | Valid report and optional evidence export; no site defect fabricated |

`tests/test_safety.py` is byte-identical to the original tracked version. Test
execution disables bytecode/cache generation. Browser binaries and the test
environment were installed in temporary directories outside the submission.

Fixture corrections make the intended signals explicit: a blocking modal now has
blocking CSS; conflicting entities have explicit distinct names; brand-free deep
pages omit a visible brand footer; the clean archival article identifies its author.
Newly wired checks are required expectations. Known coverage misses are counted
separately from unexpected regressions, not reported as successful detections.
Evidence-quality checks now actually resolve IDs against the run's observation store.
Recommendation and severity quality metrics remain structural checks, not human
validation of every recommendation.

## Remaining limits

No external search provider, OCR or semantic absence model is configured. These are
explicit coverage limitations. Vocabulary support remains English-first; unlabelled
Latin-script languages can be misclassified. SPA/hash navigation and cross-origin
browser resources remain restricted. Conservative safety boundaries are retained.

The synthetic corpus is not an unseen-site accuracy benchmark. A deadline bounds
failure time; it does not prove a complete audit of every typical website within five
minutes. The host still supplies process/memory isolation and a writable output path.
