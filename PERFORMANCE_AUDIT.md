> Historical review. Current changes and verification are in [SUBMISSION_FIXES.md](SUBMISSION_FIXES.md). Statements about missing wiring, failing tests, paths or deadlines below may describe the earlier revision.

# Runtime audit

## Target and conclusion

The repository's challenge traceability document, `design-docs/PHASE1-ANALYSIS.md`
R-57 (§5 of the handout), records **under five minutes on a standard machine for a
typical website**. This audit uses that recorded requirement; the original handout
is not present in the repository.

Measured workloads are comfortably below 300 seconds. This is **not a hard
worst-case guarantee**: trickling/unbounded responses, oversized documents and
non-interruptible work can still exceed it. The declared stage budgets sum to
**310 seconds**, and detector/report deadlines are not enforced. No threshold or
sampling change was made merely to obtain a faster benchmark.

## Measurements

Python 3.12.13, local arm64 machine, optional Chromium installed. Measurements
include cProfile overhead; they are single-run engineering comparisons, not a
statistical benchmark or a simulation of slow public internet access.

| Workload | Before | After | Unchanged scope and output |
|---|---:|---:|---|
| CPU-only synthetic audit, 30 distinct ~17 KB pages | 4.929 s; 1,290 HTML parses | 1.953 s; 358 parses | 30 pages; 5 findings, same check IDs and severity counts; no skill failures |
| Loopback `large-site`, real Chromium | 13.843 s; 1,304 parses | 11.248 s; 374 parses | 30 raw pages, 8 renders, 4 template clusters, 39 requests, 2 findings, same check IDs and severity counts |

The CPU profiling pass before optimization attributed about **4.03 of 4.89 seconds**
to BeautifulSoup construction; common extraction helpers accounted for **962** of
the 1,290 parse operations. Parsing, not model inference, was the dominant CPU cost.
The browser fixture improved about **19%**; CPU-only execution improved about **60%**.

Use `tests/harness/benchmark_runtime.py` to reproduce. `--baseline` disables the
parse cache and browser-process reuse, leaving other current code in place. It is
an ablation of those optimizations, not a checkout of the old repository. The
recorded browser baseline preceded the redundant-sleep and timeout-wiring fixes.

```sh
python tests/harness/benchmark_runtime.py --baseline
python tests/harness/benchmark_runtime.py
python tests/harness/benchmark_runtime.py --fixture large-site --baseline
python tests/harness/benchmark_runtime.py --fixture large-site
python tests/harness/run_corpus.py
```

The CPU-only workload injects responses: its 30 page observations are **not** 30
network requests. The browser workload uses real loopback HTTP. Browser and fixture
startup dependencies are required only for the latter commands.

## Cost and risk assessment

| Area | Actual behavior | Risk / decision |
|---|---|---|
| Number of requests | Default maximum 30 raw pages plus robots preflight and up to 8 rendered navigations, redirect hops and page resources. Shared safety boundary caps admitted HTTP requests at 200. The measured large site used 39 = 1 robots + 30 raw + 8 rendered. | Moderate: resource-heavy pages can exhaust the cap before all renders. Report `network_requests`, not the legacy `requests_made` raw-page counter, for network load. No cap reduction. |
| Repeated requests | All 8 rendered sample URLs were fetched twice, once per lens. BFS deduplicates exact URLs after fragment removal. Redirect aliases, query variants and assets across isolated contexts may repeat. HTTP uses a fresh session per request. | Raw/render duplication is necessary evidence. Do not replace rendered navigation with cached raw HTML, merge potentially meaningful queries, or share cookies to save handshakes. Connection pooling and HTTP caching were not introduced without demonstrated benefit and semantics tests. |
| Crawl breadth | Sequential same-host BFS, 30-page maximum, frontier normally 180 URLs; raw crawl stage 90 s. Render sample is stratified by URL-template cluster, up to 8 pages. The concurrency setting of 4 is an upper-bound declaration, not actual four-way crawling. | Calendar/faceted-query spaces can consume breadth. Existing caps constrain exploration, not every downstream CPU operation. Breadth and template-diverse rendering were preserved; more concurrency would risk pacing violations without a scheduler. |
| Rendering | Previously a browser launch for capability probing plus a new process for every sampled page (up to 9 launches). Now one process per collection pass and a separate, closed context for each page. Network-idle readiness and the usual 15 s navigation limit remain. | High on script-heavy sites: resources, long polling and large DOMs. No script/image/style blocking added for speed, no early DOM snapshot, and no rendered checks removed. Policy-blocked resources remain coverage gaps, as before. |
| LLM calls | **Zero** in the current pipeline. Classification is deterministic; external corroboration is unavailable. The documented 14-call/45-second model plans do not describe executed work. | No unnecessary calls to optimize. If integrations are enabled later, the stage budgets must be rebalanced below 300 s with a shared deadline. |
| Expensive parsing | Same HTML was reparsed by metadata, canonical, text, links, JSON-LD and inventory extraction across multiple checks. Mutating detector parsers still need their own trees. | High CPU cost, optimized with audit-local reuse of private read-only trees. Large inputs beyond cache capacity are still processed in full, without retention or truncation. |
| External lookups | One origin robots preflight; raw/render requests only. No live model/search/corroboration, remote schema expansion or separate sitemap fetch is wired into the collector. | No lookup fan-out to remove. These unavailable capabilities are coverage limitations, not performance successes. |
| Worst case | HTTP connect/read timeouts are not absolute response deadlines. Full bodies and DOMs are materialized. Parsing, browser lifecycle and report processing are not killable through the existing Budget API. Robots rule sets can also be arbitrarily large/complex. | **Largest unresolved risk.** A malicious slow stream or huge body can exceed five minutes or memory limits. A hard process/egress deadline with explicit coverage loss needs separate engineering; this pass does not claim to solve it by silently truncating evidence. |

## Implemented optimizations and accuracy guards

1. **Audit-local parse reuse** — `lib/common/extract.py`, activated at `run_audit`.
   An LRU retains at most 64 private trees and 1,048,576 source characters, clears
   at audit exit, and is context-local. Those are cache limits, not content limits
   or a strict heap-size bound. Public extraction results do not expose mutable
   cached attributes. Tests cover text, canonical metadata, links relative to
   different origins, JSON-LD, inventory, mutation isolation, eviction and full
   extraction of oversized inputs. Four defect fixtures produce **exactly equal
   cached and uncached reports**, not just equal finding counts.
2. **Browser-process reuse** — `lib/site_observer/render.py` and `collect.py`.
   Capability probing and renders share a process, but not contexts, page state,
   cookies or navigation history. Contexts close per page; the process and driver
   close even when collection raises. A regression checks one launch, distinct
   contexts, successful rendered HTML and cleanup; existing request-policy tests
   still exercise interception and incomplete-DOM rejection.
3. **Single pacing boundary** — the collector no longer adds a page-loop sleep
   on top of the shared request limiter. The existing minimum interval still
   applies to actual raw, redirect and browser requests. A fake-clock regression
   verifies that a response already slower than the interval causes no extra
   sleep, while existing tests retain positive-delay and crawl-delay enforcement.
4. **Use remaining stage time** — raw redirect hops receive the smaller of the
   configured HTTP timeout and remaining stage time. The collector now honors
   its HTTP/robots timeout configuration and bounds render navigation timeout by
   the remaining render-stage allowance. Tests cover shrinking redirect timeouts,
   custom HTTP limits and preservation of the complete sample within a short
   stage. These checks improve deadline behavior without pretending to enforce a
   hard total runtime or interrupt a trickling response.

No mandatory dependency, LLM call, external lookup, new detector or site-specific
rule was added. Earlier user changes were preserved.

## Verification

Final full suite: **389 passed**, including **11 new performance regressions**.
All **19 real-browser fixtures passed**: 27/27 scored check presences, 34 findings,
zero measured FP/FN and guardrail violations. No fixture expectations were changed.
Unprofiled corpus audits took **0.224–10.955 s**, median **3.314 s**, with summed
audit time **72.903 s** (excluding test-server shutdown between fixtures). The
slowest audit was `large-site`: 30 raw pages, 8 renders and 39 requests.

`tests/test_performance.py` contains the new correctness and operation-count
regressions. Timing thresholds are deliberately not unit-test assertions: host
load would make those flaky. The corpus harness now records per-audit `elapsed_s`
alongside its existing correctness results in `tests/harness/results.json`.

Test commands used this session's isolated dependencies:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/brand-audit-test-deps /opt/homebrew/bin/python3.12 -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/brand-audit-test-deps PLAYWRIGHT_BROWSERS_PATH=/private/tmp/brand-audit-browsers /opt/homebrew/bin/python3.12 tests/harness/run_corpus.py
```

The temporary paths are local test-environment locations, not project dependencies.
Synthetic corpus FP/FN scores exclude documented untestable/known-missing cases;
passing them protects existing behavior but does not prove unseen-site accuracy.
