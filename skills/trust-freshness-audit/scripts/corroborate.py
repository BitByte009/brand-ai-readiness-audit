"""Builds CLAIM_CORROBORATION observations. Never fetches the live web itself.

Inputs:  a claim, optional search results, optional entity_profile
Outputs: a CLAIM_CORROBORATION observation
Nature:  capability-detected recorder + deterministic entity_match check

Given no search results, returns an honest `performed: false` record -- the same
graceful-degradation pattern `lib/site_observer/render.py` uses for an absent
headless-browser capability. Given results (e.g. from the invoking agent's
`WebSearch` tool, or injected for testing), records them and runs the
identity-confusion guard deterministically. See
../references/corroboration-honesty.md for the rules this exists to enforce.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from _trust_util import is_corroboration_worthy, source_matches_entity

from lib.common.observations import make_observation


def build_corroboration_query(claim: Dict[str, Any]) -> str:
    return claim.get("text", "").strip()


def record_corroboration(
    claim: Dict[str, Any],
    search_results: Optional[List[Dict[str, Any]]] = None,
    entity_profile: Optional[Dict[str, Any]] = None,
    method: str = "web_search",
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one CLAIM_CORROBORATION observation.

    `search_results is None` means the capability was not available (or was not
    attempted) for this run -- distinct from `search_results == []`, which means
    a search WAS performed and genuinely found nothing. Only the former yields
    `performed: false`; conflating the two is exactly the dishonesty
    `corroboration-honesty.md` rule 4 exists to prevent.
    """
    query = build_corroboration_query(claim)

    if search_results is None:
        value: Dict[str, Any] = {
            "claim_id": claim["id"],
            "performed": False,
            "query": query,
            "method": method,
            "timestamp": timestamp,
            "sources": [],
            "reason": "SEARCH_UNAVAILABLE",
        }
    else:
        sources = [
            {
                "url": result.get("url", ""),
                "title": result.get("title", ""),
                "snippet": result.get("snippet", ""),
                "entity_match": source_matches_entity(result, entity_profile),
            }
            for result in search_results
        ]
        value = {
            "claim_id": claim["id"],
            "performed": True,
            "query": query,
            "method": method,
            "timestamp": timestamp,
            "sources": sources,
        }

    return make_observation("CLAIM_CORROBORATION", claim.get("source_url", ""), value)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a CLAIM_CORROBORATION observation for one claim, given optional search results."
    )
    parser.add_argument("--claim", required=True, help="Path to a JSON file containing one claim (from the claim table).")
    parser.add_argument("--results", help="Path to a JSON file of search results ([{url,title,snippet}, ...]). Omit if unavailable.")
    parser.add_argument("--entity-profile", help="Path to the entity_profile JSON file, for the entity_match check.")
    parser.add_argument("--method", default="web_search")
    parser.add_argument("--timestamp", help="ISO-8601 timestamp for the corroboration record.")
    parser.add_argument("--out", help="Path to write the observation JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.claim, "r", encoding="utf-8") as handle:
        claim = json.load(handle)

    if args.results and not is_corroboration_worthy(claim):
        print(
            f"warning: claim {claim.get('id')} is a '{claim.get('claim_type')}' claim -- "
            "D-TRUST-05 cannot act on it, so this lookup was likely unnecessary "
            "(see is_corroboration_worthy() / corroboration-honesty.md).",
            file=sys.stderr,
        )

    results = None
    if args.results:
        with open(args.results, "r", encoding="utf-8") as handle:
            results = json.load(handle)

    entity_profile = None
    if args.entity_profile:
        with open(args.entity_profile, "r", encoding="utf-8") as handle:
            entity_profile = json.load(handle)

    observation = record_corroboration(
        claim, search_results=results, entity_profile=entity_profile, method=args.method, timestamp=args.timestamp
    )
    output = json.dumps(observation, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
