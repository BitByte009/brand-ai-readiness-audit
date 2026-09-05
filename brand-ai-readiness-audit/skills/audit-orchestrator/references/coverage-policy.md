# Coverage policy

Core principle: **a check that could not run must never look like a check that passed.**

The report carries a top-level `coverage` block, separate from findings, recording
known skipped, restricted or failed work. It is not a per-check execution ledger.

Reason codes: ROBOTS_DISALLOWED, RENDERER_UNAVAILABLE, SEARCH_UNAVAILABLE,
BUDGET_EXHAUSTED, INSUFFICIENT_PAGES, LANGUAGE_UNSUPPORTED, AUTH_REQUIRED,
CHALLENGE_DETECTED, FETCH_FAILED, UNAVAILABLE_INSTRUMENT. Collection also records
NETWORK_POLICY and RENDER_FAILED; orchestration records SKILL_FAILED,
EVIDENCE_UNRESOLVED and UNAVAILABLE_INSTRUMENT.
Some taxonomy-level reason codes are reserved and not emitted by every collector.

## The three states a check can be in

The distinction the `coverage` block exists to preserve:

| State | Where it shows up |
|---|---|
| Evaluated, passed | no finding, no coverage entry |
| Evaluated, failed | a finding, with bound evidence |
| **Not evaluable** | a coverage entry naming the check IDs; never a finding |

`UNAVAILABLE_INSTRUMENT` is the third state. It is emitted by
`run_audit._unavailable_instrument_coverage`, which derives availability from the
observations actually collected rather than from a hardcoded flag — wire the
instrument and the entry disappears on its own. The entry names the specific
check IDs, not just the capability, because the check IDs are what a reader
would otherwise assume had passed. Entries are deduplicated on (reason, scope).

Coverage entries are never counted in `summary` severity counts. X-COV-01 is a
bookkeeping ID, not a finding ID.
