"""Aggregates by (check_id, template_cluster) defensively and deduplicates
same-check_id findings across the pooled set.

Inputs:  normalized findings
Outputs: (deduplicated findings, merge_log)
Nature:  deterministic

See ../references/dedupe-rules.md for the merge criteria and the field-by-field
merge policy. Cross-skill relationship marking (`related_findings`) happens
later, in scripts/score.py, after final ids are assigned -- see that file and
dedupe-rules.md's "Cross-skill relationship table".
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from _prioritization_util import affected_url_set, confidence_index


def _dedupe_key(finding: Dict[str, Any]) -> tuple:
    """Identity of a defect class, independent of its evidence wording.

    Detectors may provide a stable ``dedupe_key``.  The mechanism is the safe
    fallback because one check id can contain genuinely different subchecks
    (for example D-ENTITY-04 description and address conflicts).
    """
    return (finding["check_id"], finding.get("dedupe_key") or finding.get("mechanism", ""))


def _merge_group(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Field-by-field merge policy, per dedupe-rules.md: union observation_ids/
    source_urls, max of affected.total_in_scope, the highest confidence in the
    group. All other fields come from whichever source has the highest
    confidence then the largest affected.count, as a deterministic tie-break.

    Scope is a lower bound: preserve the largest declared count and the union
    of sampled affected URLs. Never sum overlapping counts or treat evidence
    context URLs as affected instances. Canonical JSON breaks otherwise equal
    ties without depending on detector execution order."""
    all_observation_ids = sorted({oid for f in sources for oid in f.get("observation_ids", [])})
    all_source_urls = sorted({u for f in sources for u in f.get("source_urls", [])})
    affected_urls = sorted({u for f in sources for u in affected_url_set(f)})
    total_count = max(len(affected_urls), max((f.get("affected") or {}).get("count", 0) for f in sources))
    measured_totals = [
        (f.get("affected") or {}).get("total_in_scope")
        for f in sources
        if isinstance((f.get("affected") or {}).get("total_in_scope"), (int, float))
    ]
    total_in_scope = max(measured_totals) if measured_totals else None
    best_confidence = max((f["confidence"] for f in sources), key=confidence_index)

    base = max(sources, key=lambda f: (confidence_index(f["confidence"]), (f.get("affected") or {}).get("count", 0), json.dumps(f, sort_keys=True)))

    merged = dict(base)
    merged["observation_ids"] = all_observation_ids
    merged["source_urls"] = all_source_urls
    merged["affected"] = {"count": total_count, "sample_urls": affected_urls[:5], "total_in_scope": total_in_scope}
    merged["confidence"] = best_confidence
    merged["suggested_action"] = dict(base["suggested_action"])
    return merged


def merge_duplicate_findings(findings: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Merge duplicate defect classes whose asserted affected sets overlap.

    Connected components make the result permutation-invariant; unlike a
    Jaccard cutoff, the rule does not change merely because one detector saw a
    wider sample. Context-only ``source_urls`` never establish identity.
    """
    by_check: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        by_check[_dedupe_key(finding)].append(finding)

    merged_findings: List[Dict[str, Any]] = []
    merge_log: List[Dict[str, Any]] = []

    for (check_id, _subtype), group in sorted(by_check.items()):
        remaining = sorted(group, key=lambda f: json.dumps(f, sort_keys=True))
        clusters: List[Dict[str, Any]] = []
        while remaining:
            seed = remaining.pop(0)
            component = [seed]
            urls = affected_url_set(seed)
            changed = True
            while changed:
                changed = False
                for candidate in list(remaining):
                    candidate_urls = affected_url_set(candidate)
                    if urls and candidate_urls and urls & candidate_urls:
                        remaining.remove(candidate)
                        component.append(candidate)
                        urls |= candidate_urls
                        changed = True
            clusters.append({"urls": urls, "sources": component})

        for cluster in clusters:
            sources = cluster["sources"]
            if len(sources) == 1:
                merged_findings.append(sources[0])
                continue
            merged = _merge_group(sources)
            merged_findings.append(merged)
            merge_log.append(
                {
                    "check_id": check_id,
                    "merged_count": len(sources),
                    "surviving_title": merged["title"],
                    "combined_affected_count": merged["affected"]["count"],
                }
            )

    return merged_findings, merge_log


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Deduplicate normalized findings by (check_id, overlapping URL set).")
    parser.add_argument("--findings", required=True, help="Path to a JSON file containing a list of normalized findings.")
    parser.add_argument("--out", help="Path to write {'findings':[...], 'merge_log':[...]} JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.findings, "r", encoding="utf-8") as handle:
        findings = json.load(handle)

    merged, merge_log = merge_duplicate_findings(findings)
    output = json.dumps({"findings": merged, "merge_log": merge_log}, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
