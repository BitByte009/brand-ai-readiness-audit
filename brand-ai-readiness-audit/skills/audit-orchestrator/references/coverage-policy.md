# Coverage policy

Core principle: **a check that could not run must never look like a check that passed.**

The report carries a top-level `coverage` block, separate from findings, recording
known skipped, restricted or failed work. It is not a per-check execution ledger.

Reason codes: ROBOTS_DISALLOWED, RENDERER_UNAVAILABLE, SEARCH_UNAVAILABLE,
BUDGET_EXHAUSTED, INSUFFICIENT_PAGES, LANGUAGE_UNSUPPORTED, AUTH_REQUIRED,
CHALLENGE_DETECTED, FETCH_FAILED. Collection also records NETWORK_POLICY and
RENDER_FAILED; orchestration records SKILL_FAILED and EVIDENCE_UNRESOLVED.
Some taxonomy-level reason codes are reserved and not emitted by every collector.

Coverage entries are never counted in `summary` severity counts. X-COV-01 is a
bookkeeping ID, not a finding ID.
