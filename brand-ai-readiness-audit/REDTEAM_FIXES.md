# Red-team fixes

> **Dated record.** Figures in this document describe the pass it reports on. Current release-candidate figures are 718 offline tests, corpus 29/29 with no false positives or false negatives, and 37/37 evidence/recommendation/severity gates -- all measured against expectations authored in this repository, which is regression evidence rather than independent real-world validation.


Scope: highest-impact, directly reproducible issues from the review. Existing
overfitting changes were preserved. No new detector, model integration, marketplace
skill, or external service was added. Useful deterministic checks remain in place.

## FIXED

Regression names below are in `tests/test_redteam_fixes.py` unless otherwise stated.

| Fix | OLD ASSUMPTION → GENERALIZED RULE → NEW TEST |
|---|---|
| Robots permission semantics | Selected other bots' rules and simple prefixes describe permission → use the auditor's actual product token, grouped agents, longest matching path/query rules, Allow ties, wildcards/end anchors, comment and percent-encoding handling → `test_robots_protocol_counterexamples` (12 cases). |
| Root denial and audit seed | Root denial means the entire origin is forbidden, and an unfetched seed has no reportable restriction → check each exact target; retain observed seed restrictions without fetching it; prove blanket denial conservatively → `test_allowed_deep_exception_is_crawled`, `test_disallowed_seed_is_reported_without_fetching`, `test_root_denial_is_not_proof_of_blanket_denial`. Updated the existing disallow-all orchestrator expectation to retain D-CRAWL-01. |
| Redirect authorization | Initial URL approval covers every redirect → fetch one hop at a time, authorize each destination and preserve redirect evidence; robots redirects conservatively yield unavailable coverage → `test_each_redirect_is_authorized_before_fetch` (3 cases), `test_robots_redirect_is_not_implicitly_followed`. Links resolve against the fetched final URL. |
| Ambient HTTP credentials | A nominally read-only HTTP call cannot use local credentials → disable requests' environment/netrc trust and automatic redirects, retain the declared auditor identity → `test_request_disables_ambient_credentials_and_redirects`. |
| Browser request boundary | Page navigation is equivalent to a single safe GET → intercept requests, allow only same-origin credential-free GET/HEAD, apply robots rules, block Authorization-bearing requests, service workers, WebSockets and implicit redirects; discard a policy-restricted partial DOM → `test_browser_requests_are_intercepted_and_partial_dom_is_rejected`, plus `test_network_boundary_denies_before_request` (5 cases). The fake-browser regression exercises registered callbacks; the corpus exercises real Chromium. |
| Shared request budget and pacing | Raw-page counts cover network load → count preflight, redirect hops and browser resources at the same boundary, cap at 200 admitted requests per audit, pace requests, honor applicable crawl-delay, stop after 429/503 and refuse waits beyond the current stage → `test_shared_budget_and_server_backoff`, `test_grouped_crawl_delay_is_retained`, `test_politeness_waits_only_remaining_interval`, `test_crawl_delay_exceeding_remaining_stage_budget_does_not_sleep`. The cap is an operational safety limit, not evidence of a website defect. |
| Error-page content findings and duplicated selection logic | HTML exists, therefore it describes the site; browser navigation completion implies HTTP success → one shared `lib/common/pages.py` selector requires successful HTTP status and nonempty content, uses a valid rendered lens when available, and otherwise falls back to valid raw evidence; entity/trust checks abstain with no usable pages → `test_failed_pages_do_not_generate_content_findings` (8 statuses), `test_successful_render_http_error_falls_back_to_valid_raw_evidence`. Crawl HTTP-failure observations are retained. |
| Actionable Markdown output | The short action summary is sufficient → preserve existing repair instructions, validation steps, confidence and affected scope from JSON in the human report → `test_markdown_keeps_action_details_and_validation`. No new recommendation inference was added. |

README status, network limitations, evidence claims, and the positional CLI example
now reflect actual behavior. Optional Playwright's documented minimum is 1.48 for
WebSocket interception. No mandatory dependency was added; browser regression mocks
the optional API and does not require Playwright to be installed.

## NOT FIXED

These are still actual limitations, not successes implied by passing tests:

- **Private-address access, DNS rebinding, response-size limits and hard process
  deadlines:** same-origin checks are not transport isolation. Robust protection
  needs DNS/connection enforcement and browser egress isolation; no unsafe claim
  that a hostname filter solves this. Use only operator-approved URLs in an isolated
  environment. Stage checks do not interrupt an already-running request.
- **Lifecycle/schema/CLI guarantees:** unexpected collection/scoring/emission
  exceptions can still abort; schema validation and ID resolution do not establish
  semantic consistency or evidentiary entailment. Invalid reports can still be
  emitted and CLI exit behavior remains insufficient. Requires a separate focused
  lifecycle/failure-contract change, not covered by this patch.
- **Severity and prioritization:** check-ID critical floors and remaining heuristic
  scope/importance assumptions were not recalibrated. Need representative labeled
  severity cases before claiming correctness; existing deterministic signals were
  not deleted merely to reduce severe findings.
- **Remaining detector mistakes and generic advice:** entity aliases, modal/overlay
  visibility, intent inference, omitted failure modes and some recommendation
  templates still need targeted counterexamples. This patch fixes failed-page
  evidence selection and output omissions, not all content diagnosis.
- **Marketplace packaging/format validation and decomposition:** manifest/frontmatter,
  placeholder validator, tracked bytecode, installation portability and skill
  boundary concerns were not rewritten. This was a bounded runtime/accuracy pass,
  not a marketplace reorganization.

## DEFERRED

- **External corroboration/model/search wiring:** remains explicitly unavailable;
  adding a provider would be a speculative integration requiring a choice.
- **Cross-origin rendering and redirected robots retrieval:** conservatively blocked
  with coverage loss. Safely permitting additional origins needs separate robots,
  request budgets and explicit scope handling; silently allowing CDNs is not a fix.
- **Unseen-site benchmark and broader detector calibration:** the 19 synthetic
  fixtures do not establish generalization. A separately labeled holdout corpus is
  needed; expected fixtures were not changed to conceal failures.

## Verification

Affected suites were run after each implementation batch:

- Robots/collector: **133 passed**.
- HTTP/browser request boundary: **144 passed**.
- Shared content-evidence selection: **194 passed**.
- Deadline guard and Markdown details: **87 passed**.
- Final robots/pacing boundary regressions: **159 passed**.

Full-suite command (from the marketplace directory):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/brand-audit-test-deps /opt/homebrew/bin/python3.12 -m pytest -q -p no:cacheprovider
```

Full suite: **378 passed**, up from the **338-test** starting baseline for this
implementation pass. The temporary dependency path is this session's isolated test
environment, not a runtime dependency of the repository.

Browser corpus command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/brand-audit-test-deps PLAYWRIGHT_BROWSERS_PATH=/private/tmp/brand-audit-browsers /opt/homebrew/bin/python3.12 tests/harness/run_corpus.py
```

Both the safety-batch run and final rerun passed all **19 fixtures**, with **27/27 scored check
presences**, **34 findings**, and no measured FP/FN or guardrail violations. The
final rerun result is recorded in `tests/harness/results.json`. The score excludes
documented untestable/known-missing cases and evaluates check presence, not recall
of every defective URL. Structural evidence/action/severity checks are not a human
quality assessment. `git diff --check` is clean.
