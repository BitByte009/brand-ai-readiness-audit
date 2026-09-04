"""Enforces time, page, request, concurrency and model-call budgets in code
rather than in prose instructions.

Inputs:  budget config (see skills/audit-orchestrator/references/orchestration-rules.md)
Outputs: a Budget object other components consult before doing more work
Nature:  deterministic

Every limit here is a *check*, never a raise: budget exhaustion is a normal,
expected outcome (a slow or huge site) that must degrade to a coverage entry
(BUDGET_EXHAUSTED), not a crash. Callers ask `budget.can_fetch_page()` /
`budget.stage_time_left(...)` before doing more work and stop politely when
either goes false.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

# orchestration-rules.md's published budget table.
DEFAULT_BUDGET: Dict[str, Any] = {
    "robots_preflight_s": 10,
    "raw_crawl_s": 90,
    "raw_crawl_max_pages": 30,
    "raw_crawl_concurrency": 4,
    "raw_crawl_timeout_s": 10,
    "raw_crawl_polite_delay_s": 0.2,
    "render_sample_s": 90,
    "render_sample_max_pages": 8,
    "corroboration_s": 45,
    "detectors_scoring_s": 60,
    "report_validation_s": 15,
    "model_calls_max": 14,
}


class Budget:
    """Tracks elapsed time per named stage plus page/request/model-call
    counters against `DEFAULT_BUDGET`, overridable per audit via `config`."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, clock=time.monotonic) -> None:
        self.config: Dict[str, Any] = {**DEFAULT_BUDGET, **(config or {})}
        self._clock = clock
        self._stage_started_at: Dict[str, float] = {}
        self.pages_fetched = 0
        self.requests_made = 0
        self.render_pages_done = 0
        self.model_calls_made = 0

    # -- stage timing ---------------------------------------------------

    def start_stage(self, name: str) -> None:
        self._stage_started_at[name] = self._clock()

    def stage_elapsed_s(self, name: str) -> float:
        start = self._stage_started_at.get(name)
        if start is None:
            return 0.0
        return self._clock() - start

    def stage_time_left_s(self, name: str, budget_key: str) -> float:
        limit = self.config.get(budget_key, 0)
        return max(0.0, limit - self.stage_elapsed_s(name))

    def stage_exceeded(self, name: str, budget_key: str) -> bool:
        return self.stage_time_left_s(name, budget_key) <= 0

    # -- page / request counters ----------------------------------------

    def can_fetch_page(self) -> bool:
        return self.pages_fetched < self.config["raw_crawl_max_pages"]

    def record_page_fetch(self) -> None:
        self.pages_fetched += 1
        self.requests_made += 1

    def can_render_page(self) -> bool:
        return self.render_pages_done < self.config["render_sample_max_pages"]

    def record_render(self) -> None:
        self.render_pages_done += 1

    # -- model-call counter ----------------------------------------------

    def can_call_model(self) -> bool:
        return self.model_calls_made < self.config["model_calls_max"]

    def record_model_call(self) -> None:
        self.model_calls_made += 1

    # -- politeness --------------------------------------------------------

    def polite_delay_s(self) -> float:
        return self.config["raw_crawl_polite_delay_s"]

    def snapshot(self) -> Dict[str, Any]:
        """Budget consumption for the report's `run` block."""
        return {
            "pages_fetched": self.pages_fetched,
            "requests_made": self.requests_made,
            "render_pages_done": self.render_pages_done,
            "model_calls_made": self.model_calls_made,
            "model_calls_max": self.config["model_calls_max"],
        }


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
