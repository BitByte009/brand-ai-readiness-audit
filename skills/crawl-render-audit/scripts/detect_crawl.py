"""D-CRAWL-01..15 over the store.

Inputs:  store
Outputs: unscored findings
Nature:  deterministic

See ../references/crawl-checks.md for the twelve-field definition of every check
below, and ../references/store-contract.md for the observation shapes read here.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from _util import (
    RECOGNIZED_AI_BOTS,
    affected_block,
    group_by_cluster,
    http_fetches,
    is_utility_path,
    make_finding,
    registrable_host,
    single,
)

from lib.common.extract import extract_canonical_url, extract_text, extract_links
from lib.common.robots import robots_allows

CATEGORY = "discoverability"

_NOINDEX_RE = re.compile(r"noindex", re.IGNORECASE)
_SOFT_404_RE = re.compile(
    r"(page\s+(not\s+found|does(n't|\s+not)\s+exist)|"
    r"no\s+longer\s+available|(we\s+)?could\s?n['o]t\s+find\s+(that|this)\s+page)",
    re.IGNORECASE,
)
_CHALLENGE_RE = re.compile(
    r"(checking\s+your\s+browser|verify\s+you\s+are\s+human|just\s+a\s+moment|"
    r"access\s+denied|attention\s+required)",
    re.IGNORECASE,
)
_REGIONAL_BLOCK_RE = re.compile(
    r"not\s+available\s+in\s+your\s+(region|country|location)", re.IGNORECASE
)
_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")


def _meta_content(html: str, names: List[str]) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for name in names:
        tag = soup.find("meta", attrs={"name": lambda v, n=name: v and v.lower() == n})
        if tag and tag.get("content"):
            return str(tag["content"])
    return ""


def _has_noindex(html: str, headers: Dict[str, Any]) -> bool:
    meta = _meta_content(html, ["robots", "googlebot"])
    if _NOINDEX_RE.search(meta):
        return True
    header_value = ""
    for key, value in (headers or {}).items():
        if key.lower() == "x-robots-tag":
            header_value = str(value)
            break
    return bool(_NOINDEX_RE.search(header_value))


def _extract_hreflang(html: str) -> List[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    return [
        str(link.get("hreflang"))
        for link in soup.find_all("link", rel=lambda v: v and "alternate" in v)
        if link.get("hreflang")
    ]


def _derive_link_graph(store: Dict[str, Any]) -> Dict[str, set]:
    """target_url -> set of source urls linking to it, same-host only."""
    from lib.common.extract import extract_links

    fetches = http_fetches(store)
    audited_host = registrable_host(_audited_host(store, fetches))
    graph: Dict[str, set] = {}
    for source_url, obs in fetches.items():
        html = obs.get("value", {}).get("html", "")
        for link in extract_links(html, base_url=source_url):
            href = link["href"]
            if registrable_host(href) != audited_host:
                continue
            graph.setdefault(href, set()).add(source_url)
    return graph


def _audited_host(store: Dict[str, Any], fetches: Dict[str, Dict[str, Any]]) -> str:
    """Always a bare, normalized registrable host (never a full URL)."""
    target = store.get("target", {}) or {}
    if target.get("audited_host"):
        return registrable_host(target["audited_host"])
    if fetches:
        first = next(iter(fetches.values()))
        return registrable_host(first.get("value", {}).get("final_url") or next(iter(fetches)))
    return ""


def _discovered_urls(store: Dict[str, Any]) -> List[str]:
    urls = set(_derive_link_graph(store).keys())
    sitemap = single(store, "SITEMAP")
    if sitemap:
        urls.update(entry["loc"] for entry in sitemap.get("value", {}).get("entries", []))
    urls.update(http_fetches(store).keys())
    requested = store.get("target", {}).get("requested_url")
    if requested:
        urls.add(requested if "://" in requested else "https://" + requested)
    return sorted(urls)


def check_d_crawl_01(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    robots = single(store, "ROBOTS")
    if not robots or robots.get("value", {}).get("status") != "ok":
        return []

    retired = {link['href'] for obs in http_fetches(store).values()
               for link in extract_links(obs['value'].get('html', ''), obs['source_url'])
               if re.search(r"\b(?:EOL|end.of.life|unsupported version|retired version)\b", link.get('text', ''), re.I)}
    disallowed = [
        u for u in _discovered_urls(store)
        if u not in retired and not is_utility_path(u) and not robots_allows(
            robots["value"], (urlparse(u).path or "/") + ("?" + urlparse(u).query if urlparse(u).query else "")
        )
    ]
    if not disallowed:
        return []

    findings = []
    for cluster, urls in group_by_cluster(store, disallowed).items():
        findings.append(
            make_finding(
                check_id="D-CRAWL-01",
                category=CATEGORY,
                title=f"robots.txt disallows content paths in {cluster}",
                severity="critical",
                confidence="high",
                mechanism="A disallowed path is never fetched by a compliant crawler; "
                "the content behind it does not exist for that system at all.",
                impact="Pages in this template are structurally unreachable to any "
                "robots-respecting citation pipeline.",
                observed_signal=f"{len(urls)} non-utility URL(s) disallowed by robots.txt",
                evidence=f"robots.txt disallows: {', '.join(sorted(urls)[:5])}",
                observation_ids=[robots["id"]],
                source_urls=urls,
                affected=affected_block(urls),
                suggested_action={
                    "summary": "Remove the Disallow rule blocking this content, or confirm it has no unique content reachable no other way.",
                    "priority": "critical",
                    "how_to_fix": f"Edit robots.txt to allow {cluster}.",
                    "validation": "Re-fetch robots.txt; robots_allows() on the named path returns true.",
                },
            )
        )
    return findings


def check_d_crawl_02(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    robots = single(store, "ROBOTS")
    if not robots or robots.get("value", {}).get("status") != "ok":
        return []

    groups = robots["value"].get("document", {}).get("groups", [])
    star = next((g for g in groups if (g.get("user_agent") or "").strip() == "*"), None)
    star_disallow = set(star.get("disallow", [])) if star else set()

    findings = []
    for group in groups:
        ua = (group.get("user_agent") or "").strip().lower()
        if ua not in RECOGNIZED_AI_BOTS:
            continue
        extra = set(group.get("disallow", [])) - star_disallow
        if not extra:
            continue
        findings.append(
            make_finding(
                check_id="D-CRAWL-02",
                category=CATEGORY,
                title=f"{group['user_agent']} is specifically blocked in robots.txt",
                severity="medium",
                confidence="high",
                mechanism="The site is reachable to generic crawlers but has "
                "deliberately opted this AI system out.",
                impact=f"{group['user_agent']} cannot see: {', '.join(sorted(extra))}. "
                "This may be a deliberate business decision, reported neutrally as a "
                "discoverability consequence, not an error.",
                observed_signal=f"{group['user_agent']} disallow set exceeds '*' by {sorted(extra)}",
                evidence=f"User-agent: {group['user_agent']}\nDisallow: {', '.join(sorted(extra))}",
                observation_ids=[robots["id"]],
                source_urls=[],
                affected=affected_block(list(extra)),
                suggested_action={
                    "summary": f"Confirm the {group['user_agent']} exclusion is intentional.",
                    "priority": "medium",
                    "how_to_fix": "Remove the bot-specific rules if the exclusion was not intentional.",
                    "validation": "Re-fetch robots.txt; the group's disallow set no longer exceeds '*'.",
                },
            )
        )
    return findings


def check_d_crawl_03(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    flagged = []
    for url, obs in http_fetches(store).items():
        value = obs.get("value", {})
        if value.get("status_code") != 200 or is_utility_path(url):
            continue
        html = value.get("html", "")
        if len(extract_text(html)) <= 400:
            continue
        if _has_noindex(html, value.get("headers", {})):
            flagged.append((url, obs["id"]))

    if not flagged:
        return []

    findings = []
    urls = [u for u, _ in flagged]
    for cluster, cluster_urls in group_by_cluster(store, urls).items():
        obs_ids = [oid for u, oid in flagged if u in cluster_urls]
        findings.append(
            make_finding(
                check_id="D-CRAWL-03",
                category=CATEGORY,
                title=f"noindex on substantive pages in {cluster}",
                severity="critical",
                confidence="high",
                mechanism="noindex is an explicit instruction to exclude the page "
                "from indexes, which most citation pipelines respect.",
                impact="These pages will not be indexed or cited despite being "
                "substantive, reachable content.",
                observed_signal=f"{len(cluster_urls)} substantive page(s) carry noindex",
                evidence=f"noindex found on: {', '.join(sorted(cluster_urls)[:5])}",
                observation_ids=obs_ids,
                source_urls=cluster_urls,
                affected=affected_block(cluster_urls),
                suggested_action={
                    "summary": "Remove the noindex directive unless intentionally excluded.",
                    "priority": "critical",
                    "how_to_fix": "Delete the meta robots noindex tag or X-Robots-Tag header.",
                    "validation": "Re-fetch the page; neither signal carries noindex.",
                },
            )
        )
    return findings


def check_d_crawl_04(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    dead = []
    for url in _discovered_urls(store):
        obs = http_fetches(store).get(url)
        if not obs:
            continue
        value = obs.get("value", {})
        status = value.get("status_code")
        if value.get("evidence", {}).get("coverage_gap"):
            continue
        html = value.get("html", "")
        is_dead = status is None or status >= 400
        is_soft_404 = (
            status == 200
            and len(extract_text(html)) < 400
            and bool(_SOFT_404_RE.search(html))
        )
        if is_dead or is_soft_404:
            dead.append((url, obs["id"], "dead" if is_dead else "soft_404"))

    if not dead:
        return []

    findings = []
    urls = [u for u, _, _ in dead]
    for cluster, cluster_urls in group_by_cluster(store, urls).items():
        obs_ids = [oid for u, oid, _ in dead if u in cluster_urls]
        findings.append(
            make_finding(
                check_id="D-CRAWL-04",
                category=CATEGORY,
                title=f"Dead or soft-404 pages in {cluster}",
                severity="high",
                confidence="high",
                mechanism="A dead page cannot be read regardless of what a sitemap "
                "or internal link claims.",
                impact="Links and sitemap entries pointing here lead nowhere.",
                observed_signal=f"{len(cluster_urls)} page(s) dead or soft-404",
                evidence=f"Broken: {', '.join(sorted(cluster_urls)[:5])}",
                observation_ids=obs_ids,
                source_urls=cluster_urls,
                affected=affected_block(cluster_urls),
                suggested_action={
                    "summary": "Fix the broken route, 301 to the correct resource, or remove the dead link/sitemap entry.",
                    "priority": "high",
                    "how_to_fix": "Restore or redirect the named URLs.",
                    "validation": "Re-fetch; status is 200 and the soft-404 phrase no longer matches.",
                },
            )
        )
    return findings


def _has_redirect_loop(chain: List[Dict[str, Any]]) -> bool:
    seen_from = set()
    for hop in chain:
        if hop["to"] in seen_from:
            return True
        seen_from.add(hop["from"])
    targets = [hop["to"] for hop in chain]
    return len(targets) != len(set(targets))


def check_d_crawl_05(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    flagged = []
    for url, obs in http_fetches(store).items():
        chain = obs.get("value", {}).get("redirect_chain", [])
        if len(chain) >= 3 or _has_redirect_loop(chain):
            flagged.append((url, obs["id"]))

    if not flagged:
        return []

    findings = []
    urls = [u for u, _ in flagged]
    for cluster, cluster_urls in group_by_cluster(store, urls).items():
        obs_ids = [oid for u, oid in flagged if u in cluster_urls]
        findings.append(
            make_finding(
                check_id="D-CRAWL-05",
                category=CATEGORY,
                title=f"Redirect chain faults in {cluster}",
                severity="medium",
                confidence="high",
                mechanism="Each hop is a chance for a crawler to give up, and adds "
                "latency against the crawl-budget ceiling every citation pipeline has.",
                impact="Slower, less reliable discovery of these URLs.",
                observed_signal=f"{len(cluster_urls)} URL(s) with >=3 hops or a loop",
                evidence=f"Long/looping chains: {', '.join(sorted(cluster_urls)[:5])}",
                observation_ids=obs_ids,
                source_urls=cluster_urls,
                affected=affected_block(cluster_urls),
                suggested_action={
                    "summary": "Collapse the chain to a single redirect straight to the final canonical URL.",
                    "priority": "medium",
                    "how_to_fix": "Update the redirect rule(s) to a direct hop.",
                    "validation": "Re-fetch the original URL; redirect_chain length is <=1.",
                },
            )
        )
    return findings


def check_d_crawl_06(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    fetches = http_fetches(store)
    audited_host = registrable_host(_audited_host(store, fetches))
    flagged = []
    for url, obs in fetches.items():
        value = obs.get("value", {})
        if value.get("status_code") != 200:
            continue
        html = value.get("html", "")
        final_url = value.get("final_url", url)
        canonical = extract_canonical_url(html, final_url)
        if not canonical or canonical.rstrip("/") == final_url.rstrip("/"):
            continue
        if registrable_host(canonical) != audited_host:
            continue  # cross-domain: never flag

        target_obs = fetches.get(canonical) or next(
            (o for u, o in fetches.items() if u.rstrip("/") == canonical.rstrip("/")), None
        )
        if not target_obs:
            continue  # target never crawled: applicability unmet

        target_value = target_obs.get("value", {})
        broken = (target_value.get("status_code") or 0) >= 400
        noindexed = _has_noindex(target_value.get("html", ""), target_value.get("headers", {}))
        if broken or noindexed:
            flagged.append((url, canonical, obs["id"], target_obs["id"]))

    if not flagged:
        return []

    findings = []
    for cluster, cluster_urls in group_by_cluster(store, [u for u, *_ in flagged]).items():
        rows = [row for row in flagged if row[0] in cluster_urls]
        findings.append(
            make_finding(
                check_id="D-CRAWL-06",
                category=CATEGORY,
                title=f"Canonical conflicts in {cluster}",
                severity="high",
                confidence="high",
                mechanism="A citation pipeline that follows the canonical signal "
                "ends up at content that doesn't exist or isn't indexable.",
                impact="These pages effectively disappear behind a broken canonical.",
                observed_signal=f"{len(rows)} page(s) canonicalize to a broken/noindexed same-domain target",
                evidence="; ".join(f"{u} -> {c}" for u, c, *_ in rows[:5]),
                observation_ids=[oid for row in rows for oid in row[2:]],
                source_urls=[u for u, *_ in rows],
                affected=affected_block([u for u, *_ in rows]),
                suggested_action={
                    "summary": "Point the canonical at a URL that resolves and is indexable, or remove it.",
                    "priority": "high",
                    "how_to_fix": "Fix the canonical target or the target page's own status/noindex.",
                    "validation": "Re-fetch the source page; the canonical target returns 200 with no noindex.",
                },
            )
        )
    return findings


def check_d_crawl_07(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    sitemap = single(store, "SITEMAP")
    findings = []

    if sitemap and sitemap.get("value", {}).get("status") == "ok":
        entries = [e for e in sitemap["value"].get("entries", []) if e.get("status_code") is not None]
        if entries:
            rotten = [e for e in entries if e["status_code"] < 200 or e["status_code"] >= 300]
            ratio = len(rotten) / len(entries)
            if ratio >= 0.2:
                urls = [e["loc"] for e in rotten]
                findings.append(
                    make_finding(
                        check_id="D-CRAWL-07",
                        category=CATEGORY,
                        title="Sitemap lists dead or redirecting URLs",
                        severity="medium",
                        confidence="high",
                        mechanism="The sitemap wastes crawl budget on dead ends "
                        "instead of shortcutting discovery to real content.",
                        impact=f"{ratio:.0%} of sitemap entries are rotten.",
                        observed_signal=f"{len(rotten)}/{len(entries)} sitemap entries non-200",
                        evidence=f"Rotten entries: {', '.join(sorted(urls)[:5])}",
                        observation_ids=[sitemap["id"]],
                        source_urls=urls,
                        affected=affected_block(urls, total_in_scope=len(entries)),
                        suggested_action={
                            "summary": "Remove or fix the dead/redirecting sitemap entries.",
                            "priority": "medium",
                            "how_to_fix": "Regenerate the sitemap from live, canonical URLs only.",
                            "validation": "Re-fetch /sitemap.xml; <20% of a fresh sample returns non-200.",
                        },
                    )
                )
    elif sitemap and sitemap.get("value", {}).get("status") == "missing":
        orphans = _linkless_pages(store)
        if orphans:
            obs_ids = [sitemap["id"]] if sitemap else []
            findings.append(
                make_finding(
                    check_id="D-CRAWL-07",
                    category=CATEGORY,
                    title="No sitemap, and important pages are unreachable by links alone",
                    severity="medium",
                    confidence="medium",
                    mechanism="Without a sitemap, discovery depends entirely on the "
                    "internal link graph; combined with orphan pages, real content "
                    "is unreachable either way.",
                    impact="A crawler with no sitemap and no inbound link cannot find these pages.",
                    observed_signal="sitemap missing and >=1 orphan page detected",
                    evidence=f"Orphans without a sitemap safety net: {', '.join(sorted(orphans)[:5])}",
                    observation_ids=obs_ids,
                    source_urls=orphans,
                    affected=affected_block(orphans),
                    suggested_action={
                        "summary": "Publish /sitemap.xml referenced from robots.txt, and link the orphaned pages internally.",
                        "priority": "medium",
                        "how_to_fix": "Add a sitemap and an internal link to each orphan.",
                        "validation": "Re-fetch /sitemap.xml; it exists and lists the pages.",
                    },
                )
            )

    return findings


def _orphan_urls(store: Dict[str, Any]) -> List[str]:
    """Sitemap-listed pages with zero internal in-links. Requires a confirmed
    sitemap so 'important' is a defined set (used by D-CRAWL-08)."""
    if store.get("capabilities", {}).get("crawl", {}).get("complete") is False:
        return []  # a truncated link graph cannot establish absent incoming links
    sitemap = single(store, "SITEMAP")
    if not sitemap or sitemap.get("value", {}).get("status") != "ok":
        return []
    fetches = http_fetches(store)
    if len(fetches) < 3:
        return []
    graph = _derive_link_graph(store)
    return [
        e["loc"]
        for e in sitemap["value"].get("entries", [])
        if not is_utility_path(e["loc"])
        and (urlparse(e["loc"]).path or "/") != "/"
        and len(graph.get(e["loc"], set())) == 0
    ]


def _linkless_pages(store: Dict[str, Any]) -> List[str]:
    """Crawled, non-root, non-utility pages with zero internal in-links in the
    derived link graph. Sitemap-independent -- used by D-CRAWL-07's 'no sitemap and
    no other way in' branch, where there is no sitemap to define 'important' pages.
    The root path is never counted -- it's definitionally the crawl's entry point,
    not something reached by an internal link."""
    fetches = http_fetches(store)
    if len(fetches) < 3:
        return []
    graph = _derive_link_graph(store)
    return [
        url
        for url in fetches
        if not is_utility_path(url)
        and (urlparse(url).path or "/") != "/"
        and len(graph.get(url, set())) == 0
    ]


def check_d_crawl_08(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    orphans = _orphan_urls(store)
    if not orphans:
        return []

    sitemap = single(store, "SITEMAP")
    findings = []
    for cluster, urls in group_by_cluster(store, orphans).items():
        findings.append(
            make_finding(
                check_id="D-CRAWL-08",
                category=CATEGORY,
                title=f"Orphaned pages in {cluster}",
                severity="medium",
                confidence="high",
                mechanism="A crawler that discovers pages by following links never "
                "reaches a page with zero inbound internal links.",
                impact="These pages depend entirely on the sitemap for discovery.",
                observed_signal=f"{len(urls)} sitemap URL(s) with zero internal in-links",
                evidence=f"Orphaned: {', '.join(sorted(urls)[:5])}",
                observation_ids=[sitemap["id"]] if sitemap else [],
                source_urls=urls,
                affected=affected_block(urls),
                suggested_action={
                    "summary": "Add an internal link to the orphaned page from a relevant, already-linked page.",
                    "priority": "medium",
                    "how_to_fix": "Link the page from its topical parent or primary navigation.",
                    "validation": "Re-crawl; the page's in-degree in the derived link graph is >=1.",
                },
            )
        )
    return findings


def check_d_crawl_09(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    flagged = []
    for url, obs in http_fetches(store).items():
        value = obs.get("value", {})
        html = value.get("html", "")
        is_blocked = value.get("status_code") == 403
        is_challenge = len(html) < 1000 and bool(_CHALLENGE_RE.search(html))
        if is_blocked or is_challenge:
            flagged.append((url, obs["id"]))

    if not flagged:
        return []

    findings = []
    urls = [u for u, _ in flagged]
    for cluster, cluster_urls in group_by_cluster(store, urls).items():
        obs_ids = [oid for u, oid in flagged if u in cluster_urls]
        findings.append(
            make_finding(
                check_id="D-CRAWL-09",
                category=CATEGORY,
                title=f"Bot-hostile serving in {cluster}",
                severity="critical",
                confidence="high",
                mechanism="Our own honest, single-UA fetch was blocked or challenged; "
                "no UA spoofing was used to reach this conclusion.",
                impact="Our declared, honest crawler identity cannot read this content.",
                observed_signal=f"{len(cluster_urls)} URL(s) returned 403 or a challenge shell",
                evidence=f"Blocked/challenged: {', '.join(sorted(cluster_urls)[:5])}",
                observation_ids=obs_ids,
                source_urls=cluster_urls,
                affected=affected_block(cluster_urls),
                suggested_action={
                    "summary": "Allow-list a documented, honest crawler identity, or scope the challenge to high-risk paths only.",
                    "priority": "critical",
                    "how_to_fix": "Adjust WAF/bot-protection rules for this identity and path set.",
                    "validation": "Re-fetch with the same UA; status is 200 with the requested content.",
                },
            )
        )
    return findings


def check_d_crawl_10(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    samples = [
        (url, obs["id"], obs["value"]["elapsed_ms"])
        for url, obs in http_fetches(store).items()
        if obs.get("value", {}).get("elapsed_ms") is not None
    ]
    if len(samples) < 5:
        return []

    median_ms = statistics.median(v for _, _, v in samples)
    threshold_ms = 3000 * 3
    if median_ms <= threshold_ms:
        return []

    urls = [u for u, _, _ in samples]
    return [
        make_finding(
            check_id="D-CRAWL-10",
            category=CATEGORY,
            title="Fetch cost likely to cause crawler timeout",
            severity="medium",
            confidence="medium",
            mechanism="Citation pipelines run under their own timeouts; a slow "
            "origin is functionally unreachable even with zero blocking rules.",
            impact="Budget-constrained crawlers are likely to abandon these pages.",
            observed_signal=f"median TTFB {median_ms:.0f}ms across {len(samples)} samples (threshold {threshold_ms}ms)",
            evidence=f"Sampled: {', '.join(sorted(urls)[:5])}",
            observation_ids=[oid for _, oid, _ in samples],
            source_urls=urls,
            affected=affected_block(urls),
            suggested_action={
                "summary": "Investigate origin TTFB (caching, CDN, server-rendering cost) for this template.",
                "priority": "medium",
                "how_to_fix": "Add caching/CDN in front of the affected template.",
                "validation": "Re-sample >=5 pages; median TTFB within 2x of the 3s threshold.",
            },
        )
    ]


def check_d_crawl_11(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    fetches = http_fetches(store)
    locale_groups: Dict[str, List[str]] = {}
    for url in fetches:
        path = urlparse(url).path
        segments = [s for s in path.split("/") if s]
        for i, seg in enumerate(segments):
            if _LOCALE_SEGMENT_RE.match(seg):
                shape = "/".join(segments[:i] + ["*"] + segments[i + 1 :])
                locale_groups.setdefault(shape, []).append(url)
                break

    findings = []
    for shape, urls in locale_groups.items():
        if len(urls) < 2:
            continue
        hreflang_by_url = {u: _extract_hreflang(fetches[u]["value"].get("html", "")) for u in urls}
        none_tagged = all(not tags for tags in hreflang_by_url.values())
        if not none_tagged:
            continue
        findings.append(
            make_finding(
                check_id="D-CRAWL-11",
                category=CATEGORY,
                title=f"Locale variants with no hreflang ({shape})",
                severity="medium",
                confidence="high",
                mechanism="Ambiguous locale signals split citation authority across "
                "duplicates and risk serving the wrong-language version to a crawler.",
                impact="These locale variants compete instead of consolidating signal.",
                observed_signal=f"{len(urls)} locale variant(s), none carry hreflang",
                evidence=f"Variants: {', '.join(sorted(urls)[:5])}",
                observation_ids=[fetches[u]["id"] for u in urls],
                source_urls=urls,
                affected=affected_block(urls),
                suggested_action={
                    "summary": "Add self- and cross-referencing hreflang tags across every locale variant.",
                    "priority": "medium",
                    "how_to_fix": "Add <link rel=alternate hreflang=...> for each variant on every variant.",
                    "validation": "Re-fetch each variant; a consistent, mutually-referencing hreflang set is present.",
                },
            )
        )
    return findings


def check_d_crawl_12(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    flagged = []
    for url, obs in http_fetches(store).items():
        html = obs.get("value", {}).get("html", "")
        if _REGIONAL_BLOCK_RE.search(html):
            flagged.append((url, obs["id"]))

    if not flagged:
        return []

    urls = [u for u, _ in flagged]
    return [
        make_finding(
            check_id="D-CRAWL-12",
            category=CATEGORY,
            title="Explicit geographic serving restriction observed",
            severity="low",
            confidence="high",
            mechanism="We audit from one vantage point; an assistant's fetch may "
            "originate elsewhere and be blocked the same way.",
            impact="Visitors/assistants from the restricted region cannot reach this content.",
            observed_signal=f"{len(urls)} page(s) show an explicit regional-block message",
            evidence=f"Regional block observed on: {', '.join(sorted(urls)[:5])}",
            observation_ids=[oid for _, oid in flagged],
            source_urls=urls,
            affected=affected_block(urls),
            suggested_action={
                "summary": "Confirm the regional restriction is intentional.",
                "priority": "low",
                "how_to_fix": "Remove the geo-block or provide a graceful, indexable explanation page.",
                "validation": "Re-fetch; the explicit regional-block response no longer appears.",
            },
        )
    ]


def check_d_crawl_13(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    fetches = http_fetches(store)
    primary_host = registrable_host(_audited_host(store, fetches))
    flagged = []
    for url, obs in fetches.items():
        if registrable_host(url) == primary_host:
            continue
        value = obs.get("value", {})
        if value.get("status_code") != 200:
            continue
        canonical = extract_canonical_url(value.get("html", ""), value.get("final_url", url))
        if registrable_host(canonical) != primary_host:
            flagged.append((url, obs["id"]))

    if not flagged:
        return []

    urls = [u for u, _ in flagged]
    return [
        make_finding(
            check_id="D-CRAWL-13",
            category=CATEGORY,
            title="Duplicate content served at an alternate host with no canonical resolution",
            severity="medium",
            confidence="high",
            mechanism="Citation authority splits across duplicates instead of "
            "consolidating on one URL.",
            impact="Search/citation signal for this content is divided.",
            observed_signal=f"{len(urls)} alternate-host URL(s) serve 200 with no canonical back to {primary_host}",
            evidence=f"Duplicate hosts: {', '.join(sorted(urls)[:5])}",
            observation_ids=[oid for _, oid in flagged],
            source_urls=urls,
            affected=affected_block(urls),
            suggested_action={
                "summary": f"301-redirect every alternate form to {primary_host}, or set a correct canonical tag.",
                "priority": "medium",
                "how_to_fix": "Add a redirect rule or canonical tag pointing at the primary host.",
                "validation": "Re-fetch the alternate form; it now redirects to or canonicalizes to the primary host.",
            },
        )
    ]


def check_d_crawl_14(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    budget_exhausted = bool(store.get("capabilities", {}).get("crawl", {}).get("budget_exhausted"))
    if not budget_exhausted:
        return []

    discovered = [u for u in _discovered_urls(store) if registrable_host(u) == registrable_host(_audited_host(store, http_fetches(store)))]
    if not discovered:
        return []

    findings = []
    for cluster, urls in group_by_cluster(store, discovered).items():
        with_query = [u for u in urls if urlparse(u).query]
        ratio = len(with_query) / len(urls) if urls else 0
        if ratio <= 0.4:
            continue
        findings.append(
            make_finding(
                check_id="D-CRAWL-14",
                category=CATEGORY,
                title=f"Crawl budget burned by parameter URLs in {cluster}",
                severity="medium",
                confidence="medium",
                mechanism="A crawler with a fixed page budget that spends it on "
                "filter/sort combinations never reaches the actual content pages.",
                impact="Substantive pages behind this template may go undiscovered.",
                observed_signal=f"{ratio:.0%} of discovered URLs in {cluster} carry a query string, and the crawl exhausted its budget",
                evidence=f"Parameter URLs: {', '.join(sorted(with_query)[:5])}",
                observation_ids=[],
                source_urls=with_query,
                affected=affected_block(with_query, total_in_scope=len(urls)),
                suggested_action={
                    "summary": "Disallow or canonicalize low-value parameter combinations so budget reaches substantive URLs.",
                    "priority": "medium",
                    "how_to_fix": "Add robots.txt rules or canonical tags for facet/sort parameters.",
                    "validation": "Re-crawl under the same budget; discovery reaches the previously unreached substantive URLs.",
                },
            )
        )
    return findings


def check_d_crawl_15(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    robots = single(store, "ROBOTS")
    if not robots or robots["value"].get("status") not in {"error", "unparseable"}:
        return []
    if robots['value'].get('failure_kind') in {'transport', 'policy', 'redirect'}:
        return []  # audit limitation, not proof of a defective server policy
    if robots['value'].get('status') == 'error' and not robots['value'].get('http_status'):
        return []  # legacy/unknown error records do not establish a server response

    return [
        make_finding(
            check_id="D-CRAWL-15",
            category=CATEGORY,
            title="robots.txt is unreachable or unparseable",
            severity="critical",
            confidence="high",
            mechanism="Many crawlers treat an unreachable robots.txt as disallow-all.",
            impact="The entire site may be treated as off-limits by conservative crawlers.",
            observed_signal=f"robots.txt status: {robots['value'].get('status')}",
            evidence=f"robots.txt fetch status: {robots['value'].get('status')}; HTTP status: {robots['value'].get('http_status', 'not applicable')}",
            observation_ids=[robots["id"]],
            source_urls=[robots.get("source_url", "")],
            affected=affected_block([robots.get("source_url", "")]),
            suggested_action={
                "summary": "Serve a syntactically valid robots.txt with a 200 status.",
                "priority": "critical",
                "how_to_fix": "Fix the server/proxy issue serving robots.txt, or correct its syntax.",
                "validation": "Re-fetch /robots.txt; status is 200 and it parses.",
            },
        )
    ]


CHECKS = [
    check_d_crawl_01,
    check_d_crawl_02,
    check_d_crawl_03,
    check_d_crawl_04,
    check_d_crawl_05,
    check_d_crawl_06,
    check_d_crawl_07,
    check_d_crawl_08,
    check_d_crawl_09,
    check_d_crawl_10,
    check_d_crawl_11,
    check_d_crawl_12,
    check_d_crawl_13,
    check_d_crawl_14,
    check_d_crawl_15,
]


def detect_crawl(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for check in CHECKS:
        findings.extend(check(store))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run D-CRAWL-01..15 over an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--out", help="Path to write findings JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    findings = detect_crawl(store)
    output = json.dumps(findings, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
