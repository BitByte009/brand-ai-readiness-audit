# Failure taxonomy (shared)

Authoritative ID registry. Per-check detail lives in each skill's `<marketplace-root>/references/failure-taxonomy.md` registry.
Every check is defined with 12 fields: id, meaning, mechanism, applicability,
observable_signals, detection_test, evidence_required, false_positive_rules,
false_negative_risks, severity, confidence, recommendation + validation.

Status: registry frozen at 53 checks. Full 12-field expansion is Day 1-4 work,
tracked per skill. No new check IDs after the Day 4 feature freeze.

## Discoverability
| Prefix | Concern | Owner | Count |
|---|---|---|---|
| D-CRAWL-01..15  | reach: permission, status, redirects, canonicals, duplicates, budget | crawl-render-audit | 15 |
| D-RENDER-01..05 | read: raw vs rendered gaps | crawl-render-audit | 5 |
| D-EXTRACT-01..09| extract: facts out of text | crawl-render-audit | 9 |
| D-ENTITY-01..06 | who this is, unambiguously | entity-semantic-audit | 6 |
| D-TRUST-01..06  | would a machine believe it | trust-freshness-audit | 6 |

## Engagement
| Prefix | Concern | Owner | Count |
|---|---|---|---|
| E-ORIENT-01..04   | where am I | engagement-audit | 4 |
| E-ANSWER-01..04   | does the page deliver the answer | engagement-audit | 4 |
| E-CONTINUE-01..04 | can I go further | engagement-audit | 4 |

## Meta
| X-COV-01 | A check could not run. Recorded in the coverage block. Never a finding,
never counted in severities, never presented as a pass. |

## Revision log (from Phase 1B review)
- ADDED: D-CRAWL-11 hreflang/locale, D-CRAWL-12 geo variance, D-CRAWL-13 duplicate
  hosts, D-CRAWL-14 facet budget burn, D-CRAWL-15 robots.txt 5xx/unparseable,
  D-EXTRACT-09 encoding/content-type, E-ANSWER-04 citation-landing mismatch.
- CUT: E-CONTINUE-05 viewport/overflow. Weakest mechanism link; invited aesthetic findings.
- DEMOTED: D-TRUST-04 to low + single aggregated finding; D-EXTRACT-08 to proactive-only;
  E-ORIENT-02 folded into the E-ANSWER-04 measurement; D-CRAWL-10 capped at medium;
  E-ANSWER-01 capped at medium severity and confidence.
- REASSIGNED: cross-page address -> D-ENTITY-04; cross-page price/stat/date -> D-TRUST-03.
- REWRITTEN: D-CRAWL-09 no longer spoofs user-agents. One honest self-identifying UA;
  AI-crawler policy read declaratively from robots.txt.

## Proactive-only (never emitted as findings)
llms.txt absence, feed/API availability, author-expertise enrichment,
substance-to-boilerplate ratio.
