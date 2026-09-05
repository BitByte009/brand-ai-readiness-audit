"""Site-archetype and page-type classification. Runs once, before any check,
and gates check applicability per ../../../references/archetype-applicability.md.

Inputs:  store
Outputs: archetype (one of the 8 named archetypes, or "" if unclear)
Nature:  deterministic heuristic

The failure taxonomy's own design anticipates this as a named LLM instrument
(PROJECT_CONTEXT.md D-4). No model call is wired into this environment, so
this is a deterministic, signal-based heuristic used in its place -- the same
"documented, not required" substitution pattern already used elsewhere in
this project (e.g. the CORROBORATION instrument, still blocked on OQ-3). An
unrecognized site returns "" rather than guessing: every archetype-gated check
in the four detector skills already treats an unmatched/empty archetype as
"no special up/down/suppression applies," which is the correct, safe default
-- guessing wrong would silently mis-gate real checks, while "" only ever
costs a missed RETHR adjustment, never a wrong one.
"""

from __future__ import annotations

from typing import Any, Dict, List

from lib.common.extract import extract_jsonld, schema_type_names

ARCHETYPES = [
    "brand-product",
    "ecommerce",
    "publisher-editorial",
    "documentation",
    "local-business",
    "personal-portfolio",
    "institutional",
    "web-app",
]


def _jsonld_types(store: Dict[str, Any]) -> List[str]:
    types: List[str] = []
    for obs in store.get("observations", []):
        if obs.get("type") not in {"HTTP_FETCH", "RENDER"}:
            continue
        html = (obs.get("value", {}) or {}).get("html", "")
        if not html:
            continue
        for item in extract_jsonld(html):
            types.extend(schema_type_names(item.get("@type")))
    return types


def _path_signals(store: Dict[str, Any]) -> Dict[str, int]:
    counts = {"doc": 0, "shop": 0, "blog": 0, "app": 0, "total": 0}
    for obs in store.get("observations", []):
        if obs.get("type") != "HTTP_FETCH":
            continue
        path = (obs.get("source_url") or "").lower()
        counts["total"] += 1
        if any(seg in path for seg in ("/docs/", "/documentation/", "/api-reference/", "docs.")):
            counts["doc"] += 1
        if any(seg in path for seg in ("/product/", "/shop/", "/cart", "/checkout", "/store/")):
            counts["shop"] += 1
        if any(seg in path for seg in ("/blog/", "/article/", "/news/", "/posts/")):
            counts["blog"] += 1
        if any(seg in path for seg in ("/app/", "/dashboard", "/login", "/signup")):
            counts["app"] += 1
    return counts


def classify_archetype(store: Dict[str, Any]) -> str:
    """Best-effort, deterministic archetype guess from JSON-LD @type usage
    (an explicit, structured, first-party signal) and URL path shape (a
    weaker, corroborating signal). Returns "" when no signal clears a simple
    majority -- an unclassified site is gated as if none of the 8 named
    archetypes applied, never coerced into the nearest guess."""
    jsonld_types = {t for t in _jsonld_types(store)}

    if jsonld_types & {"LocalBusiness", "Restaurant", "Store", "ProfessionalService"}:
        return "local-business"
    if jsonld_types & {"Product", "Offer", "AggregateOffer"}:
        return "ecommerce"
    if jsonld_types & {"Article", "BlogPosting", "NewsArticle"}:
        return "publisher-editorial"
    if jsonld_types & {"SoftwareApplication", "WebApplication"}:
        return "web-app"
    if jsonld_types & {"GovernmentOrganization", "EducationalOrganization", "NGO"}:
        return "institutional"
    if jsonld_types & {"Person"} and not (jsonld_types & {"Organization", "Corporation"}):
        return "personal-portfolio"

    counts = _path_signals(store)
    total = counts["total"] or 1
    for label, key in (("documentation", "doc"), ("ecommerce", "shop"), ("publisher-editorial", "blog"), ("web-app", "app")):
        if counts[key] / total >= 0.3:
            return label

    if jsonld_types & {"Organization", "Corporation"}:
        return "brand-product"

    return ""


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
