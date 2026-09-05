# Degraded mode

Expected degraded paths produce partial reports. Unexpected collection, scoring
or emission exceptions can still abort; do not promise an always-valid report.
Check run.schema_valid, run.skill_failures and coverage before presenting results.

| Trigger | Behaviour |
|---|---|
| DNS/host unreachable | The robots.txt fetch fails the same way a page fetch would; this collapses to the "robots.txt 5xx / unparseable" row below (status `error`) since both are the identical `requests.RequestException` path in `lib/common/robots.py`. D-CRAWL-15 fires; crawl is empty. |
| robots.txt exclusions | Check the seed and every discovered path against the auditor's applicable rules. Explicit Allow exceptions can permit deep pages despite root denial. An excluded seed is not fetched, but its observed robots restriction can support D-CRAWL-01. Record ROBOTS_DISALLOWED coverage for skipped paths. |
| robots.txt 5xx / unparseable | D-CRAWL-15 critical; crawl treated as disallowed. Unlike disallow-all, this fires from the robots status alone, independent of any discovered URL. |
| Renderer unavailable | Raw-only audit; all D-RENDER + rendered-lens E-* -> coverage gaps |
| Bot challenge detected | Reported as the finding it is; audit continues on what is reachable |
| Auth wall | Public surface only; coverage states the boundary |
| Cross-origin redirect | Conservatively blocked by the network boundary, with NETWORK_POLICY coverage. Do not start a second audit of the destination. Same-origin raw redirects are checked hop by hop. |
| < 3 pages discoverable | Record INSUFFICIENT_PAGES coverage; each check applies its own actual sample-size preconditions. |
| Budget exhausted | Partial audit, honest scope counts, coverage entry |
