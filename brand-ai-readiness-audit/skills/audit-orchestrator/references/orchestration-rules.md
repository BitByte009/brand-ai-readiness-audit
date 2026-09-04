# Orchestration rules

1. Exactly one observation pass. No skill re-fetches. Runtime and rate-abuse both
   depend on this.
2. Detectors are pure functions over an immutable store and may run in any order.
3. The orchestrator never assigns severity and never runs a check.
4. Evidence-binding validation runs after scoring and before schema validation.
   Any finding citing an unresolvable observation ID is dropped and logged.
5. A report is always emitted. See degraded-mode.md.

## Budget (target: full audit < 5 minutes)
| Stage | Budget |
|---|---|
| robots + preflight | 10s |
| raw crawl | 90s, <=30 pages, concurrency <=4, 10s timeout, polite delay |
| render sample | 90s, 6-8 pages by template diversity |
| corroboration | 45s, hard cap |
| detectors + scoring | 60s |
| report + validation | 15s |

## Model-call budget: <= 14 per audit
8 probe (one batched call per rendered page), 1 classification, 4 detector
interpretation, 1 report prose. Enforced in `<marketplace-root>/lib/common/budget.py`.
