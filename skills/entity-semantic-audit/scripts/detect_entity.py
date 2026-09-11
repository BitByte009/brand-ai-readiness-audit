"""D-ENTITY-01..06, archetype-gated.

Inputs:  store, entity_profile (built by build_entity_profile.py; built internally
         from `store` if not supplied, so this script also runs standalone)
Outputs: unscored findings
Nature:  deterministic + interpretation

See ../references/entity-checks.md for the twelve-field definition of every check
below, ../references/store-contract.md for the observation shapes read, and
../references/entity-profile-contract.md for the profile shape consumed.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from _entity_util import (
    RETHRESHOLD_NAME_ARCHETYPES,
    RETHRESHOLD_OFFERING_ARCHETYPES,
    RETHRESHOLD_TYPE_ARCHETYPES,
    SUPPRESSED_OFFERING_ARCHETYPES,
    affected_block,
    depth1_urls,
    homepage_url,
    identity_question,
    make_finding,
    normalize_address_part,
    normalize_name,
    probes,
    text_similarity,
)
from build_entity_profile import build_entity_profile

CATEGORY = "identity"
_CONFIDENCE_DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}
_SEVERITY_DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}


def check_d_entity_01(store: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    field = profile["fields"]["canonical_name"]
    candidates = field["candidates"]
    archetype = profile.get("archetype", "")
    # archetype-applicability.md: RETHR on documentation and personal-portfolio --
    # a sparse or implicit name is normal on a minimal personal site or a docs
    # project, not a defect of the same magnitude as on a commercial site.
    downgrade = archetype in RETHRESHOLD_NAME_ARCHETYPES
    severity = _SEVERITY_DOWNGRADE["high"] if downgrade else "high"

    if not candidates:
        pages = profile["pages_considered"]
        return [
            make_finding(
                check_id="D-ENTITY-01",
                category=CATEGORY,
                title="No canonical entity name found anywhere on the site",
                severity=severity,
                confidence="high",
                mechanism="A citation pipeline needs some name to attribute a fact "
                "to; an entity with no name candidate anywhere is never citable.",
                impact="Nothing on the site can be cited as coming from a named entity.",
                observed_signal="0 name candidates found in title, h1, schema, or footer",
                evidence="No name candidate found on any sampled page",
                observation_ids=[],
                source_urls=pages,
                affected=affected_block(pages),
                suggested_action={
                    "summary": "State the entity's name in the title, h1, and structured data.",
                    "priority": severity,
                    "how_to_fix": "Add a clear name to <title>, <h1>, and an Organization/Person JSON-LD node.",
                    "validation": "Re-extract name candidates; at least one is found.",
                },
            )
        ]

    if field["consistent"]:
        return []

    counts = Counter(normalize_name(c["value"]) for c in candidates)
    total = sum(counts.values())
    variants = []
    for norm, count in counts.most_common():
        raw = next(c["value"] for c in candidates if normalize_name(c["value"]) == norm)
        variants.append(f"\"{raw}\" ({count}/{total})")

    return [
        make_finding(
            check_id="D-ENTITY-01",
            category=CATEGORY,
            title="No canonical entity name stated consistently",
            severity=severity,
            confidence="high",
            mechanism="A citation pipeline that sees multiple name variants for one "
            "entity may cite the wrong one or split attribution across variants.",
            impact="A machine cannot determine one authoritative name to cite.",
            observed_signal=f"{len(counts)} distinct name forms, no single form >=70% share",
            evidence=f"Competing name forms: {', '.join(variants)}",
            observation_ids=[c["observation_id"] for c in candidates],
            source_urls=[c["source_url"] for c in candidates],
            affected=affected_block([c["source_url"] for c in candidates]),
            suggested_action={
                "summary": "State the canonical name consistently in title, h1, and structured data sitewide.",
                "priority": severity,
                "how_to_fix": "Pick one dominant name form; if a legal/trading-name pair is intentional, link them in one sentence.",
                "validation": "Re-extract name candidates; the normalized-core set converges to one value at >=70% share.",
            },
        )
    ]


def check_d_entity_02(store: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    from lib.common.extract import language_supported
    from lib.common.pages import effective_pages
    if any(not language_supported(p['html']) for p in effective_pages(store).values()):
        return []
    field = profile["fields"]["entity_type"]
    if field["value"]:
        return []

    archetype = profile.get("archetype", "")
    # archetype-applicability.md: RETHR on personal-portfolio -- a personal site
    # rarely needs to explicitly say "I am a person."
    downgrade = archetype in RETHRESHOLD_TYPE_ARCHETYPES
    severity = _SEVERITY_DOWNGRADE["high"] if downgrade else "high"

    has_probe = bool(probes(store))
    confidence = "high" if has_probe else "medium"
    if downgrade:
        confidence = _CONFIDENCE_DOWNGRADE[confidence]

    return [
        make_finding(
            check_id="D-ENTITY-02",
            category=CATEGORY,
            title="Entity type never stated plainly",
            severity=severity,
            confidence=confidence,
            mechanism="An assistant that cannot categorize the entity cannot frame "
            "a citation correctly (company vs. nonprofit vs. person vs. publication).",
            impact="Machines cannot determine what kind of thing this entity is.",
            observed_signal="no type-word, JSON-LD @type label, or identity-probe answer found across sampled pages",
            evidence="No plain statement of entity type found in prose, schema, or the identity probe",
            observation_ids=[],
            source_urls=profile["pages_considered"],
            affected=affected_block(profile["pages_considered"]),
            suggested_action={
                "summary": "Add one plain sentence stating what kind of entity this is.",
                "priority": severity,
                "how_to_fix": "State the entity's category near the top of the homepage or about page.",
                "validation": "Re-extract; a type-word or the identity probe's type answer is now present.",
            },
        )
    ]


def check_d_entity_03(store: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    from _entity_util import corroboration

    corrob = corroboration(store)
    if not corrob or not corrob.get("value", {}).get("performed"):
        return []  # never inferred, never treated as "no collision found"

    matches = corrob["value"].get("matches", [])
    # Distinctness is by competing entity (source_url), not by name string -- the
    # whole point of a collision is that multiple *different* entities share our
    # queried name, so they are expected to have the same name text.
    distinct_entities = {m.get("source_url") for m in matches if m.get("source_url")}
    if len(distinct_entities) < 2:
        return []

    if profile["fields"]["distinguishing_attributes"]["present"]:
        return []  # any one distinguisher present suppresses this check entirely

    entity_type = profile["fields"]["entity_type"]["value"]
    adjacent = bool(entity_type) and any(m.get("category") == entity_type for m in matches)
    severity = "high" if adjacent else "medium"

    match_summary = ", ".join(f"{m.get('name')} ({m.get('source_url', '')})" for m in matches[:5])

    return [
        make_finding(
            check_id="D-ENTITY-03",
            category=CATEGORY,
            title="Ambiguous entity: name collides with other known entities",
            severity=severity,
            confidence="high",
            mechanism="An assistant may attribute a competing entity's facts to "
            "this one, or decline to cite either, when nothing distinguishes them.",
            impact="This entity may be confused with a similarly named one in citations.",
            observed_signal=f"{len(distinct_entities)} distinct competing entities observed; no type, location, or identity anchor stated",
            evidence=f"Query: {corrob['value'].get('query')}; competing matches: {match_summary}",
            observation_ids=[corrob["id"]],
            source_urls=profile["pages_considered"],
            affected=affected_block(profile["pages_considered"]),
            suggested_action={
                "summary": "State category, operating scope, and an identity anchor in plain text.",
                "priority": severity,
                "how_to_fix": "Add a sentence naming the entity's category and location, and an Organization JSON-LD node with sameAs.",
                "validation": "Re-extract the entity profile; type, location, or identity anchor is now populated.",
            },
        )
    ]


def _min_similarity_pair(candidates: List[Dict[str, Any]]) -> Optional[Tuple[float, Dict[str, Any], Dict[str, Any]]]:
    best = None
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            if a["source_url"] == b["source_url"]:
                continue
            ratio = text_similarity(a["value"], b["value"])
            if best is None or ratio < best[0]:
                best = (ratio, a, b)
    return best


def _addresses_conflict(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if a.get("branch_name") and b.get("branch_name") and a["branch_name"] != b["branch_name"]:
        return False  # legitimate multi-location business
    fields_a, fields_b = a.get("fields", {}), b.get("fields", {})
    # Compare normalized forms ('123 Main St' == '123 Main Street') so the same
    # real address written two conventional ways is never flagged as a conflict.
    return any(
        fields_a.get(k)
        and fields_b.get(k)
        and normalize_address_part(fields_a[k]) != normalize_address_part(fields_b[k])
        for k in fields_a
    )


def check_d_entity_04(store: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings = []
    archetype = profile.get("archetype", "")
    downgrade = archetype == "personal-portfolio"

    desc_candidates = profile["fields"]["description"]["candidates"]
    pair = _min_similarity_pair(desc_candidates)
    if pair and pair[0] < 0.5:
        _, a, b = pair
        severity = "medium" if downgrade else "high"
        confidence = _CONFIDENCE_DOWNGRADE["medium"] if downgrade else "medium"
        findings.append(
            make_finding(
                check_id="D-ENTITY-04",
                category=CATEGORY,
                title="Entity description differs materially across pages",
                severity=severity,
                confidence=confidence,
                mechanism="Conflicting self-descriptions give a citation pipeline "
                "no reliable single fact to repeat.",
                impact="A machine cannot determine one authoritative description of this entity.",
                observed_signal=f"description similarity ratio {pair[0]:.2f} between {a['source_url']} and {b['source_url']}",
                evidence=f"\"{a['value']}\" ({a['source_url']}) vs. \"{b['value']}\" ({b['source_url']})",
                observation_ids=[a["observation_id"], b["observation_id"]],
                source_urls=[a["source_url"], b["source_url"]],
                affected=affected_block([a["source_url"], b["source_url"]]),
                suggested_action={
                    "summary": "Reconcile the conflicting descriptions sitewide.",
                    "priority": severity,
                    "how_to_fix": "Use one consistent entity-level description, or label distinct pages explicitly if the variation is intentional.",
                    "validation": "Re-extract; the two candidates now match or are each explicitly labeled as distinct.",
                },
            )
        )

    location_candidates = profile["fields"]["location"]["candidates"]
    for i in range(len(location_candidates)):
        for j in range(i + 1, len(location_candidates)):
            a, b = location_candidates[i], location_candidates[j]
            if a["source_url"] == b["source_url"]:
                continue
            if _addresses_conflict(a, b):
                severity = "medium" if downgrade else "high"
                confidence = "medium" if downgrade else "high"
                findings.append(
                    make_finding(
                        check_id="D-ENTITY-04",
                        category=CATEGORY,
                        title="Entity address differs across pages with no distinguishing label",
                        severity=severity,
                        confidence=confidence,
                        mechanism="Conflicting addresses for one undifferentiated "
                        "entity give a citation pipeline no reliable location to repeat.",
                        impact="A machine cannot determine one authoritative address for this entity.",
                        observed_signal=f"conflicting address fields between {a['source_url']} and {b['source_url']}",
                        evidence=f"\"{a['value']}\" ({a['source_url']}) vs. \"{b['value']}\" ({b['source_url']})",
                        observation_ids=[a["observation_id"], b["observation_id"]],
                        source_urls=[a["source_url"], b["source_url"]],
                        affected=affected_block([a["source_url"], b["source_url"]]),
                        suggested_action={
                            "summary": "Reconcile the conflicting addresses, or label each location explicitly.",
                            "priority": severity,
                            "how_to_fix": "Add a distinguishing name (branch/location) to each address node, or correct the conflicting value.",
                            "validation": "Re-extract; the addresses now match or each carries an explicit distinguishing label.",
                        },
                    )
                )
                break
        else:
            continue
        break

    return findings


def check_d_entity_05(
    store: Dict[str, Any], profile: Dict[str, Any], sibling_fired: bool
) -> List[Dict[str, Any]]:
    if not sibling_fired:
        return []  # never standalone -- compound trigger only

    anchor = profile["identity_anchor"]
    if anchor["present"]:
        return []

    pages = profile["pages_considered"]
    return [
        make_finding(
            check_id="D-ENTITY-05",
            category=CATEGORY,
            title="No machine-readable identity anchor",
            severity="medium",
            confidence="high",
            mechanism="Structured identity anchors (sameAs, a self-referencing "
            "url) are how a citation pipeline cross-checks which entity a name "
            "refers to; combined with an already-observed name/type clarity gap, "
            "there is no anchor to fall back on either.",
            impact="No structured cross-check exists for this entity's identity, compounding the name/type gap already found.",
            observed_signal="no Organization/LocalBusiness/Person node with sameAs or a self-referencing url",
            evidence="No identity anchor found on any sampled page",
            observation_ids=[],
            source_urls=pages,
            affected=affected_block(pages),
            suggested_action={
                "summary": "Add an Organization/Person/LocalBusiness JSON-LD node with sameAs links to official profiles.",
                "priority": "medium",
                "how_to_fix": "Add sameAs (or at minimum a self-referencing url) to the identity JSON-LD node.",
                "validation": "Re-fetch; the node is present with a non-empty sameAs or a self-referencing url.",
            },
        )
    ]


def check_d_entity_06(store: Dict[str, Any], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    from lib.common.extract import language_supported
    from lib.common.pages import effective_pages
    if any(not language_supported(p['html']) for p in effective_pages(store).values()):
        return []
    archetype = profile.get("archetype", "")
    if archetype in SUPPRESSED_OFFERING_ARCHETYPES:
        return []

    home = homepage_url(store)
    if not home:
        return []  # applicability unmet: cannot evaluate "one click away" without a homepage

    scope_urls = {home, *depth1_urls(store, home)}
    offering_field = profile["fields"]["primary_offering"]
    in_scope = [c for c in offering_field["candidates"] if c.get("source_url") in scope_urls]
    if in_scope:
        return []

    probe_map = probes(store)
    scope_has_probe_miss = any(
        (q := identity_question(probe_map.get(u), "Q3")) and not q.get("answered") for u in scope_urls
    )
    confidence = "high" if scope_has_probe_miss else "medium"

    severity = "high"
    if archetype in RETHRESHOLD_OFFERING_ARCHETYPES:
        severity = "medium"
        confidence = "medium"

    return [
        make_finding(
            check_id="D-ENTITY-06",
            category=CATEGORY,
            title="Primary offering unclear on the homepage and one click from it",
            severity=severity,
            confidence=confidence,
            mechanism="An assistant asked what this entity does needs a plain "
            "answer; marketing abstraction with no concrete statement of the "
            "offering produces no quotable answer.",
            impact="Machines cannot determine what this entity sells, builds, or does.",
            observed_signal=f"no offering statement found on the homepage or its {len(scope_urls) - 1} depth-1 page(s)",
            evidence=f"Checked: {', '.join(sorted(scope_urls))}",
            observation_ids=[],
            source_urls=sorted(scope_urls),
            affected=affected_block(sorted(scope_urls)),
            suggested_action={
                "summary": "State plainly, on the homepage or a page one click from it, what the entity offers or does.",
                "priority": severity,
                "how_to_fix": "Add a concrete offering sentence to the homepage or a directly-linked page.",
                "validation": "Re-fetch the homepage and its depth-1 pages; the offering pattern or identity probe now succeeds on at least one.",
            },
        )
    ]


def detect_entity(store: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if profile is None:
        profile = build_entity_profile(store)
    if not profile.get("pages_considered"):
        return []

    findings: List[Dict[str, Any]] = []
    d01 = check_d_entity_01(store, profile)
    d02 = check_d_entity_02(store, profile)
    findings.extend(d01)
    findings.extend(d02)
    findings.extend(check_d_entity_03(store, profile))
    findings.extend(check_d_entity_04(store, profile))
    findings.extend(check_d_entity_05(store, profile, sibling_fired=bool(d01 or d02)))
    findings.extend(check_d_entity_06(store, profile))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run D-ENTITY-01..06 over an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--profile", help="Path to a precomputed entity_profile JSON file. Built from --store if omitted.")
    parser.add_argument("--out", help="Path to write findings JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    profile = None
    if args.profile:
        with open(args.profile, "r", encoding="utf-8") as handle:
            profile = json.load(handle)

    findings = detect_entity(store, profile)
    output = json.dumps(findings, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
