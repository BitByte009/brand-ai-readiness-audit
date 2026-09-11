# Site-archetype applicability

`lib/site_observer/classify.py` assigns an archetype from structured data and sampled
URL patterns. An empty archetype means unknown. Classification is heuristic, not
an external assertion about the organization. All checks use their own evidence
preconditions; no missing matrix row disables a check.

The following are the implemented archetype exceptions. Other checks have no
archetype override and still require their documented mechanical evidence.

| Check | Exception | Implementation |
|---|---|---|
| D-ENTITY-01 | Lower confidence/severity for documentation and personal portfolios | `skills/entity-semantic-audit/scripts/detect_entity.py` |
| D-ENTITY-02 | Lower confidence/severity for personal portfolios | Same detector |
| D-ENTITY-04 | Lower severity for personal portfolios | Same detector |
| D-ENTITY-06 | Suppressed for documentation, personal portfolios and institutions; reduced for publishers | Same detector |
| D-TRUST-01, D-TRUST-02 | Higher base for publishers; lower for documentation and personal portfolios | `skills/trust-freshness-audit/scripts/detect_trust.py` |
| D-TRUST-06 | Suppressed for personal portfolios | Same detector |
| E-ORIENT-03 | Suppressed for local businesses, personal portfolios and web apps | `skills/engagement-audit/scripts/detect_engagement.py` |
| E-CONTINUE-01, E-CONTINUE-02, E-CONTINUE-03 | Suppressed for personal portfolios and web apps | Same detector |

Page-level applicability is separate. Explicit semantic page types are collected
as PAGE_CLASSIFICATION observations. Unknown types remain `other`; terminal pages
and utility paths are excluded where the individual check requires continuation.
English vocabulary checks abstain on explicitly non-English pages. Unlabelled
Latin-script languages remain a limitation.

Below three crawled pages, collection records INSUFFICIENT_PAGES. Individual
cross-page checks apply their own sample-size preconditions; the pipeline does
not pretend every cross-page comparison requires the same minimum.
