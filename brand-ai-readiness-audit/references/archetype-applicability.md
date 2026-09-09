# Site-archetype applicability matrix

Archetype is classified once in the observation layer, before any check runs, and is
stated in the report so a reader knows what frame we audited under.

Archetypes: `brand-product`, `ecommerce`, `publisher-editorial`, `documentation`,
`local-business`, `personal-portfolio`, `institutional`, `web-app`.

Each check declares one of: APPLIES / SUPPRESSED / RETHRESHOLDED per archetype.

| Check | brand-product | ecommerce | publisher | documentation | local-business | personal | institutional | web-app |
|---|---|---|---|---|---|---|---|---|
| D-ENTITY-06 offering unclear | APPLIES | APPLIES | RETHR | SUPPRESSED | APPLIES | SUPPRESSED | SUPPRESSED | APPLIES |
| D-ENTITY-01 canonical name | APPLIES | APPLIES | APPLIES | RETHR | APPLIES | RETHR | APPLIES | APPLIES |
| D-ENTITY-02 type never stated | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | RETHR | APPLIES | APPLIES |
| D-ENTITY-03 ambiguous collision | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| D-ENTITY-04 cross-page inconsistency | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | RETHR(down) | APPLIES | APPLIES |
| D-ENTITY-05 no identity anchor | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| D-TRUST-01 undated claims | APPLIES | APPLIES | RETHR(up) | RETHR(down) | APPLIES | RETHR(down) | APPLIES | APPLIES |
| D-TRUST-02 stale signals | APPLIES | APPLIES | RETHR(up) | RETHR(down) | APPLIES | RETHR(down) | APPLIES | APPLIES |
| D-TRUST-03 internal contradiction | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| D-TRUST-04 unattributed claims | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| D-TRUST-05 uncorroborated claim | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| D-TRUST-06 organizational opacity | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | SUPPRESSED | APPLIES | APPLIES |
| D-EXTRACT-03 missing schema | APPLIES | APPLIES | APPLIES | SUPPRESSED | APPLIES | SUPPRESSED | RETHR | SUPPRESSED |
| E-CONTINUE-01 no next step | APPLIES | APPLIES | APPLIES | APPLIES | RETHR | SUPPRESSED | APPLIES | SUPPRESSED |
| E-ORIENT-03 path context | RETHR | APPLIES | APPLIES | APPLIES | SUPPRESSED | SUPPRESSED | APPLIES | SUPPRESSED |
| E-ORIENT-01 brand ID on arrival | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| E-ORIENT-04 fragment links resolve | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| E-ANSWER-01 title/body promise | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| E-ANSWER-02 blocking interstitial | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| E-ANSWER-03 citation gated for human | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| E-ANSWER-04 citation-landing mismatch | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |
| E-CONTINUE-02 dead end | APPLIES | APPLIES | APPLIES | APPLIES | RETHR | SUPPRESSED | APPLIES | SUPPRESSED |
| E-CONTINUE-03 route to hub | APPLIES | APPLIES | APPLIES | APPLIES | RETHR | SUPPRESSED | APPLIES | SUPPRESSED |
| E-CONTINUE-04 broken internal links | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES | APPLIES |

**Scope of this matrix.** It covers the 24 checks whose applicability genuinely
varies by archetype: `D-ENTITY`, `D-TRUST` and the `E-*` engagement families.
The `D-CRAWL`, `D-RENDER` and `D-EXTRACT` families are deliberately absent, and
their absence does not disable them: they are mechanism/gate checks (can a
machine reach the page, read it, pull a fact out of it) that apply uniformly to
every archetype, so 29 near-identical "APPLIES" rows would carry no information.
Their applicability preconditions live with the checks themselves, in
`skills/crawl-render-audit/references/`. Every one of them runs -- `D-CRAWL-01`,
`D-CRAWL-04`, `D-EXTRACT-02`, `D-EXTRACT-04` and `D-RENDER-01` among others fire
end to end in the fixture corpus.

## Minimum-corpus rule
Below 3 crawled pages, all cross-page consistency checks disable and the coverage
block says so. Below 3 samples in a template cluster, confidence drops one tier.
