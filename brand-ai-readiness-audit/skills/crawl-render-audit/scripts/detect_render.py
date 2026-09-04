"""D-RENDER-01..05: raw vs rendered on the main-content region only.

Inputs:  store
Outputs: unscored findings
Nature:  deterministic + interpretation

See ../references/render-checks.md for the twelve-field definition of every check
below, and ../references/store-contract.md for the observation shapes read here.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from _util import affected_block, group_by_cluster, http_fetches, make_finding, renders

from lib.common.extract import extract_links

CATEGORY = "discoverability"
MAIN_TEXT_FLOOR = 400
RATIO_THRESHOLD = 0.30
_CHROME_TAGS = {"nav", "header", "footer", "script", "style", "noscript"}
_NEXT_HREF_RE = re.compile(r"([?&]page=\d+|/page/\d+)", re.IGNORECASE)


def _main_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(list(_CHROME_TAGS)):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def _paired_pages(store: Dict[str, Any]):
    fetches = http_fetches(store)
    render_obs = renders(store)
    for url, render in render_obs.items():
        if render.get("value", {}).get("status") != "ok":
            continue
        fetch = fetches.get(url)
        if not fetch:
            continue
        yield url, fetch, render


def check_d_render_01(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    per_page = {}
    for url, fetch, render in _paired_pages(store):
        raw_text = _main_text(fetch["value"].get("html", ""))
        rendered_text = _main_text(render["value"].get("html", ""))
        if len(rendered_text) <= MAIN_TEXT_FLOOR:
            continue
        ratio = len(raw_text) / len(rendered_text) if rendered_text else 1.0
        if ratio >= RATIO_THRESHOLD:
            continue
        excerpt = next((w for w in rendered_text.split() if w not in raw_text), rendered_text[:80])
        per_page[url] = {
            "fetch_id": fetch["id"],
            "render_id": render["id"],
            "raw_len": len(raw_text),
            "rendered_len": len(rendered_text),
            "ratio": ratio,
            "excerpt": excerpt,
        }

    if not per_page:
        return []

    for cluster, urls in group_by_cluster(store, per_page.keys()).items():
        rows = {u: per_page[u] for u in urls}
        confidence = "high" if len(rows) >= 3 else "medium"
        findings.append(
            make_finding(
                check_id="D-RENDER-01",
                category=CATEGORY,
                title=f"Primary content is render-dependent in {cluster}",
                severity="high",
                confidence=confidence,
                mechanism="A fetcher that does not execute JavaScript receives a "
                "shell; the page looks complete to a person and empty to the machine.",
                impact="Non-rendering readers cannot read, quote, or cite this content.",
                observed_signal="; ".join(
                    f"{u}: raw {r['raw_len']}/rendered {r['rendered_len']} chars (ratio {r['ratio']:.2f})"
                    for u, r in list(rows.items())[:3]
                ),
                evidence=f"Present rendered, absent raw, e.g.: \"{next(iter(rows.values()))['excerpt']}\"",
                observation_ids=[oid for r in rows.values() for oid in (r["fetch_id"], r["render_id"])],
                source_urls=list(rows.keys()),
                affected=affected_block(list(rows.keys())),
                suggested_action={
                    "summary": "Server-render or pre-render the main-content region for this template.",
                    "priority": "high",
                    "how_to_fix": "Emit the substantive text in the initial HTML payload and hydrate on top.",
                    "validation": "Re-fetch with JS disabled; the named excerpt appears raw and the ratio exceeds 0.6.",
                },
            )
        )
    return findings


def check_d_render_02(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    from _util import probes

    findings = []
    probe_obs = probes(store)
    for url, fetch, render in _paired_pages(store):
        probe = probe_obs.get(url)
        if not probe:
            continue
        raw_text = _main_text(fetch["value"].get("html", ""))
        for question in probe.get("value", {}).get("questions", []):
            if question.get("category") != "factual" or not question.get("answered"):
                continue
            span = re.sub(r"\s+", " ", (question.get("evidence_span") or "").strip())
            if not span:
                continue
            if span not in raw_text:
                findings.append(
                    make_finding(
                        check_id="D-RENDER-02",
                        category=CATEGORY,
                        title=f"Key fact render-only on {url}",
                        severity="high",
                        confidence="high",
                        mechanism="Even when most of the page reads fine raw, the "
                        "one fact a user would ask an assistant for can be the part "
                        "that's missing.",
                        impact="This specific, user-relevant fact cannot be read without executing JavaScript.",
                        observed_signal=f"probe question '{question.get('id')}' answered from rendered text only",
                        evidence=f"Rendered-only fact: \"{span}\"",
                        observation_ids=[probe["id"], fetch["id"], render["id"]],
                        source_urls=[url],
                        affected=affected_block([url]),
                        suggested_action={
                            "summary": "Move this fact into server-rendered markup.",
                            "priority": "high",
                            "how_to_fix": f"Ensure the text \"{span}\" is present in the raw HTML response.",
                            "validation": "Re-fetch raw; the named evidence span is present verbatim.",
                        },
                    )
                )
    return findings


def check_d_render_03(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    for url, fetch, render in _paired_pages(store):
        raw_links = {link["href"] for link in extract_links(fetch["value"].get("html", ""), base_url=url)}
        rendered_links = {link["href"] for link in extract_links(render["value"].get("html", ""), base_url=url)}
        rendered_only = sorted(rendered_links - raw_links)
        if len(rendered_only) < 3:
            continue
        findings.append(
            make_finding(
                check_id="D-RENDER-03",
                category=CATEGORY,
                title=f"Internal navigation is render-only on {url}",
                severity="high",
                confidence="high",
                mechanism="A non-rendering fetcher cannot discover pages reachable "
                "only through client-rendered links, shrinking effective site coverage.",
                impact=f"{len(rendered_only)} link target(s) are invisible to a non-rendering fetch.",
                observed_signal=f"{len(rendered_only)} rendered-only link target(s)",
                evidence=f"Rendered-only targets: {', '.join(rendered_only[:5])}",
                observation_ids=[fetch["id"], render["id"]],
                source_urls=[url],
                affected=affected_block(rendered_only),
                suggested_action={
                    "summary": "Render primary navigation as real anchor tags in the initial HTML.",
                    "priority": "high",
                    "how_to_fix": "Use progressive enhancement: real <a href> targets, JS intercepts clicks for SPA transitions.",
                    "validation": "Re-fetch raw; the previously rendered-only targets now appear as <a href> values.",
                },
            )
        )
    return findings


def _disclosure_panels(html: str):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    panels = []
    for trigger in soup.find_all(attrs={"aria-controls": True}):
        target = soup.find(id=trigger["aria-controls"])
        if target is not None:
            panels.append((trigger, target))
    for trigger in soup.find_all(attrs={"aria-expanded": "false"}):
        target_id = trigger.get("aria-controls")
        if target_id:
            continue  # already covered above
        # common accordion pattern: expanded control's next sibling is the panel
        sibling = trigger.find_next_sibling()
        if sibling is not None:
            panels.append((trigger, sibling))
    return panels


def check_d_render_04(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    for url, fetch, render in _paired_pages(store):
        html = render["value"].get("html", "")
        empty_panels = [
            trigger for trigger, panel in _disclosure_panels(html) if not panel.get_text(strip=True)
        ]
        if not empty_panels:
            continue
        findings.append(
            make_finding(
                check_id="D-RENDER-04",
                category=CATEGORY,
                title=f"Interaction-gated content absent from the DOM on {url}",
                severity="medium",
                confidence="medium",
                mechanism="A fetcher (and most non-interactive citation pipelines) "
                "never triggers the click, so DOM-absent content is unreadable.",
                impact=f"{len(empty_panels)} disclosure panel(s) have no content until clicked.",
                observed_signal=f"{len(empty_panels)} trigger(s) with an empty associated panel",
                evidence="Empty disclosure panel(s) found pre-interaction",
                observation_ids=[render["id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Render the panel content into the DOM at load, even visually collapsed.",
                    "priority": "medium",
                    "how_to_fix": "Do not defer the panel's DOM existence to the click interaction.",
                    "validation": "Re-render; the panel's pre-interaction DOM text content is non-empty.",
                },
            )
        )
    return findings


def _listing_item_count(html: str) -> int:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    counts: Counter = Counter()
    for el in soup.find_all(True):
        classes = el.get("class")
        if not classes or el.parent is None:
            continue
        counts[(id(el.parent), el.name, tuple(sorted(classes)))] += 1
    return max(counts.values(), default=0)


def _has_pagination_anchor(html: str, base_url: str) -> bool:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    if soup.find("link", rel=lambda v: v and "next" in v):
        return True
    for link in extract_links(html, base_url=base_url):
        if "next" in [r.lower() for r in link.get("rel", [])]:
            return True
        if _NEXT_HREF_RE.search(link["href"]):
            return True
    return False


def check_d_render_05(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    for url, fetch, render in _paired_pages(store):
        rendered_html = render["value"].get("html", "")
        item_count = _listing_item_count(rendered_html)
        if item_count < 10:
            continue
        raw_html = fetch["value"].get("html", "")
        if _has_pagination_anchor(raw_html, url) or _has_pagination_anchor(rendered_html, url):
            continue
        findings.append(
            make_finding(
                check_id="D-RENDER-05",
                category=CATEGORY,
                title=f"Listing without crawlable pagination on {url}",
                severity="medium",
                confidence="medium",
                mechanism="A crawler that doesn't scroll or click 'load more' sees "
                "only the first page of the collection, permanently.",
                impact="Items beyond the first page are unreachable to a non-interactive fetch.",
                observed_signal=f"{item_count} rendered items, no rel=next or page-shaped anchor found",
                evidence=f"Listing of {item_count} items with no pagination anchor",
                observation_ids=[fetch["id"], render["id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Expose paginated, crawlable URLs alongside the infinite-scroll UI.",
                    "priority": "medium",
                    "how_to_fix": "Add ?page=2 (or equivalent) URLs linked with rel=next.",
                    "validation": "Re-fetch raw; a second-page URL is discoverable and returns additional items.",
                },
            )
        )
    return findings


CHECKS = [
    check_d_render_01,
    check_d_render_02,
    check_d_render_03,
    check_d_render_04,
    check_d_render_05,
]


def detect_render(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for check in CHECKS:
        findings.extend(check(store))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run D-RENDER-01..05 over an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--out", help="Path to write findings JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    findings = detect_render(store)
    output = json.dumps(findings, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
