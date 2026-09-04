# False-positive guardrails

Evaluated BEFORE the detection test. If the applicability precondition fails, the
check does not fire and is not recorded as a pass. Full mechanism/threshold detail
lives with each check in `crawl-checks.md`, `render-checks.md`, `extract-checks.md`;
this file is the compiled cross-reference so a suppression can be looked up by check
ID without re-reading three files.

## Never flag (marketplace-wide, verbatim from the design brief)
- irrelevant absence of a feature the site does not need
- normal JavaScript use
- structured data that is unnecessary for the page type
- short pages
- unusual visual design
- an LLM subjective opinion unsupported by a measurement

## Skill-specific suppressions

| Check ID | Suppression condition | Effect |
|---|---|---|
| D-CRAWL-01 | Path is a utility path (cart/search/checkout/login/account/wishlist/admin, or carries a query string) | never fires |
| D-CRAWL-01 | `ROBOTS.status != "ok"` | does not fire (that's D-CRAWL-15) |
| D-CRAWL-02 | — | always fires as a neutral *consequence*, never as an error; downgraded to medium |
| D-CRAWL-03 | Page is a tag/filter/thank-you/cart/search/checkout/print page, or is under the short-page floor | never fires |
| D-CRAWL-04 | Single transient 5xx that clears on one retry | never fires |
| D-CRAWL-05 | Exactly one canonical hop (`http->https`, apex `->www`, trailing-slash) | never fires |
| D-CRAWL-06 | Canonical target is cross-domain | never fires (legitimate on syndicated content) |
| D-CRAWL-06 | Canonical target was never itself crawled | does not fire (applicability unmet, not a pass) |
| D-CRAWL-07 | Sitemap absent but no orphan pages exist | never fires — absence alone is not a defect |
| D-CRAWL-08 | Page is a utility/legal path (privacy, terms, cookie policy) | never fires |
| D-CRAWL-08 | Fewer than 3 crawled pages | check disabled (minimum-corpus rule) |
| D-CRAWL-08 | The root path (crawl's entry point) | never counted as orphaned |
| D-CRAWL-09 | 403/429 clears on a backed-off retry | never fires (rate limiting we caused, not a block) |
| D-CRAWL-09 | — | never confirmed by spoofing a different UA (D-10); scoped strictly to our honest fetch |
| D-CRAWL-10 | Fewer than 5 samples, or a single slow request | never fires; capped at medium even when it does |
| D-CRAWL-11 | Fewer than 2 detected locale variants of the same content | never fires |
| D-CRAWL-12 | No explicit regional-block response observed | never fires — the vantage-point caveat itself is not a finding |
| D-CRAWL-13 | Alternate host/path form 301s to the canonical host | never fires |
| D-CRAWL-14 | Crawl completed within budget regardless of parameter ratio | never fires |
| D-CRAWL-15 | `ROBOTS.status == "missing"` (clean 404) | never fires — missing conventionally means allow-all |
| D-RENDER-01..05 | `RENDER.status != "ok"` (capability absent or render failed) | category inapplicable for the page, not a pass |
| D-RENDER-01 | Missing text is client-side widgets, comments, recommendations, chat, or analytics | never fires |
| D-RENDER-01 | Missing text is navigation chrome | never fires (that's D-RENDER-03) |
| D-RENDER-01 | Sibling pages of the same template pass | suppressed at template level |
| D-RENDER-02 | No answered `category=="factual"` probe question for the page | never fires |
| D-RENDER-03 | Rendered-only link is a duplicate of an already-raw-visible href | excluded before the 3-entry count |
| D-RENDER-04 | Panel content is DOM-present but CSS-hidden | never fires — visibility is not the test, DOM text-emptiness is |
| D-RENDER-05 | Listing has fewer than 10 rendered items | never fires |
| D-EXTRACT-01 | Probe miss with no non-text carrier (empty-alt image / bare PDF link) present | never fires — falls to D-EXTRACT-06/07 instead |
| D-EXTRACT-02 | Shared title/description is a legitimate paginated series of the same content | never fires |
| D-EXTRACT-03 | Markup absent but prose states the fact (probe answers) | never fires — **markup absence alone is never a defect** |
| D-EXTRACT-03 | Page type has no clear schema.org mapping | never fires |
| D-EXTRACT-04 | Gap is in an optional (non-required) property, or a vocabulary extension | never fires |
| D-EXTRACT-05 | Multiple `<h1>`s present | never fires alone — that's valid HTML5 |
| D-EXTRACT-06 | Fewer than 2 relevant unanswered questions | never fires |
| D-EXTRACT-06 | Page has zero questions marked relevant | never fires — not "about" the canonical topics |
| D-EXTRACT-07 | Question not marked `relevant==true` by the probe instrument | never fires — this skill never substitutes its own relevance judgment |
| D-EXTRACT-08 | — | **never emits a finding at all** — proactive-only, structurally cannot false-positive as a defect |
| D-EXTRACT-09 | Resource is intentionally non-HTML (JSON feed, RSS, PDF linked as data) | never fires |
| D-EXTRACT-09 | Mojibake/replacement-character rate below 1% of characters | never fires |

## Compound-trigger checks (two independent signals required)
Per `PHASE1-ANALYSIS.md` §5.2, these are the checks most prone to over-firing and each
requires two independent signals, never one: D-EXTRACT-01 (probe miss + non-text
carrier), D-EXTRACT-03 (page-type mapping + probe miss), D-EXTRACT-09 (content-type
mismatch or mojibake, each independently gated), D-CRAWL-09 (initial block + retry
confirmation), D-CRAWL-14 (parameter ratio + budget exhaustion).
