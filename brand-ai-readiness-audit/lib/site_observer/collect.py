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
from lib.common.network_policy import RequestPolicy
from lib.common.observations import make_observation
from lib.common.robots import fetch_robots, robots_allows
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
    Unreachable/unparseable policy stops crawling; path exclusions are
    evaluated individually, including explicitly allowed deep paths."""
    status = robots.get("status")
    if status in ("error", "unparseable"):
        return {"reason": "ROBOTS_DISALLOWED", "detail": f"robots.txt {status}"}
    # Root denial does not imply denial of an explicitly allowed deep URL.
    # Every requested/discovered path is checked by crawl(), including the seed.
    return None


@render_mod.reuse_browser
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

    budget = budget or Budget()
    now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
    sleep = sleep or _time_mod.sleep

    seed_url = _normalize_url(url)
    origin = _origin(seed_url)
    policy = RequestPolicy(seed_url, sleep=sleep, delay=budget.polite_delay_s())
    fetch = fetch or (lambda target: fetch_url(target, timeout=budget.config["raw_crawl_timeout_s"], policy=policy))
    robots_fetcher = robots_fetcher or (lambda target: fetch_robots(target, timeout=budget.config["robots_preflight_s"], policy=policy))
    coverage: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []

    budget.start_stage("robots_preflight")
    policy.time_left = lambda: budget.stage_time_left_s("robots_preflight", "robots_preflight_s")
    robots = robots_fetcher(origin)
    policy.robots = robots
    groups = robots.get("document", {}).get("groups", [])
    selected = [g for g in groups if g.get("user_agent", "").lower() == "brand-ai-readiness-audit"] or [g for g in groups if g.get("user_agent") == "*"]
    policy.delay = max([policy.delay] + [g.get("crawl_delay", 0) for g in selected])
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
        policy.time_left = lambda: budget.stage_time_left_s("raw_crawl", "raw_crawl_s")

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
            # The shared boundary paces actual requests (including redirects).
            # An additional page-loop sleep wastes time after slow responses.
            polite_delay_s=0,
            sleep=sleep,
        )
        pages = crawl_result["pages"]
        clusters = crawl_result["clusters"]
        if crawl_result["skipped_safety"]:
            coverage.append({"check_id": "X-COV-01", "status": "skipped", "reason": "NETWORK_POLICY",
                             "detail": f"{len(crawl_result['skipped_safety'])} action/credential/ambiguous URLs excluded",
                             "scope": "unsafe discovered targets; not a site defect"})

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
            if result.get("evidence", {}).get("coverage_gap"):
                coverage.append({"check_id": "X-COV-01", "status": "failed", "reason": "NETWORK_POLICY",
                                 "detail": "Transport did not produce complete evidence: " + result["evidence"].get("error", "unknown"),
                                 "scope": page_url})

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
            policy.time_left = lambda: budget.stage_time_left_s("render_sample", "render_sample_s")
            eligible = {shape: [url for url in urls if pages[url].get("status_code") is not None
                               and 200 <= pages[url]["status_code"] < 300 and pages[url].get("html")]
                        for shape, urls in clusters.items()}
            sample_urls = stratified_sample(eligible, budget.config["render_sample_max_pages"])
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
                rendered = render_mod.render_page(pages[page_url].get("final_url") or page_url,
                    timeout_ms=max(1, min(15000, int(policy.time_left() * 1000))),
                    capability=render_capability, policy=policy)
                budget.record_render()
                observations.append(make_observation("RENDER", page_url, rendered))
                if rendered.get("status") != "ok":
                    coverage.append({"check_id": "X-COV-01", "status": "failed", "reason": "RENDER_FAILED", "detail": rendered.get("reason"), "scope": page_url})
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

    if policy.blocked or policy.stopped:
        coverage.append({"check_id": "X-COV-01", "status": "partial", "reason": "NETWORK_POLICY", "detail": f"{len(policy.blocked)} request(s) blocked; origin backoff={policy.stopped}", "scope": "restricted redirects/resources; not proof of a site defect"})
    scope = {
        "archetype": store["archetype"],
        "pages_crawled": len(pages),
        "pages_rendered": sum(1 for obs in observations if obs["type"] == "RENDER"),
        "template_clusters": len(clusters),
        "disallowed": degradation is not None or not robots_allows(robots, urlparse(seed_url).path + ("?" + urlparse(seed_url).query if urlparse(seed_url).query else "")),
    }

    return {"store": store, "coverage": coverage, "budget": {**budget.snapshot(), "network_requests": policy.requests}, "scope": scope}


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
