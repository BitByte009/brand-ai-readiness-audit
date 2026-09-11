"""Generates proactive opportunities from gaps, not defects.

Inputs:  store, demoted findings (from evidence-prioritization)
Outputs: proactive_opportunities[]
Nature:  deterministic

See ../references/proactive-layer.md for the five sources and the rules
(never a defect framing, never generic, never counted in severity totals).
Two of the five documented sources (1: unanswered probe questions, 3:
corroboration-surface gaps) require the CORROBORATION/probe instrument,
which is not wired into this environment (see lib/site_observer/probe.py) --
this module honestly produces nothing for those rather than fabricate a
plausible-sounding gap it never actually checked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
if str(MARKETPLACE_ROOT) not in sys.path:
    sys.path.insert(0, str(MARKETPLACE_ROOT))

from lib.common.extract import extract_jsonld, schema_type_names  # noqa: E402
from lib.common.pages import effective_pages


def _identity_anchor_opportunity(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """proactive-layer.md source 2: identity anchors the site does not
    occupy. `sameAs` is the one standard, machine-checkable anchor already
    available from JSON-LD alone -- no corroboration lookup needed."""
    fetch_observations = [{"source_url": url, "value": page, "id": page["observation_id"]}
                          for url, page in effective_pages(store).items()]
    if not fetch_observations:
        return None

    has_organization_or_person = False
    has_same_as = False
    example_url = None
    observation_ids = []
    for obs in fetch_observations:
        html = (obs.get("value", {}) or {}).get("html", "")
        if not html:
            continue
        for item in extract_jsonld(html):
            types = schema_type_names(item.get('@type'))
            if any(t in ("Organization", "Person", "LocalBusiness", "Corporation") for t in types):
                has_organization_or_person = True
                example_url = example_url or obs.get("source_url")
                observation_ids.append(obs['id'])
                if item.get("sameAs"):
                    has_same_as = True

    if has_organization_or_person and not has_same_as:
        return {
            "source": "identity_anchor_gap",
            "source_urls": [example_url],
            "observation_ids": sorted(set(observation_ids)),
            "title": "No sameAs links from the entity's structured data",
            "opportunity": (
                f"The Organization/Person markup on {example_url} carries no `sameAs` array. "
                "If verified profiles exist, add links to the entity's authoritative profiles (official social accounts, "
                "Wikidata/Wikipedia, a company registry page) gives citation pipelines a "
                "corroboration path that does not depend on prose alone."
            ),
            "expected_mechanism": "sameAs links let a consumer cross-check the entity against an independent, authoritative source.",
            "expected_effect": "Higher confidence in entity resolution for systems that follow sameAs.",
        }
    return None


def _demoted_opportunities(demoted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """proactive-layer.md source 4: findings demoted below the confidence
    floor. Reframed as an opportunity, never as the defect they were
    demoted from -- the demotion already means evidence-prioritization
    would not assert them as confident defects."""
    opportunities = []
    for finding in demoted:
        opportunities.append(
            {
                "source": "demoted_finding",
                "source_urls": finding.get("source_urls", []),
                "observation_ids": finding.get("observation_ids", []),
                "title": f"Worth a closer look: {finding.get('title', finding.get('check_id', ''))}",
                "opportunity": (
                    f"{finding.get('observed_signal', finding.get('evidence', ''))} "
                    "This did not clear the evidence bar for a confident finding, but may still be worth reviewing."
                ),
                "expected_mechanism": finding.get("mechanism", ""),
                "expected_effect": finding.get("impact", ""),
            }
        )
    return opportunities


def generate_proactive_opportunities(store: Dict[str, Any], demoted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    opportunities: List[Dict[str, Any]] = []
    identity_gap = _identity_anchor_opportunity(store)
    if identity_gap:
        opportunities.append(identity_gap)
    opportunities.extend(_demoted_opportunities(demoted))
    return opportunities


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
