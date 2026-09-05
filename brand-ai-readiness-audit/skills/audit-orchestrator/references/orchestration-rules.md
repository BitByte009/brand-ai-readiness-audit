# Orchestration rules

1. Exactly one observation pass. No skill re-fetches. Runtime and rate-abuse both
   depend on this.
2. Detectors are pure functions over an immutable store and may run in any order.
3. The orchestrator never assigns severity and never runs a check.
4. Evidence-binding validation runs after scoring and before schema validation.
   Any finding citing an unresolvable observation ID is dropped and logged.
5. Expected partial runs carry coverage. Unexpected lifecycle errors can still
   prevent emission; inspect schema_valid and skill_failures, not just exit status.
   See [degraded mode](degraded-mode.md).

## Budget (target: full audit < 5 minutes)
| Stage | Budget |
|---|---|
| robots + preflight | 10s |
| raw crawl | 90s, <=30 pages, concurrency <=4, 10s timeout, polite delay |
| render sample | 90s, 6-8 pages by template diversity |
| corroboration | 45s, hard cap |
| detectors + scoring | 60s |
| report + validation | 15s |

## Current implementation versus planning allowances

The table is a planning allocation, not a hard end-to-end deadline; it totals
310 seconds. Raw crawling is sequential and rendering samples at most eight pages.
Detector/report work is not interruptible through the Budget API. Read the
[performance audit](../../../PERFORMANCE_AUDIT.md) before making runtime guarantees.

There are currently **zero model/search calls**. The 14-call allowance in
[Budget](../../../lib/common/budget.py) reserves 8 probes, 1 classification,
4 detector interpretations and 1 report call for a future integration; it does
not mean those calls are implemented or should be issued by the invoking agent.
