"""Shared helpers for the three crawl-render-audit detectors.

Not a public script (no CLI entrypoint). `detect_crawl.py`, `detect_render.py` and
`detect_extract.py` each add this file's directory to `sys.path` and import from it
directly, since the parent skill directory's hyphenated name makes it an invalid
Python package path. See `references/store-contract.md` for the observation shapes
referenced here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
for _path in (str(SCRIPTS_DIR), str(MARKETPLACE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Shared mechanics, re-exported for the existing detector interfaces.
from lib.common.observations import http_fetches, iter_type, page_classifications, probes, renders, single
from lib.common.findings import affected_block, make_finding

SHORT_PAGE_TEXT_FLOOR = 400

# Structural, not brand/CMS/vertical-specific: generic path verbs and any query string.
_UTILITY_SEGMENT_RE = re.compile(
    r"^(cart|checkout|search|login|logout|signin|signup|register|account|"
    r"wishlist|admin|basket|my-account)(/|$)",
    re.IGNORECASE,
)

RECOGNIZED_AI_BOTS = {
    "gptbot",
    "chatgpt-user",
    "google-extended",
    "openai-bot",
    "perplexitybot",
    "ccbot",
    "claudebot",
    "anthropic-ai",
}


def is_utility_path(url: str) -> bool:
    """True for cart/search/checkout/login/account/admin/wishlist paths or any URL
    carrying a query string -- disallowing or excluding these is correct practice,
    never a discoverability defect (see fp-guardrails.md)."""
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    return any(_UTILITY_SEGMENT_RE.fullmatch(re.sub(r"\.(?:html?|php|aspx?)$", "", segment, flags=re.I))
               for segment in path.split('/'))


def registrable_host(value: str) -> str:
    """Best-effort same-site host comparison: lowercase netloc, port stripped,
    leading 'www.' stripped. Accepts either a full URL or a bare host string. Not a
    full public-suffix resolution -- sufficient for same-domain-vs-cross-domain
    distinctions this skill needs."""
    if "://" in value:
        netloc = (urlparse(value).netloc or "").lower()
    else:
        netloc = value.lower().split("/")[0]
    netloc = netloc.split(":")[0]
    return netloc[4:] if netloc.startswith("www.") else netloc


_NUMERIC_SEGMENT_RE = re.compile(r"^\d+$")
_SLUG_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+){2,}$", re.IGNORECASE)
_SEGMENT_EXTENSION_RE = re.compile(r"^(.*)(\.[A-Za-z0-9]{1,8})$")


def cluster_key(url: str) -> str:
    """Local template-shape fallback used when the store carries no
    `template_clusters`. Numeric and long slug/id path segments collapse to `*` so
    `/blog/2024/my-post-title` and `/blog/2023/another-post` key identically.

    A trailing file extension (e.g. /product/123.html) is stripped before the
    id/slug patterns are tested and reattached after, so "123.html" is seen as
    the numeric id "123" rather than a never-matching literal -- otherwise the
    most common real templated-URL shape (numeric id immediately followed by
    an extension in the same path segment) would never cluster, silently
    defeating the one-finding-per-template-cluster aggregation this function
    exists to provide."""
    path = urlparse(url).path or "/"
    segments = [seg for seg in path.split("/") if seg]
    shaped = []
    for seg in segments:
        ext_match = _SEGMENT_EXTENSION_RE.match(seg)
        stem, ext = (ext_match.group(1), ext_match.group(2)) if ext_match else (seg, "")
        if _NUMERIC_SEGMENT_RE.match(stem) or _SLUG_SEGMENT_RE.match(stem):
            shaped.append("*" + ext)
        else:
            shaped.append(seg)
    return "/" + "/".join(shaped)


def group_by_cluster(store: Dict[str, Any], urls: Iterable[str]) -> Dict[str, List[str]]:
    """Group URLs by `template_clusters` from the store when present, else by the
    local `cluster_key` fallback (D-7: finding unit is (check_id, template_cluster))."""
    urls = list(urls)
    declared = store.get("template_clusters")
    if declared:
        lookup: Dict[str, str] = {}
        for cluster in declared:
            for u in cluster.get("urls", []):
                lookup[u] = cluster.get("cluster_id", cluster_key(u))
        grouped: Dict[str, List[str]] = {}
        for u in urls:
            key = lookup.get(u, cluster_key(u))
            grouped.setdefault(key, []).append(u)
        return grouped

    grouped = {}
    for u in urls:
        grouped.setdefault(cluster_key(u), []).append(u)
    return grouped
