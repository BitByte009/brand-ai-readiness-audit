# Degraded mode

Expected failures produce partial reports and coverage gaps. Unexpected library
lifecycle exceptions produce a valid empty report with AUDIT_FAILED and an explicit
warning that no site-quality conclusion is possible. Detector import/execution
failures are isolated. Inspect coverage and run.skill_failures, even with valid JSON.
File permissions, unavailable Python dependencies and OS termination can still
prevent CLI emission.

| Trigger | Behaviour |
|---|---|
| DNS/transport failure | Stop crawling and record coverage; do not diagnose a website defect from the auditor's network failure. |
| robots.txt exclusions | Check every discovered path; honor Allow exceptions and record skipped scope. |
| robots.txt HTTP error / unparseable | Stop crawling; report the observed policy problem with evidence-scoped severity. The check ID alone never forces critical severity. |
| Renderer unavailable/incomplete | Retain usable raw evidence and record missing rendered coverage. |
| Cross-origin redirect/resource | Conservatively blocked and recorded as NETWORK_POLICY. |
| Fewer than three pages | Record INSUFFICIENT_PAGES; individual checks apply their minimum evidence requirements. |
| Sitemap unavailable | Unknown, not missing; only a fetched 404 proves absence. Unfetched entries never count as dead. |
| Local probe cannot answer | PROBE_LIMITED; never manufacture negative semantic evidence. |
| No external search provider | SEARCH_UNAVAILABLE; no corroboration finding. |
| Non-English page | LANGUAGE_UNSUPPORTED for vocabulary-based checks; structural checks continue. |
| Stage/global budget exhausted | Partial scope and coverage; CLI worker stops after 280 seconds and emits a deadline report. |
