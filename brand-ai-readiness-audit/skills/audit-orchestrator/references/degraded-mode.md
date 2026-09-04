# Degraded mode

Every path below must produce a schema-valid report and exit 0. A crash scores zero
on every rubric line simultaneously.

| Trigger | Behaviour |
|---|---|
| DNS/host unreachable | The robots.txt fetch fails the same way a page fetch would; this collapses to the "robots.txt 5xx / unparseable" row below (status `error`) since both are the identical `requests.RequestException` path in `lib/common/robots.py`. D-CRAWL-15 fires; crawl is empty. |
| robots.txt disallow-all | **Crawl nothing.** No page is fetched, so `crawl-render-audit`'s own D-CRAWL-01 (which needs at least one already-discovered disallowed URL) structurally cannot fire here -- a known gap, not a suppressed finding. The block is communicated instead through `coverage` (ROBOTS_DISALLOWED, scope "all raw-crawl and rendered-lens checks") and `scope.pages_crawled == 0`, per coverage-policy.md's own principle: a check that could not run must never look like a check that passed, and this skill never fabricates a finding to fill that gap. |
| robots.txt 5xx / unparseable | D-CRAWL-15 critical; crawl treated as disallowed. Unlike disallow-all, this fires from the robots status alone, independent of any discovered URL. |
| Renderer unavailable | Raw-only audit; all D-RENDER + rendered-lens E-* -> coverage gaps |
| Bot challenge detected | Reported as the finding it is; audit continues on what is reachable |
| Auth wall | Public surface only; coverage states the boundary |
| Cross-domain redirect | Audit the resolved host; report both requested and audited |
| < 3 pages discoverable | Cross-page checks disabled; coverage states it |
| Budget exhausted | Partial audit, honest scope counts, coverage entry |
