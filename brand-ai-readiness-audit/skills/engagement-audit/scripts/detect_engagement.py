"""E-ORIENT, E-ANSWER, E-CONTINUE over the rendered lens. Positional and structural measurements only.

Inputs:  store, entity_profile (built by entity-semantic-audit, optional -- only
         E-ORIENT-01 needs it)
Outputs: unscored findings
Nature:  deterministic + capped interpretation

See ../references/engagement-checks.md for the twelve-field definition of every
check below, ../references/store-contract.md for the observation shapes read,
and ../references/ai-referral-persona.md for the arrival model every check is
evaluated against.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional

from _engagement_util import (
    affected_block,
    content_area_links,
    classify_link,
    effective_pages,
    engagement_question,
    find_blocking_overlay,
    find_paywall_gate,
    has_anchor_nav_to_answer,
    has_breadcrumb,
    has_dom_anchor,
    brand_token_positions,
    containment_ratio,
    http_fetches,
    hub_url,
    internal_fragment_links,
    navigation_destinations,
    is_in_collapsed_region,
    is_terminal_page,
    main_text,
    make_finding,
    page_classifications,
    probes,
    scroll_depth_fraction,
    url_depth,
)

from lib.common.extract import extract_metadata

CATEGORY = "engagement"


def _brand_tokens(entity_profile: Optional[Dict[str, Any]], for_url: Optional[str] = None) -> List[str]:
    """Names that would identify the operator to a visitor on this page.

    `for_url` drops alias tokens whose only evidence is this very page. A page
    cannot identify its owner by repeating its own title: if /docs/rate-limits
    is titled "Rate Limit Configuration", finding that string on that page says
    nothing about whose site it is. Excluding it is what lets E-ORIENT-01 see a
    genuinely unbranded deep page instead of being satisfied by circular
    evidence. The canonical name is never dropped -- when a page's title *is*
    the brand name, that is real identification.
    """
    if not entity_profile:
        return []
    fields = entity_profile.get("fields", {})
    canonical = (fields.get("canonical_name") or {}).get("value")
    if not canonical:
        return []

    alias_field = fields.get("aliases") or {}
    page_local = set()
    if for_url:
        by_value: Dict[str, set] = {}
        for candidate in alias_field.get("candidates", []) or []:
            by_value.setdefault(str(candidate.get("value", "")).strip(), set()).add(candidate.get("source_url"))
        page_local = {value for value, urls in by_value.items() if urls == {for_url}}

    aliases = alias_field.get("value") or ""
    tokens = [canonical] + [
        alias.strip() for alias in aliases.split(",")
        if alias.strip() and alias.strip() not in page_local
    ]
    return tokens


def check_e_orient_01(store: Dict[str, Any], entity_profile: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not _brand_tokens(entity_profile):
        return []  # no determined canonical name -- that gap is D-ENTITY-01's, not this skill's

    findings = []
    for url, page in effective_pages(store).items():
        if url_depth(url) < 2:
            continue
        tokens = _brand_tokens(entity_profile, for_url=url)
        title = extract_metadata(page["html"])["title"]
        positions = brand_token_positions(page["html"], title, tokens)
        if any(positions.values()):
            continue
        findings.append(
            make_finding(
                check_id="E-ORIENT-01",
                category=CATEGORY,
                title=f"No brand identification on arrival at {url}",
                severity="high",
                confidence="high",
                mechanism="An AI-referred visitor arrives with no homepage "
                "context and no navigation history; if the first screen "
                "doesn't say whose page this is, they cannot evaluate trust.",
                impact="A cold arrival on this page cannot tell whose site it landed on.",
                observed_signal="brand token absent from early body text, logo alt, and title",
                evidence=f"Checked title \"{title}\", logo alt text, and first-screen body text on {url}",
                observation_ids=[page["observation_id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Put the brand name in the title, accessible header text, or the logo's alt text.",
                    "priority": "high",
                    "how_to_fix": f"Add the brand name to one of the three positions on {url}.",
                    "validation": "Re-fetch the page cold; the brand token is present in >=1 of the three positions.",
                },
            )
        )
    return findings


def check_e_orient_03(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    pages = effective_pages(store)
    if not pages:
        return []
    max_depth = max(url_depth(u) for u in pages)
    if max_depth < 3:
        return []  # flat site: nothing to show a breadcrumb for

    classifications = page_classifications(store)
    findings = []
    for url, page in pages.items():
        if url_depth(url) < 2:
            continue
        if is_terminal_page(url, classifications.get(url)):
            continue  # a landing/campaign page omitting navigation is a deliberate design choice, not a defect
        if has_breadcrumb(page["html"]):
            continue
        findings.append(
            make_finding(
                check_id="E-ORIENT-03",
                category=CATEGORY,
                title=f"No path context on {url}",
                severity="medium",
                confidence="high",
                mechanism="An AI-referred visitor dropped mid-site has no "
                "navigation history to infer structure from.",
                impact="A visitor cannot tell where this page sits in the wider site.",
                observed_signal="no BreadcrumbList, breadcrumb-named element, or textual path equivalent found",
                evidence=f"No path-context signal found on {url}",
                observation_ids=[page["observation_id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Add a breadcrumb or a clear parent-topic link near the top of the page.",
                    "priority": "medium",
                    "how_to_fix": f"Add breadcrumb markup (e.g. BreadcrumbList) to {url}.",
                    "validation": "Re-fetch; a path-context signal is now present.",
                },
            )
        )
    return findings


def check_e_orient_04(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    pages = effective_pages(store)
    broken_by_source: Dict[str, List[Any]] = {}

    for url, page in pages.items():
        for target, fragment in internal_fragment_links(page["html"], url):
            target_page = pages.get(target) or pages.get(target + "/") or pages.get(target.rstrip("/"))
            if not target_page:
                continue  # target never crawled: applicability unmet
            if not has_dom_anchor(target_page["html"], fragment):
                broken_by_source.setdefault(url, []).append((target, fragment, page["observation_id"], target_page["observation_id"]))

    findings = []
    for url, broken in broken_by_source.items():
        obs_ids = [oid for _, _, oid, _ in broken] + [oid for _, _, _, oid in broken]
        findings.append(
            make_finding(
                check_id="E-ORIENT-04",
                category=CATEGORY,
                title=f"Fragment links don't resolve from {url}",
                severity="medium",
                confidence="high",
                mechanism="A visitor following a deep-linked anchor lands on "
                "the target page with no way to reach the specific content "
                "the fragment promised.",
                impact="These deep links do not resolve to any content on their target page.",
                observed_signal=f"{len(broken)} fragment link(s) with no matching target id",
                evidence="; ".join(f"{url}#{frag} -> {target} (no #{frag})" for target, frag, *_ in broken[:5]),
                observation_ids=sorted(set(obs_ids)),
                source_urls=[url] + [t for t, *_ in broken],
                affected=affected_block([t for t, *_ in broken]),
                suggested_action={
                    "summary": "Add the missing anchor id to the target page, or fix the link.",
                    "priority": "medium",
                    "how_to_fix": "Add an id/name attribute matching the fragment at the referenced content.",
                    "validation": "Re-fetch the target page; an element with the matching id now exists.",
                },
            )
        )
    return findings


def check_e_answer_01(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    probe_map = probes(store)
    findings = []

    for url, page in effective_pages(store).items():
        meta = extract_metadata(page["html"])
        title_desc = f"{meta['title']} {meta['description']}".strip()
        if not title_desc:
            continue

        body = main_text(page["html"])
        if len(body) <= 400:
            continue  # not content-bearing prose (listing/grid page) -- divergence is normal there

        overlap = containment_ratio(title_desc, body)
        if overlap >= 0.2:
            continue

        probe = probe_map.get(url)
        q5 = engagement_question(probe, "Q5")
        confidence = "medium"
        if q5 is not None:
            if q5.get("answered") and containment_ratio(title_desc, q5.get("answer", "")) >= 0.2:
                continue  # probe disagrees with the deterministic miss

        findings.append(
            make_finding(
                check_id="E-ANSWER-01",
                category=CATEGORY,
                title=f"Title/description promises what the body doesn't deliver on {url}",
                severity="medium",
                confidence=confidence,
                mechanism="An AI-referred visitor arrives having read a "
                "citation built from the title/description; a body that "
                "doesn't deliver on it breaks the promise that got them to click.",
                impact="The page does not appear to deliver what its own title/description promised.",
                observed_signal=f"word-containment overlap {overlap:.2f} (< 0.20)",
                evidence=f"Title/description: \"{title_desc}\" vs. body excerpt: \"{body[:200]}\"",
                observation_ids=[page["observation_id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Rewrite the title/description to match the body, or add the promised content to the body.",
                    "priority": "medium",
                    "how_to_fix": f"Align the title/description on {url} with what the page body actually covers.",
                    "validation": "Re-extract; containment overlap exceeds 0.20.",
                },
            )
        )
    return findings


def check_e_answer_02(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    from _engagement_util import rendered_pages_only

    findings = []
    for url, page in rendered_pages_only(store).items():
        overlay = find_blocking_overlay(page["html"])
        if not overlay:
            continue
        findings.append(
            make_finding(
                check_id="E-ANSWER-02",
                category=CATEGORY,
                title=f"Entry-blocking interstitial on {url}",
                severity="high",
                confidence="high",
                mechanism="A visitor arriving expecting a specific answer, met "
                "instead with a blocking overlay, cannot see that answer "
                "without first dismissing something they didn't ask for.",
                impact="Content is not visible to an arriving visitor without dismissing this element first.",
                observed_signal=f"visible-by-default {overlay['tag']} (role={overlay['role']!r}, class={overlay['class']!r})",
                evidence=f"Blocking element found on {url}: {overlay}",
                observation_ids=[page["observation_id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Defer the overlay until after the visitor has seen the primary content.",
                    "priority": "high",
                    "how_to_fix": f"Make the overlay on {url} dismissible without obscuring the answer, or delay it.",
                    "validation": "Re-render; no blocking dialog/modal is present-and-visible at first paint.",
                },
            )
        )
    return findings


def check_e_answer_03(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    from _engagement_util import rendered_pages_only

    findings = []
    for url, page in rendered_pages_only(store).items():
        gate = find_paywall_gate(page["html"])
        if not gate:
            continue
        content_len = len(main_text(page["html"]))
        if content_len <= 400:
            continue  # an honest preview, not a mismatch
        findings.append(
            make_finding(
                check_id="E-ANSWER-03",
                category=CATEGORY,
                title=f"Citation content gated for the human visitor on {url}",
                severity="high",
                confidence="high",
                mechanism="A citation pipeline may quote text a human visitor "
                "is then asked to pay or sign in to see -- flagged as a "
                "citation-mismatch risk, not as an error in the paywall itself.",
                impact="A visitor following a citation to this page may be unable to verify it without paying or signing in.",
                observed_signal=f"gating element ({gate['tag']}, class={gate['class']!r}) co-present with {content_len} chars of content",
                evidence=f"Gate text: \"{gate['text']}\"",
                observation_ids=[page["observation_id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "State plainly, above the gate, what the paywalled content covers.",
                    "priority": "high",
                    "how_to_fix": f"Add a pre-gate summary on {url} that matches what's citable, or expose a structured-data summary.",
                    "validation": "Re-render; the gate and substantive content no longer structurally overlap, or the pre-gate text matches.",
                },
            )
        )
    return findings


def check_e_answer_04(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    from _engagement_util import rendered_pages_only

    probe_map = probes(store)
    findings = []

    for url, page in rendered_pages_only(store).items():
        probe = probe_map.get(url)
        if not probe:
            continue
        for question in probe.get("value", {}).get("questions", []):
            # Explicit relevant:true required, never defaulted -- matching
            # crawl-render-audit's convention (an unset field is never fair
            # game for a finding). A permissive default here would let a
            # tangential, answered-but-unimportant fact fire a
            # citation-landing-mismatch finding nobody would actually cite.
            if not question.get("answered") or not question.get("relevant"):
                continue
            span = question.get("evidence_span")
            if not span:
                continue

            fraction = scroll_depth_fraction(page["html"], span)
            if fraction is None:
                continue
            collapsed = is_in_collapsed_region(page["html"], span)
            if fraction <= 0.5 and not collapsed:
                continue
            if has_anchor_nav_to_answer(page["html"], span):
                continue  # a long page that jumps straight to the answer isn't "buried"

            findings.append(
                make_finding(
                    check_id="E-ANSWER-04",
                    category=CATEGORY,
                    title=f"Citation-landing mismatch on {url}",
                    severity="high",
                    confidence="high",
                    mechanism="The extraction probe confirms the fact is "
                    "extractable; this measures whether it's also locatable "
                    "on arrival -- a fact a machine could cite that an "
                    "arriving human can't actually find.",
                    impact="An arriving visitor is unlikely to see the fact a citation pointed them to.",
                    observed_signal=(
                        f"scroll-depth fraction {fraction:.2f} (> 0.50)" if fraction > 0.5 else "answer is inside a collapsed region"
                    ),
                    evidence=f"Probe question '{question.get('id')}' answer: \"{span}\"",
                    observation_ids=[probe["id"], page["observation_id"]],
                    source_urls=[url],
                    affected=affected_block([url]),
                    suggested_action={
                        "summary": "Move the confirmed-answer sentence earlier in the rendered content.",
                        "priority": "high",
                        "how_to_fix": f"Surface \"{span}\" above the fold and outside any collapsed region on {url}.",
                        "validation": "Re-render; the same evidence span sits above the 0.50 scroll-depth fraction and outside any collapsed region.",
                    },
                )
            )
    return findings


def _outgoing_classifications(url: str, page: Dict[str, Any]) -> List[str]:
    links = content_area_links(page["html"], url)
    return [classify_link(link, url) for link in links]


# Two destinations, because one is satisfied by a bare "Home" link, which
# returns the visitor to the start rather than letting them continue.
MIN_NAVIGATION_DESTINATIONS = 2


def check_e_continue_01(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    pages = effective_pages(store)
    if len(pages) < 2:
        return []  # a genuinely single-page site has nowhere "deeper" to go, by design -- not a defect

    classifications = page_classifications(store)
    probe_map = probes(store)
    findings = []

    for url, page in pages.items():
        if is_terminal_page(url, classifications.get(url)):
            continue
        kinds = _outgoing_classifications(url, page)
        if not kinds:
            continue  # E-CONTINUE-02's case
        if any(k == "internal_content" for k in kinds):
            continue

        # This check asserts the visitor has "no way to go deeper or sideways
        # without returning to search". Standing navigation that reaches real
        # internal destinations falsifies exactly that claim, so the same
        # evidence that clears E-CONTINUE-02 has to clear this one. What remains
        # reportable is narrower than E-CONTINUE-02's: a page whose own content
        # points only off-site *and* which offers no navigation to come back to.
        if len(navigation_destinations(page["html"], url)) >= MIN_NAVIGATION_DESTINATIONS:
            continue

        probe = probe_map.get(url)
        q8 = engagement_question(probe, "Q8")
        confidence = "high"
        if q8 is not None:
            confidence = "medium"
            if q8.get("answered"):
                continue  # probe found a plausible next step; don't assert none exists

        findings.append(
            make_finding(
                check_id="E-CONTINUE-01",
                category=CATEGORY,
                title=f"No relevant next step on {url}",
                severity="medium",
                confidence=confidence,
                mechanism="A visitor who got their answer (or didn't) has no "
                "way to go deeper or sideways without returning to search.",
                impact="This page offers no genuine continuation for an AI-referred visitor.",
                observed_signal=f"{len(kinds)} outgoing content-area link(s), none classify as internal content",
                evidence=f"Outgoing link kinds on {url}: {kinds}",
                observation_ids=[page["observation_id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Add a link to related content, a topic hub, or a clear onward action.",
                    "priority": "medium",
                    "how_to_fix": f"Add a genuine internal content link on {url}.",
                    "validation": "Re-fetch; >=1 outgoing link now points to genuine internal content.",
                },
            )
        )
    return findings


def check_e_continue_02(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    pages = effective_pages(store)
    if len(pages) < 2:
        return []  # a genuinely single-page site has nowhere "deeper" to go, by design -- not a defect

    classifications = page_classifications(store)
    findings = []

    for url, page in pages.items():
        if is_terminal_page(url, classifications.get(url)):
            continue
        kinds = _outgoing_classifications(url, page)
        if kinds:
            continue

        # No in-content link is not the same as no way out. Standing navigation
        # that reaches real internal destinations is a continuation path, and
        # treating its absence from the prose as a dead end reports every
        # well-built brochure and documentation page as a defect.
        navigation = navigation_destinations(page["html"], url)
        if len(navigation) >= MIN_NAVIGATION_DESTINATIONS:
            continue

        findings.append(
            make_finding(
                check_id="E-CONTINUE-02",
                category=CATEGORY,
                title=f"Dead end at {url}",
                severity="medium",
                confidence="high",
                mechanism="There is structurally nothing to click that leads "
                "deeper into the site, either from this page's own content or "
                "from its navigation.",
                impact="A visitor has no way to continue browsing from this page.",
                observed_signal="no in-content internal links and fewer than "
                f"{MIN_NAVIGATION_DESTINATIONS} internal destination(s) in site navigation",
                evidence=f"Outgoing content-area link kinds on {url}: {kinds}; "
                f"internal navigation destinations: {navigation}",
                observation_ids=[page["observation_id"]],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Add at least one in-content link to related material.",
                    "priority": "medium",
                    "how_to_fix": f"Add a content-region link on {url}.",
                    "validation": "Re-fetch; content-region out-degree is >=1.",
                },
            )
        )
    return findings


def check_e_continue_03(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    pages = effective_pages(store)
    classifications = page_classifications(store)
    findings = []

    for url, page in pages.items():
        if is_terminal_page(url, classifications.get(url)):
            continue
        hub = hub_url(url)
        if not hub or hub not in pages:
            continue  # never invented from URL shape alone -- hub must be demonstrably crawled

        links = content_area_links(page["html"], url)
        hrefs = {link["href"].rstrip("/") for link in links}
        if hub.rstrip("/") in hrefs:
            continue

        findings.append(
            make_finding(
                check_id="E-CONTINUE-03",
                category=CATEGORY,
                title=f"No route to the broader topic hub from {url}",
                severity="low",
                confidence="high",
                mechanism="A visitor satisfied by the specific answer but "
                "wanting the wider picture has no way to get there without "
                "leaving the site.",
                impact="A visitor cannot reach the broader topic/category from this page.",
                observed_signal=f"hub {hub} exists in the crawl but is not linked from {url}",
                evidence=f"Hub URL {hub} not found among outgoing links of {url}",
                observation_ids=[page["observation_id"], pages[hub]["observation_id"]],
                source_urls=[url, hub],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Add a link back to the broader topic/category page.",
                    "priority": "low",
                    "how_to_fix": f"Link {hub} from {url}.",
                    "validation": "Re-fetch; the hub URL now appears among the page's outgoing links.",
                },
            )
        )
    return findings


def check_e_continue_04(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    fetches = http_fetches(store)
    pages = effective_pages(store)
    by_source: Dict[str, List[Any]] = {}

    for url, page in pages.items():
        for link in content_area_links(page["html"], url):
            target = link["href"]
            target_obs = fetches.get(target)
            if not target_obs:
                continue  # never fetched to verify; only reasons over what's already observed
            status = target_obs["value"].get("status_code")
            if status and status >= 400:
                by_source.setdefault(url, []).append((target, status, target_obs["id"]))

    findings = []
    for url, broken in by_source.items():
        page = pages[url]
        findings.append(
            make_finding(
                check_id="E-CONTINUE-04",
                category=CATEGORY,
                title=f"Broken internal links from {url}",
                severity="medium",
                confidence="high",
                mechanism="A visitor who takes the offered next step and hits "
                "a dead link has, functionally, the same dead-end experience "
                "as a page with no next step at all.",
                impact="These offered next steps do not actually work.",
                observed_signal=f"{len(broken)} outgoing link(s) return >=400",
                evidence="; ".join(f"{target} -> {status}" for target, status, _ in broken[:5]),
                observation_ids=[page["observation_id"]] + [oid for _, _, oid in broken],
                source_urls=[url] + [t for t, _, _ in broken],
                affected=affected_block([t for t, _, _ in broken]),
                suggested_action={
                    "summary": "Fix or remove the broken outgoing link(s).",
                    "priority": "medium",
                    "how_to_fix": f"Update the links on {url} pointing at broken targets.",
                    "validation": "Re-fetch the target(s); status is <400.",
                },
            )
        )
    return findings


CHECKS_NO_PROFILE = [
    check_e_orient_03,
    check_e_orient_04,
    check_e_answer_01,
    check_e_answer_02,
    check_e_answer_03,
    check_e_answer_04,
    check_e_continue_01,
    check_e_continue_02,
    check_e_continue_03,
    check_e_continue_04,
]


def detect_engagement(store: Dict[str, Any], entity_profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    findings.extend(check_e_orient_01(store, entity_profile))
    for check in CHECKS_NO_PROFILE:
        findings.extend(check(store))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run E-ORIENT/E-ANSWER/E-CONTINUE over an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--entity-profile", help="Path to entity_profile JSON (built by entity-semantic-audit). Optional.")
    parser.add_argument("--out", help="Path to write findings JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    entity_profile = None
    if args.entity_profile:
        with open(args.entity_profile, "r", encoding="utf-8") as handle:
            entity_profile = json.load(handle)

    findings = detect_engagement(store, entity_profile)
    output = json.dumps(findings, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
