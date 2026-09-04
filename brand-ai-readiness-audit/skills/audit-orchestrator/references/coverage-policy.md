# Coverage policy

Core principle: **a check that could not run must never look like a check that passed.**

The report carries a top-level `coverage` block, not findings, listing every check
that was attempted, skipped or failed, with a reason code.

Reason codes: ROBOTS_DISALLOWED, RENDERER_UNAVAILABLE, SEARCH_UNAVAILABLE,
BUDGET_EXHAUSTED, INSUFFICIENT_PAGES, LANGUAGE_UNSUPPORTED, AUTH_REQUIRED,
CHALLENGE_DETECTED, FETCH_FAILED.

Coverage entries are never counted in `summary` severity counts. X-COV-01 is a
bookkeeping ID, not a finding ID.
