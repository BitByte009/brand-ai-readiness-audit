"""Drives one complete observation pass and returns the store plus coverage.
The only component the orchestrator calls to touch the network.

Inputs:  url, budget, capabilities
Outputs: store + coverage
Nature:  deterministic orchestration

PROJECT_CONTEXT.md D-2: crawl once, analyse many. Every detector skill reads
the store this returns and never re-fetches (D-6). This module owns the
*order* of operations (robots before any page fetch, raw crawl before any
render, at most one collection pass) but contains no check logic of its own.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from lib.common.budget import Budget
from lib.common.http_client import fetch_url
from lib.common.observations import make_observation
from lib.common.robots import fetch_robots, is_disallow_all
from lib.site_observer import classify as classify_mod
from lib.site_observer import render as render_mod
from lib.site_observer.crawl import crawl, stratified_sample

STORE_VERSION = "1.0"


def _normalize_url(url: str) -> str:
    """Add a scheme if the operator gave a bare host, without touching the
    path -- the crawl seed must stay the exact URL requested (a deep page
    audits that page, not the homepage it happens to share an origin with)."""
    return url if urlparse(url).scheme else f"https://{url}"


def _origin(normalized_url: str) -> str:
    """robots.txt is always at the origin root regardless of what path was
    requested; this is only ever used to build the robots.txt URL and the
    audited-host record, never as the crawl seed."""
    parsed = urlparse(normalized_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _robots_degradation(robots: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """None if crawling may proceed; otherwise a coverage-ready reason.
    degraded-mode.md: disallow-all and unreachable/unparseable both stop the
    raw crawl before it starts -- the only difference is *why*."""
    status = robots.get("status")
    if status in ("error", "unparseable"):
        return {"reason": "ROBOTS_DISALLOWED", "detail": f"robots.txt {status}"}
    if is_disallow_all(robots):
        return {"reason": "ROBOTS_DISALLOWED", "detail": "robots.txt disallows all paths"}
    return None


def collect(
    url: str,
    budget: Optional[Budget] = None,
    fetch: Optional[Callable[[str], Dict[str, Any]]] = None,
    robots_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
    render_capability: Optional[Dict[str, Any]] = None,
    now: Optional[Callable[[], datetime.datetime]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> Dict[str, Any]:
    """Run exactly one collection pass and return `(store, coverage)`.

    `fetch`/`robots_fetcher` default to the real network client but are
    injectable so tests never touch a socket. Never raises: an unreachable
    origin or a fully-disallowed robots.txt still returns a schema-shaped,
    if mostly empty, store plus a coverage entry explaining why."""
    import time as _time_mod

    fetch = fetch or fetch_url
    robots_fetcher = robots_fetcher or fetch_robots
    budget = budget or Budget()
    now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
    sleep = sleep or _time_mod.sleep

    seed_url = _normalize_url(url)
    origin = _origin(seed_url)
    coverage: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []

    budget.start_stage("robots_preflight")
    robots = robots_fetcher(origin)
    robots_obs = make_observation("ROBOTS", robots.get("url", origin), robots)
    observations.append(robots_obs)

    degradation = _robots_degradation(robots)
    audited_host = urlparse(origin).netloc
    pages: Dict[str, Dict[str, Any]] = {}
    clusters: Dict[str, List[str]] = {}

    if degradation is not None:
        coverage.append(
            {
                "check_id": "X-COV-01",
                "status": "skipped",
                "reason": degradation["reason"],
                "detail": degradation["detail"],
                "scope": "all raw-crawl and rendered-lens checks",
            }
        )
    else:
        budget.start_stage("raw_crawl")

        def _on_page_fetched(_url: str, _result: Dict[str, Any]) -> None:
            budget.record_page_fetch()

        crawl_result = crawl(
            seed_url,
            fetch=fetch,
            robots=robots,
            max_pages=budget.config["raw_crawl_max_pages"],
            time_left=lambda: budget.stage_time_left_s("raw_crawl", "raw_crawl_s"),
            can_fetch_more=budget.can_fetch_page,
            on_page_fetched=_on_page_fetched,
            polite_delay_s=budget.polite_delay_s(),
            sleep=sleep,
        )
        pages = crawl_result["pages"]
        clusters = crawl_result["clusters"]

        seed_result = pages.get(seed_url)
        if seed_result and seed_result.get("final_url"):
            resolved_host = urlparse(seed_result["final_url"]).netloc
            if resolved_host and resolved_host != audited_host:
                audited_host = resolved_host

        if crawl_result["skipped_robots"]:
            coverage.append(
                {
                    "check_id": "X-COV-01",
                    "status": "partial",
                    "reason": "ROBOTS_DISALLOWED",
                    "detail": f"{len(crawl_result['skipped_robots'])} discovered path(s) skipped by robots.txt",
                    "scope": "the specific disallowed paths, not the whole site",
                }
            )
        if budget.stage_exceeded("raw_crawl", "raw_crawl_s") or not budget.can_fetch_page():
            coverage.append(
                {
                    "check_id": "X-COV-01",
                    "status": "partial",
                    "reason": "BUDGET_EXHAUSTED",
                    "detail": f"raw crawl stopped at {len(pages)} page(s)",
                    "scope": "pages beyond the crawl budget",
                }
            )

        for page_url, result in pages.items():
            observations.append(make_observation("HTTP_FETCH", page_url, result))

        if len(pages) < 3:
            coverage.append(
                {
                    "check_id": "X-COV-01",
                    "status": "skipped",
                    "reason": "INSUFFICIENT_PAGES",
                    "detail": f"only {len(pages)} page(s) discoverable",
                    "scope": "cross-page checks",
                }
            )

    render_capability = render_capability if render_capability is not None else render_mod.detect_capability()
    if degradation is None and pages:
        if render_capability.get("available"):
            budget.start_stage("render_sample")
            sample_urls = stratified_sample(clusters, budget.config["render_sample_max_pages"])
            for page_url in sample_urls:
                if budget.stage_exceeded("render_sample", "render_sample_s") or not budget.can_render_page():
                    coverage.append(
                        {
                            "check_id": "X-COV-01",
                            "status": "partial",
                            "reason": "BUDGET_EXHAUSTED",
                            "detail": "render sample stopped early",
                            "scope": "remaining rendered-lens pages",
                        }
                    )
                    break
                rendered = render_mod.render_page(page_url, capability=render_capability)
                budget.record_render()
                observations.append(make_observation("RENDER", page_url, rendered))
        else:
            coverage.append(
                {
                    "check_id": "X-COV-01",
                    "status": "skipped",
                    "reason": "RENDERER_UNAVAILABLE",
                    "detail": render_capability.get("reason", "RENDERER_UNAVAILABLE"),
                    "scope": "D-RENDER checks and the rendered lens of E-* checks",
                }
            )

    store: Dict[str, Any] = {
        "store_version": STORE_VERSION,
        "collected_at": now().isoformat(),
        "target": {
            "requested_url": url,
            "requested_host": urlparse(origin).netloc,
            "audited_host": audited_host,
            "origin": origin,
        },
        "capabilities": {
            "renderer": render_capability,
            "corroboration": {"available": False, "reason": "MODEL_UNAVAILABLE"},
        },
        "archetype": classify_mod.classify_archetype({"observations": observations}),
        "observations": observations,
    }

    from lib.site_observer import probe as probe_mod

    probe_capability = probe_mod.detect_capability()
    if not probe_capability.get("available"):
        coverage.append(
            {
                "check_id": "X-COV-01",
                "status": "skipped",
                "reason": "SEARCH_UNAVAILABLE",
                "detail": probe_capability.get("reason", "MODEL_UNAVAILABLE"),
                "scope": "D-ENTITY-03 and D-TRUST-05 corroboration checks",
            }
        )

    scope = {
        "archetype": store["archetype"],
        "pages_crawled": len(pages),
        "pages_rendered": sum(1 for obs in observations if obs["type"] == "RENDER"),
        "template_clusters": len(clusters),
        "disallowed": degradation is not None,
    }

    return {"store": store, "coverage": coverage, "budget": budget.snapshot(), "scope": scope}


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
