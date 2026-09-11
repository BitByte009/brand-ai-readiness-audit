"""D-TRUST-01..06. D-TRUST-05 gated on a real corroboration record.

Inputs:  store, claim_table (built by build_claim_table.py; built internally
         from `store` if not supplied), entity_profile (optional, for D-TRUST-05's
         identity-confusion guard)
Outputs: unscored findings
Nature:  deterministic + interpretation

See ../references/trust-checks.md for the twelve-field definition of every check
below, ../references/store-contract.md for the observation shapes read, and
../references/claim-table-contract.md for the claim table shape consumed.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional

from _trust_util import (
    RETHRESHOLD_FRESHNESS_DOWN_ARCHETYPES,
    RETHRESHOLD_FRESHNESS_UP_ARCHETYPES,
    SUPPRESSED_OPACITY_ARCHETYPES,
    affected_block,
    claim_corroborations,
    effective_pages,
    find_author_byline,
    has_contact_method,
    has_operator_identity,
    is_about_page,
    is_contact_page,
    make_finding,
    page_classifications,
    parse_date,
)
from build_claim_table import build_claim_table

from lib.common.extract import extract_text

CATEGORY = "trust"
_SEVERITY_UP = {"low": "medium", "medium": "high", "high": "high"}  # never promoted to critical
_SEVERITY_DOWN = {"high": "medium", "medium": "low", "low": "low"}


def _freshness_severity(store: Dict[str, Any], base: str = "medium") -> str:
    archetype = store.get("archetype", "")
    if archetype in RETHRESHOLD_FRESHNESS_UP_ARCHETYPES:
        return _SEVERITY_UP[base]
    if archetype in RETHRESHOLD_FRESHNESS_DOWN_ARCHETYPES:
        return _SEVERITY_DOWN[base]
    return base


def _has_date_signal(inventory: Dict[str, Any]) -> bool:
    return bool(inventory.get("schema_dates") or inventory.get("visible_dates") or inventory.get("header_date"))


def check_d_trust_01(store: Dict[str, Any], claim_table: Dict[str, Any]) -> List[Dict[str, Any]]:
    severity = _freshness_severity(store)

    by_page: Dict[str, List[Dict[str, Any]]] = {}
    for claim in claim_table["claims"]:
        if claim["claim_type"] == "time_sensitive":
            by_page.setdefault(claim["source_url"], []).append(claim)

    findings = []
    for url, claims in by_page.items():
        inventory = claim_table["date_inventory"].get(url, {})
        if _has_date_signal(inventory):
            continue
        findings.append(
            make_finding(
                check_id="D-TRUST-01",
                category=CATEGORY,
                title=f"Time-sensitive claims with no date signal on {url}",
                severity=severity,
                confidence="high",
                mechanism="A citation pipeline repeating a time-framed claim with "
                "no way to judge its currency risks repeating something already false.",
                impact="Machines cannot tell whether this claim is still current.",
                observed_signal=f"{len(claims)} time-sensitive phrase(s), 0 date signals on this page",
                evidence=f"Time-sensitive text: \"{claims[0]['text']}\"",
                observation_ids=[c["observation_id"] for c in claims],
                source_urls=[url],
                affected=affected_block([url]),
                suggested_action={
                    "summary": "Add a visible 'last updated' date or dateModified schema near the claim.",
                    "priority": severity,
                    "how_to_fix": f"State when the claim on {url} was last verified or updated.",
                    "validation": "Re-fetch the page; a date signal is now present.",
                },
            )
        )
    return findings


def check_d_trust_02(store: Dict[str, Any], claim_table: Dict[str, Any]) -> List[Dict[str, Any]]:
    audited_at = parse_date(store.get("collected_at", ""))
    if not audited_at:
        return []

    severity = _freshness_severity(store)
    findings = []

    for claim in claim_table["claims"]:
        if claim["claim_type"] not in ("dated_event", "dated_offer"):
            continue
        claim_date = parse_date(claim.get("date_value", ""))
        if not claim_date or claim_date >= audited_at:
            continue

        # The claim's date is in the past -- but if the PAGE ITSELF was
        # published on or before that date, the claim was true when it was
        # written (an archival news article about a then-upcoming event is
        # not stale, it's an accurate historical record). Only fire when the
        # page has no such evidence, or was itself published/updated after
        # the event and is still presenting it as current.
        inventory = claim_table["date_inventory"].get(claim["source_url"], {})
        page_dates = [
            d for iso in inventory.get("schema_dates", []) + inventory.get("visible_dates", []) for d in [parse_date(iso)] if d
        ]
        if page_dates and min(page_dates) <= claim_date:
            continue

        findings.append(
            make_finding(
                check_id="D-TRUST-02",
                category=CATEGORY,
                title=f"Stale {claim['claim_type'].replace('_', ' ')} on {claim['source_url']}",
                severity=severity,
                confidence="high",
                mechanism="A stale forward-framed claim is actively misleading if "
                "repeated, not merely uninformative.",
                impact="Repeating this claim would assert something that has already lapsed.",
                observed_signal=f"date {claim_date.isoformat()} is before the audit date {audited_at.isoformat()}",
                evidence=claim["text"],
                observation_ids=[claim["observation_id"]],
                source_urls=[claim["source_url"]],
                affected=affected_block([claim["source_url"]]),
                suggested_action={
                    "summary": "Update or remove the stale date-bound claim, offer, or event.",
                    "priority": severity,
                    "how_to_fix": f"Refresh or remove the claim on {claim['source_url']}.",
                    "validation": "Re-fetch; the extracted date is no longer past relative to its framing.",
                },
            )
        )

    return findings


def check_d_trust_03(store: Dict[str, Any], claim_table: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for claim in claim_table["claims"]:
        if claim["claim_type"] == "entity_fact" and claim.get("key"):
            by_key.setdefault(claim["key"], []).append(claim)

    findings = []
    for key, claims in by_key.items():
        seen_values: Dict[str, Dict[str, Any]] = {}
        for claim in claims:
            value = claim["value"]
            if value in seen_values:
                continue
            conflicting = next((c for v, c in seen_values.items() if v != value
                                and c.get("time_context", []) == claim.get("time_context", [])), None)
            if conflicting:
                findings.append(
                    make_finding(
                        check_id="D-TRUST-03",
                        category=CATEGORY,
                        title=f"Internal contradiction on '{key}'",
                        severity="high",
                        confidence="high",
                        mechanism="Conflicting asserted values give a citation "
                        "pipeline no reliable single fact to repeat, and may cause "
                        "it to prefer a stale or wrong version.",
                        impact=f"Machines cannot determine one authoritative value for '{key}'.",
                        observed_signal=f"'{key}' differs: \"{conflicting['value']}\" vs. \"{value}\"",
                        evidence=f"\"{conflicting['text']}\" ({conflicting['source_url']}) vs. \"{claim['text']}\" ({claim['source_url']})",
                        observation_ids=[conflicting["observation_id"], claim["observation_id"]],
                        source_urls=[conflicting["source_url"], claim["source_url"]],
                        affected=affected_block([conflicting["source_url"], claim["source_url"]]),
                        suggested_action={
                            "summary": f"Reconcile the conflicting '{key}' values, or state explicitly why they differ.",
                            "priority": "high",
                            "how_to_fix": "Update the incorrect page, or label the distinguishing context (e.g. different time periods or entities).",
                            "validation": "Re-extract; the two values now match or carry an explicit distinguishing label.",
                        },
                    )
                )
                break  # one aggregated finding per key is enough evidence of the contradiction class
            seen_values[value] = claim
    return findings


def check_d_trust_04(store: Dict[str, Any], claim_table: Dict[str, Any]) -> List[Dict[str, Any]]:
    unattributed = [c for c in claim_table["claims"] if c["claim_type"] == "superlative_stat" and not c.get("attributed")]
    if not unattributed:
        return []

    urls = [c["source_url"] for c in unattributed]
    return [
        make_finding(
            check_id="D-TRUST-04",
            category=CATEGORY,
            title="Unattributed falsifiable claims",
            severity="low",
            confidence="high",
            mechanism="An assistant repeating an unsourced falsifiable claim as "
            "fact inherits the risk of it being wrong or outdated, with no way "
            "to check.",
            impact="These claims cannot be verified independently before being repeated.",
            observed_signal=f"{len(unattributed)} falsifiable claim(s) with no nearby citation",
            evidence="; ".join(f"\"{c['text']}\" ({c['source_url']})" for c in unattributed[:5]),
            observation_ids=[c["observation_id"] for c in unattributed],
            source_urls=urls,
            affected=affected_block(urls, total_in_scope=len(claim_table["claims"])),
            suggested_action={
                "summary": "Add a source next to each falsifiable claim, or rephrase as non-falsifiable language.",
                "priority": "low",
                "how_to_fix": "Link to the underlying data or report for each statistic/ranking claim.",
                "validation": "Re-fetch; the claim now carries a nearby citation or has been rephrased.",
            },
        )
    ]


def check_d_trust_05(store: Dict[str, Any], claim_table: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    claims_by_id = {c["id"]: c for c in claim_table["claims"]}

    for claim_id, corroboration in claim_corroborations(store).items():
        value = corroboration.get("value", {})
        if not value.get("performed"):
            continue  # never fires without a real record -- corroboration-honesty.md

        claim = claims_by_id.get(claim_id)
        if not claim:
            continue

        sources = value.get("sources", [])
        matched = [s for s in sources if s.get("entity_match")]
        if matched:
            continue

        identity_confusion = bool(sources) and not matched
        observed_signal = (
            f"{len(sources)} source(s) found, all about a different/unconfirmed entity"
            if identity_confusion
            else "0 independent sources found"
        )

        findings.append(
            make_finding(
                check_id="D-TRUST-05",
                category=CATEGORY,
                title="Claim exists only on the entity's own site" if not identity_confusion else "Apparent corroboration is about a different entity",
                severity="medium",
                confidence="high",
                mechanism="A claim repeated only by its own source is weaker "
                "evidence than one corroborated independently; a source that is "
                "actually about a different, similarly named entity is worse "
                "than no corroboration at all.",
                impact="This claim cannot be verified against an independent, confirmed-same-entity source.",
                observed_signal=observed_signal,
                evidence=f"Query: {value.get('query')}; sources: {', '.join(s.get('url', '') for s in sources[:5]) or 'none'}",
                observation_ids=[corroboration["id"]],
                source_urls=[claim["source_url"]],
                affected=affected_block([claim["source_url"]]),
                suggested_action={
                    "summary": "Build an external presence that states this fact independently and unambiguously about this entity.",
                    "priority": "medium",
                    "how_to_fix": "Pursue a press mention, directory listing, or review platform entry for this claim.",
                    "validation": "Re-run corroboration; >=1 source now exists with entity_match true.",
                },
            )
        )
    return findings


def check_d_trust_06(store: Dict[str, Any], claim_table: Dict[str, Any]) -> List[Dict[str, Any]]:
    from lib.common.extract import language_supported
    archetype = store.get("archetype", "")
    if archetype in SUPPRESSED_OPACITY_ARCHETYPES:
        return []

    pages = effective_pages(store)
    if not pages:
        return []
    findings = []

    # Parsed once per page and reused below for both the contact-info and
    # byline checks -- each used to call extract_text() (a full HTML parse)
    # separately, doubling the per-page parsing cost.
    page_texts = {url: extract_text(page["html"]) for url, page in pages.items()}

    classifications = page_classifications(store)
    has_operator = any(
        is_about_page(url, classifications.get(url))
        or has_operator_identity(page["html"], page_texts[url])
        for url, page in pages.items()
    )
    has_contact = any(
        is_contact_page(url, classifications.get(url))
        or has_contact_method(page["html"], page_texts[url])
        for url, page in pages.items()
    )
    if not has_operator and not has_contact and all(language_supported(page["html"]) for page in pages.values()):
        findings.append(
            make_finding(
                check_id="D-TRUST-06",
                category=CATEGORY,
                title="No operator identity or contact method found",
                severity="medium",
                confidence="high",
                mechanism="A citation pipeline weighing whether to trust and "
                "repeat a claim has no visible accountability trail to check.",
                impact="Nothing on the site identifies who is accountable for its claims.",
                observed_signal="no operator-identity or actionable contact signal found sitewide",
                evidence="No classified accountability role, named operator, contact method, or exact role-path fallback found on any sampled page",
                observation_ids=[],
                source_urls=sorted(pages.keys()),
                affected=affected_block(sorted(pages.keys())),
                suggested_action={
                    "summary": "Identify the site operator and provide a visible contact method.",
                    "priority": "medium",
                    "how_to_fix": "State who operates the site and add an email, phone, contact form, or postal contact.",
                    "validation": "Re-crawl; an operator-identity or actionable contact signal is now present.",
                },
            )
        )

    article_urls = [url for url, obs in classifications.items() if obs.get("value", {}).get("page_type") == "article"]
    evaluated_articles = [url for url in article_urls if url in pages and language_supported(pages[url]["html"])]
    anonymous_articles = [
        url
        for url in evaluated_articles
        if not find_author_byline(pages[url]["html"], page_texts[url])
    ]
    if anonymous_articles:
        findings.append(
            make_finding(
                check_id="D-TRUST-06",
                category=CATEGORY,
                title="Article pages carry no named author",
                severity="medium",
                confidence="high",
                mechanism="A citation pipeline weighing whether to trust and "
                "repeat a claim has no named source to attribute or check.",
                impact="Claims on the affected articles cannot be attributed to a named, accountable author.",
                observed_signal=f"{len(anonymous_articles)}/{len(evaluated_articles)} evaluated article page(s) have no named author",
                evidence=f"No JSON-LD, meta, rel=author, itemprop, or visible byline on: {', '.join(sorted(anonymous_articles)[:5])}",
                observation_ids=[pages[url]["observation_id"] for url in anonymous_articles]
                + [classifications[url]["id"] for url in anonymous_articles],
                source_urls=anonymous_articles,
                affected=affected_block(anonymous_articles, total_in_scope=len(evaluated_articles)),
                suggested_action={
                    "summary": "Add a named author identity to each affected article.",
                    "priority": "medium",
                    "how_to_fix": "State the author's name and expose it through a byline, author metadata, rel=author, or JSON-LD.",
                    "validation": "Re-crawl; every affected article carries a resolvable named author.",
                },
            )
        )

    return findings


CHECKS = [
    check_d_trust_01,
    check_d_trust_02,
    check_d_trust_03,
    check_d_trust_04,
    check_d_trust_05,
    check_d_trust_06,
]


def detect_trust(store: Dict[str, Any], claim_table: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if claim_table is None:
        claim_table = build_claim_table(store)

    findings: List[Dict[str, Any]] = []
    for check in CHECKS:
        findings.extend(check(store, claim_table))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run D-TRUST-01..06 over an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--claim-table", help="Path to a precomputed claim_table JSON file. Built from --store if omitted.")
    parser.add_argument("--out", help="Path to write findings JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    claim_table = None
    if args.claim_table:
        with open(args.claim_table, "r", encoding="utf-8") as handle:
            claim_table = json.load(handle)

    findings = detect_trust(store, claim_table)
    output = json.dumps(findings, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
