"""Entity fact table with per-page, per-field provenance. Emitted for downstream skills.

Inputs:  store
Outputs: entity_profile
Nature:  deterministic first; falls back to the PROBE identity questions
         (Q2/Q3/Q4, references/probe-questions.md) only when a field has zero
         deterministic candidates.

See ../references/entity-profile-contract.md for the exact output shape and
../references/store-contract.md for the observation types read here.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from _entity_util import (
    IDENTITY_NODE_TYPES,
    LEGAL_REGISTER_SOURCES,
    PUBLIC_FACING_SOURCES,
    TYPE_LABEL_MAP,
    effective_pages,
    footer_copyright_name,
    identity_question,
    jsonld_nodes_of_type,
    normalize_name,
    offering_pattern_match,
    probes,
    title_segments,
    type_keyword_match,
)

from lib.common.extract import extract_metadata, extract_text, schema_type_matches

FIELD_NAMES = [
    "canonical_name",
    "entity_type",
    "description",
    "primary_offering",
    "location",
    "official_domain",
    "aliases",
    "distinguishing_attributes",
]

_ADDRESS_PARTS = ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")


def _first_h1(html: str) -> Optional[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else None


def _format_address(address: Dict[str, Any]) -> str:
    parts = [str(address[k]) for k in _ADDRESS_PARTS if address.get(k)]
    return ", ".join(parts)


def _collect_name_candidates(pages: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates = []
    for url, page in pages.items():
        html = page["html"]
        oid = page["observation_id"]

        title = extract_metadata(html)["title"].strip()
        for segment in title_segments(title):
            candidates.append({"value": segment, "source": "title", "source_url": url, "observation_id": oid})

        h1 = _first_h1(html)
        if h1:
            candidates.append({"value": h1, "source": "h1", "source_url": url, "observation_id": oid})

        for node in jsonld_nodes_of_type(html, IDENTITY_NODE_TYPES):
            if node.get("name"):
                candidates.append(
                    {"value": str(node["name"]).strip(), "source": "schema", "source_url": url, "observation_id": oid}
                )

        footer_name = footer_copyright_name(html)
        if footer_name:
            candidates.append({"value": footer_name, "source": "footer", "source_url": url, "observation_id": oid})
    return candidates


# A page title is a *document* label; an Organization/Person node's `name` is an
# *entity* declaration. Counting them as equal-weight votes conflates the two,
# so a site with correct per-page titles ("Support - Acme", "Pricing - Acme")
# looks like a site that cannot decide what it is called. When the site states
# its identity in machine-readable form, and that statement passes the tests
# below, it is the better evidence and inferred candidates do not outvote it --
# it is self-declared, typed, and exactly the field AI systems read for entity
# resolution.
#
# Authority is earned, never assumed. All five conditions must hold:
#   1. typed as an identity node and carrying a non-empty name (F);
#   2. exactly one distinct name across the whole site (E: competing
#      organizations mean the site has not made a single claim);
#   3. repeated -- present on at least MIN_STRUCTURED_IDENTITY_PAGES pages and
#      on at least half the pages considered (C: markup on one page of many is
#      a page-level assertion, not a sitewide one);
#   4. not pointing somewhere else -- a declared `url` must belong to this site,
#      which is what keeps an embedded third-party node (a vendor, a payment
#      provider, a review platform) from being adopted as the operator;
#   5. corroborated by something a human can see -- the name must appear in a
#      page title or visible text (B: markup that contradicts the visible site
#      is exactly the conflict D-ENTITY-01 exists to report, so it must not be
#      able to silence itself).
MIN_STRUCTURED_IDENTITY_PAGES = 2


def _structured_identity(pages: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The site's machine-readable identity, if it earns authority. Else None."""
    nodes = []
    for url, page in pages.items():
        for node in jsonld_nodes_of_type(page["html"], IDENTITY_NODE_TYPES):
            name = str(node.get("name") or "").strip()
            if name:
                nodes.append((url, page["observation_id"], node, name))
    if not nodes:
        return None

    names = {normalize_name(name) for _, _, _, name in nodes}
    if len(names) != 1:
        return None  # condition 2

    pages_with_identity = {url for url, _, _, _ in nodes}
    if len(pages_with_identity) < MIN_STRUCTURED_IDENTITY_PAGES:
        return None  # condition 3
    if len(pages_with_identity) * 2 < len(pages):
        return None  # condition 3

    # "www." is a presentation prefix, not a different site: a node declaring
    # https://example.com while the audit runs against https://www.example.com
    # is the same operator, and rejecting it there would break the single most
    # common real-world spelling.
    def bare_host(value: str) -> str:
        host = (urlparse(value).hostname or "").lower().rstrip(".")
        return host[4:] if host.startswith("www.") else host

    site_hosts = {bare_host(url) for url in pages}
    site_hosts.discard("")
    for _, _, node, _ in nodes:
        declared = str(node.get("url") or "").strip()
        if not declared:
            continue
        host = bare_host(declared)
        if host and host not in site_hosts and not any(host.endswith("." + h) for h in site_hosts):
            return None  # condition 4

    name = nodes[0][3]
    normalized = normalize_name(name)
    visible = any(
        normalized in normalize_name(extract_metadata(page["html"])["title"] + " " + extract_text(page["html"]))
        for page in pages.values()
    )
    if not visible:
        return None  # condition 5

    descriptions = {str(node.get("description") or "").strip() for _, _, node, _ in nodes}
    descriptions.discard("")
    return {
        "name": name,
        "description": descriptions.pop() if len(descriptions) == 1 else None,
        "pages": sorted(pages_with_identity),
        "observation_ids": sorted({oid for _, oid, _, _ in nodes}),
    }


def _canonical_name_field(candidates: List[Dict[str, Any]],
                          identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if identity is not None:
        # Candidates are kept verbatim: authority changes which name wins,
        # never what was observed, so the evidence trail stays complete.
        return {"value": identity["name"], "candidates": candidates,
                "consistent": True, "determined_by": "structured_identity"}
    if not candidates:
        return {"value": None, "candidates": [], "consistent": False, "determined_by": "none"}

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in candidates:
        groups.setdefault(normalize_name(c["value"]), []).append(c)
    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_norm, top_group = ranked[0]
    total = sum(len(g) for _, g in ranked)
    share = len(top_group) / total

    consistent = len(ranked) <= 1 or share >= 0.7

    if not consistent and len(ranked) == 2:
        # A single legal-register name (schema/footer only) against a
        # consistently-used public-facing name is a legal/trading-name pair,
        # not an inconsistency -- e.g. JSON-LD Organization.name carrying the
        # registered legal name while title/h1 carry the trading name
        # throughout. Never suppresses a genuine second PUBLIC-FACING name.
        _, minority_group = ranked[1]
        minority_is_legal_only = all(c["source"] in LEGAL_REGISTER_SOURCES for c in minority_group)
        dominant_is_public_facing = any(c["source"] in PUBLIC_FACING_SOURCES for c in top_group)
        if minority_is_legal_only and dominant_is_public_facing:
            consistent = True

    dominant_value = Counter(c["value"] for c in top_group).most_common(1)[0][0]

    return {"value": dominant_value, "candidates": candidates, "consistent": consistent, "determined_by": "deterministic"}


def _entity_type_field(store: Dict[str, Any], pages: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    for url, page in pages.items():
        html = page["html"]
        text = extract_text(html)

        word = type_keyword_match(text)
        if word:
            return {
                "value": word,
                "candidates": [{"value": word, "source": "prose", "source_url": url, "observation_id": page["observation_id"]}],
                "consistent": True,
                "determined_by": "deterministic",
            }

        for node in jsonld_nodes_of_type(html, set(TYPE_LABEL_MAP.keys())):
            node_type = next(
                (known_type for known_type in TYPE_LABEL_MAP if schema_type_matches(node.get("@type"), known_type)),
                None,
            )
            label = TYPE_LABEL_MAP.get(node_type)
            if label and label in text.lower():
                return {
                    "value": label,
                    "candidates": [{"value": label, "source": "schema", "source_url": url, "observation_id": page["observation_id"]}],
                    "consistent": True,
                    "determined_by": "deterministic",
                }

    for url, probe in probes(store).items():
        question = identity_question(probe, "Q2")
        if question and question.get("answered"):
            answer = question.get("answer")
            return {
                "value": answer,
                "candidates": [{"value": answer, "source": "probe", "source_url": url, "observation_id": probe["id"]}],
                "consistent": True,
                "determined_by": "probe",
            }

    return {"value": None, "candidates": [], "consistent": False, "determined_by": "none"}


def _is_entity_subject_page(url: str) -> bool:
    """A page whose subject is the entity, not one of its topics."""
    path = (urlparse(url).path or "/").lower()
    return path in ("/", "") or "about" in path


def _is_entity_level_page(url: str, html: str) -> bool:
    path = (urlparse(url).path or "/").lower()
    if path == "/" or "about" in path:
        return True
    return bool(jsonld_nodes_of_type(html, {"Organization", "LocalBusiness"}))


def _description_field(pages: Dict[str, Dict[str, Any]],
                       identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Candidate self-descriptions of the *entity*.

    `<meta name="description">` describes the page it sits on -- distinct
    per-page descriptions are correct practice, not a contradiction -- so it is
    read as an entity description only on a page whose subject is the entity
    itself (home or about). An Organization node's `description` property is
    entity-scoped wherever it appears, so it is always eligible. Without that
    split, sitewide Organization markup made every page "entity-level" and every
    correct per-page description a conflicting claim about the company.
    """
    # When the site has declared an authoritative entity description in
    # machine-readable form, that is its self-description. A page's
    # `<meta name="description">` is a per-page snippet written to a different
    # length budget for a different purpose; differing wording between the two
    # is not the site contradicting itself, which is what D-ENTITY-04 asserts.
    authoritative_description = (identity or {}).get("description")

    candidates = []
    for url, page in pages.items():
        html = page["html"]
        if not _is_entity_level_page(url, html):
            continue

        if _is_entity_subject_page(url) and not authoritative_description:
            description = extract_metadata(html)["description"].strip()
            if description:
                candidates.append({"value": description, "source": "meta", "source_url": url, "observation_id": page["observation_id"]})

        for node in jsonld_nodes_of_type(html, {"Organization", "LocalBusiness"}):
            if node.get("description"):
                candidates.append(
                    {"value": str(node["description"]).strip(), "source": "schema", "source_url": url, "observation_id": page["observation_id"]}
                )

    return {
        "value": candidates[0]["value"] if candidates else None,
        "candidates": candidates,
        "consistent": None,  # compared pairwise by D-ENTITY-04, not collapsed to one bool here
        "determined_by": "deterministic" if candidates else "none",
    }


def _offering_field(store: Dict[str, Any], pages: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    candidates = []
    for url, page in pages.items():
        html = page["html"]
        text = extract_text(html)

        match = offering_pattern_match(text)
        if match:
            candidates.append({"value": match, "source": "prose", "source_url": url, "observation_id": page["observation_id"]})

        for node in jsonld_nodes_of_type(html, {"Product", "Service", "Offer"}):
            name = node.get("name")
            if name and str(name) in text:
                candidates.append({"value": str(name), "source": "schema", "source_url": url, "observation_id": page["observation_id"]})

    determined_by = "deterministic" if candidates else "none"
    if not candidates:
        for url, probe in probes(store).items():
            question = identity_question(probe, "Q3")
            if question and question.get("answered"):
                answer = question.get("answer")
                candidates.append({"value": answer, "source": "probe", "source_url": url, "observation_id": probe["id"]})
                determined_by = "probe"

    return {
        "value": candidates[0]["value"] if candidates else None,
        "candidates": candidates,
        "consistent": bool(candidates),
        "determined_by": determined_by,
    }


def _location_field(store: Dict[str, Any], pages: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    candidates = []
    for url, page in pages.items():
        html = page["html"]
        for node in jsonld_nodes_of_type(html, {"Organization", "LocalBusiness"}):
            address = node.get("address")
            if isinstance(address, dict):
                candidates.append(
                    {
                        "value": _format_address(address),
                        "fields": {k: address.get(k) for k in _ADDRESS_PARTS},
                        "branch_name": node.get("name"),
                        "source": "schema",
                        "source_url": url,
                        "observation_id": page["observation_id"],
                    }
                )

    determined_by = "deterministic" if candidates else "none"
    if not candidates:
        for url, probe in probes(store).items():
            question = identity_question(probe, "Q4")
            if question and question.get("answered"):
                answer = question.get("answer")
                candidates.append(
                    {"value": answer, "fields": {}, "branch_name": None, "source": "probe", "source_url": url, "observation_id": probe["id"]}
                )
                determined_by = "probe"

    return {
        "value": candidates[0]["value"] if candidates else None,
        "candidates": candidates,
        "consistent": None,  # compared pairwise by D-ENTITY-04
        "determined_by": determined_by,
    }


def _identity_anchor(pages: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    same_as = set()
    self_url = None
    observation_ids = []

    for url, page in pages.items():
        html = page["html"]
        for node in jsonld_nodes_of_type(html, IDENTITY_NODE_TYPES):
            raw_same_as = node.get("sameAs")
            entries = [raw_same_as] if isinstance(raw_same_as, str) else (raw_same_as or [])
            for entry in entries:
                if entry:
                    same_as.add(str(entry))
            if entries:
                observation_ids.append(page["observation_id"])

            if node.get("url") and not self_url:
                self_url = str(node["url"])
                observation_ids.append(page["observation_id"])

    return {
        "present": bool(same_as or self_url),
        "same_as": sorted(same_as),
        "self_url": self_url,
        "observation_ids": sorted(set(observation_ids)),
    }


# An alias is an alternate name for the *entity*. One page's title is a name for
# that page, and admitting it sitewide let a deep page satisfy its own brand
# identification with its own title -- which is what disabled E-ORIENT-01.
# A candidate therefore has to look like a real alternate identity: either the
# site repeats it across pages, or the site declares it structurally (a schema
# name, a footer legal name), which is an explicit claim rather than an
# inference from a document label.
MIN_ALIAS_PAGES = 2


def _aliases_field(candidates: List[Dict[str, Any]], canonical_field: Dict[str, Any]) -> Dict[str, Any]:
    dominant_norm = normalize_name(canonical_field["value"]) if canonical_field.get("value") else None

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        normalized = normalize_name(candidate["value"])
        if normalized == dominant_norm:
            continue
        groups.setdefault(normalized, []).append(candidate)

    alias_candidates = []
    for group in groups.values():
        pages = {c.get("source_url") for c in group}
        declared = any(c.get("source") in LEGAL_REGISTER_SOURCES for c in group)
        if len(pages) >= MIN_ALIAS_PAGES or declared:
            alias_candidates.extend(group)

    values = sorted({c["value"] for c in alias_candidates})
    return {
        "value": ", ".join(values) if values else None,
        "candidates": alias_candidates,
        "consistent": None,
        "determined_by": "deterministic" if alias_candidates else "none",
    }


def _official_domain_field(identity_anchor: Dict[str, Any]) -> Dict[str, Any]:
    value = identity_anchor["same_as"][0] if identity_anchor["same_as"] else identity_anchor["self_url"]
    return {
        "value": value,
        "candidates": [{"value": v, "source": "schema"} for v in identity_anchor["same_as"]],
        "consistent": None,
        "determined_by": "deterministic" if value else "none",
    }


def build_entity_profile(store: Dict[str, Any]) -> Dict[str, Any]:
    # Prefer the RENDER lens over raw HTTP_FETCH per page (see
    # _entity_util.effective_pages) so a JS-rendered site's client-rendered
    # identity content is read, not just its raw HTML shell.
    pages = effective_pages(store)

    name_candidates = _collect_name_candidates(pages)
    structured_identity = _structured_identity(pages)
    canonical_name_field = _canonical_name_field(name_candidates, structured_identity)
    entity_type_field = _entity_type_field(store, pages)
    description_field = _description_field(pages, structured_identity)
    offering_field = _offering_field(store, pages)
    location_field = _location_field(store, pages)
    identity_anchor = _identity_anchor(pages)
    aliases_field = _aliases_field(name_candidates, canonical_name_field)
    official_domain_field = _official_domain_field(identity_anchor)

    which_distinguishers = [
        name
        for name, present in (
            ("type", bool(entity_type_field["value"])),
            ("location", bool(location_field["candidates"])),
            ("identity_anchor", identity_anchor["present"]),
        )
        if present
    ]

    return {
        "fields": {
            "canonical_name": canonical_name_field,
            "entity_type": entity_type_field,
            "description": description_field,
            "primary_offering": offering_field,
            "location": location_field,
            "official_domain": official_domain_field,
            "aliases": aliases_field,
            "distinguishing_attributes": {"present": bool(which_distinguishers), "which": which_distinguishers},
        },
        "field_names": FIELD_NAMES,
        "identity_anchor": identity_anchor,
        "archetype": store.get("archetype", ""),
        "pages_considered": sorted(pages.keys()),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the entity_profile from an observation store.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--out", help="Path to write the entity_profile JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    profile = build_entity_profile(store)
    output = json.dumps(profile, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
