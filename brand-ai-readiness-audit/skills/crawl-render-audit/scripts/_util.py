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
    if parsed.query:
        return True
    path = parsed.path.lstrip("/")
    return bool(_UTILITY_SEGMENT_RE.match(path))


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


def iter_type(store: Dict[str, Any], observation_type: str) -> List[Dict[str, Any]]:
    return [obs for obs in store.get("observations", []) if obs.get("type") == observation_type]


def single(store: Dict[str, Any], observation_type: str) -> Optional[Dict[str, Any]]:
    matches = iter_type(store, observation_type)
    return matches[0] if matches else None


def http_fetches(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Map requested URL -> HTTP_FETCH observation, most-recent-wins on duplicates."""
    return {obs["source_url"]: obs for obs in iter_type(store, "HTTP_FETCH")}


def renders(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "RENDER")}


def page_classifications(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "PAGE_CLASSIFICATION")}


def probes(store: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {obs["source_url"]: obs for obs in iter_type(store, "PROBE")}


def affected_block(urls: List[str], total_in_scope: Optional[int] = None) -> Dict[str, Any]:
    unique = sorted(set(urls))
    return {
        "count": len(unique),
        "sample_urls": unique[:5],
        "total_in_scope": total_in_scope if total_in_scope is not None else len(unique),
    }


def make_finding(
    *,
    check_id: str,
    category: str,
    title: str,
    severity: str,
    confidence: str,
    mechanism: str,
    impact: str,
    observed_signal: str,
    evidence: str,
    observation_ids: List[str],
    source_urls: List[str],
    affected: Dict[str, Any],
    suggested_action: Dict[str, Any],
) -> Dict[str, Any]:
    """Build one unscored finding. `severity` is a proposed base severity per the
    taxonomy; final severity is `evidence-prioritization`'s job, never this skill's
    (SKILL.md: 'Explicitly NOT this skill's job -- Assigning final severity')."""
    return {
        "check_id": check_id,
        "category": category,
        "title": title,
        "severity": severity,
        "confidence": confidence,
        "mechanism": mechanism,
        "impact": impact,
        "observed_signal": observed_signal,
        "evidence": evidence,
        "observation_ids": sorted(set(observation_ids)),
        "source_urls": sorted(set(source_urls)),
        "affected": affected,
        "suggested_action": suggested_action,
    }
