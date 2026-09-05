"""Raw-lens crawl with template clustering and stratified sampling. Discovery
from the link graph only (a sitemap, if declared, is folded in by the caller
once fetched) -- never guesses URL patterns that were never actually linked.

Inputs:  origin, an injected page fetcher, robots, budget
Outputs: page records, link graph, template clusters
Nature:  deterministic

The fetcher is injected (never `requests` called directly here) so this
module has no network dependency of its own and every path is exercised in
tests without touching a socket.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

from lib.common.extract import extract_links
from lib.common.robots import robots_allows
from lib.common.network_policy import unsafe_target

_NUMERIC_SEGMENT_RE = re.compile(r"^\d+$")
_HEX_ID_RE = re.compile(r"^[0-9a-f]{8,}$", re.IGNORECASE)
_UUID_LIKE_RE = re.compile(r"^[0-9a-f-]{20,}$", re.IGNORECASE)
_SEGMENT_EXTENSION_RE = re.compile(r"^(.*)(\.[A-Za-z0-9]{1,8})$")


def registrable_host(url_or_host: str) -> str:
    """A small, local notion of "same site" (strip scheme/port/www) -- not a
    full public-suffix-list implementation, which this crawler's same-host
    scoping does not need."""
    host = urlparse(url_or_host).netloc or url_or_host
    host = host.split("@")[-1].split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def template_shape(path: str) -> str:
    """Collapse id-shaped path segments to '#' so /product/123 and
    /product/456 cluster as one template: /product/#. This is the raw-lens
    input to the finding unit's `(check_id, template_cluster)` grouping
    (PROJECT_CONTEXT.md D-7).

    A trailing file extension (e.g. /product/123.html) is stripped before
    the id patterns are tested and reattached after, so the numeric/hex/uuid
    match sees "123" rather than the never-matching "123.html" -- otherwise
    the most common real templated-URL shape (numeric id immediately
    followed by an extension in the same path segment) would never cluster."""
    segments = (path or "/").split("/")
    shaped = []
    for seg in segments:
        ext_match = _SEGMENT_EXTENSION_RE.match(seg)
        stem, ext = (ext_match.group(1), ext_match.group(2)) if ext_match else (seg, "")
        if _NUMERIC_SEGMENT_RE.match(stem) or _HEX_ID_RE.match(stem) or _UUID_LIKE_RE.match(stem):
            shaped.append("#" + ext)
        else:
            shaped.append(seg)
    return "/".join(shaped) or "/"


def crawl(
    origin: str,
    fetch: Callable[[str], Dict[str, Any]],
    robots: Optional[Dict[str, Any]] = None,
    max_pages: int = 30,
    max_frontier: Optional[int] = None,
    time_left: Callable[[], float] = lambda: float("inf"),
    can_fetch_more: Callable[[], bool] = lambda: True,
    on_page_fetched: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    polite_delay_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """Same-host BFS crawl, bounded by `max_pages`, `time_left()` (stage
    budget, polled between fetches) and `can_fetch_more()` (a page-count
    budget hook). `robots` gates every URL, including the seed, exactly the
    same way -- a disallowed origin yields zero pages, never a special-cased
    exception for "the one the operator asked about".

    `polite_delay_s`, applied between fetches (never before the first or
    after the last), is how "no rate abuse" is actually enforced rather than
    just documented -- `sleep` is injectable so tests exercise the delay
    logic without a real test suite run taking minutes."""
    host = registrable_host(origin)
    max_frontier = max_frontier if max_frontier is not None else max_pages * 6
    queue = deque([origin])
    seen: Set[str] = {origin}
    pages: Dict[str, Dict[str, Any]] = {}
    link_graph: Dict[str, Set[str]] = {}
    skipped_robots: List[str] = []
    skipped_safety: List[str] = []

    while queue and len(pages) < max_pages and time_left() > 0 and can_fetch_more():
        url = queue.popleft()
        if unsafe_target(url):
            skipped_safety.append(url)
            continue
        path = urlparse(url).path or "/"
        if urlparse(url).query:
            path += "?" + urlparse(url).query
        if robots is not None and not robots_allows(robots, path):
            skipped_robots.append(url)
            continue

        if pages and polite_delay_s > 0:
            sleep(polite_delay_s)

        result = fetch(url)
        pages[url] = result
        if on_page_fetched:
            on_page_fetched(url, result)

        status = result.get("status_code", 200)
        if status is None or not 200 <= status < 300:
            continue  # Do not explore authentication/error-page links.

        html = (result or {}).get("html", "")
        if not html:
            continue
        for link in extract_links(html, base_url=result.get("final_url") or url):
            href = link["href"]
            if link.get("unsafe_action"):
                skipped_safety.append(href)
                continue
            parsed = urlparse(href)
            if parsed.scheme not in ("http", "https") or registrable_host(href) != host:
                continue
            normalized = href.split("#")[0]
            link_graph.setdefault(normalized, set()).add(url)
            if normalized not in seen and len(seen) < max_frontier:
                seen.add(normalized)
                queue.append(normalized)

    clusters: Dict[str, List[str]] = {}
    for url in pages:
        clusters.setdefault(template_shape(urlparse(url).path), []).append(url)

    return {
        "pages": pages,
        "link_graph": {url: sorted(sources) for url, sources in link_graph.items()},
        "clusters": {shape: sorted(urls) for shape, urls in clusters.items()},
        "skipped_robots": sorted(set(skipped_robots)),
        "skipped_safety": sorted(set(skipped_safety)),
    }


def stratified_sample(clusters: Dict[str, List[str]], sample_size: int) -> List[str]:
    """Pick up to `sample_size` URLs spreading across as many template
    clusters as possible (one per cluster first, then a second pass) rather
    than exhausting the budget on the largest cluster alone -- the rendered
    lens exists to catch cross-template gaps, so it should see every
    template at least once before it sees any template twice."""
    if sample_size <= 0:
        return []
    ordered_clusters = [sorted(urls) for _, urls in sorted(clusters.items())]
    sample: List[str] = []
    round_index = 0
    while len(sample) < sample_size and any(round_index < len(urls) for urls in ordered_clusters):
        for urls in ordered_clusters:
            if len(sample) >= sample_size:
                break
            if round_index < len(urls):
                sample.append(urls[round_index])
        round_index += 1
    return sample


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
