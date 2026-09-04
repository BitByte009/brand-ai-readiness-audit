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

from _prioritization_util import confidence_index, finding_url_set

MERGE_JACCARD_FLOOR = 0.5


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _merge_group(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Field-by-field merge policy, per dedupe-rules.md: union observation_ids/
    source_urls, max of affected.total_in_scope, the highest confidence in the
    group. All other fields come from whichever source has the highest
    confidence then the largest affected.count, as a deterministic tie-break.

    affected.count is the size of the UNION of every source's affected URLs,
    never a sum: the merge criterion (Jaccard >= 0.5) requires the sources'
    URL sets to substantially overlap in the first place, so summing their
    counts double-counts every URL both findings already agreed was affected
    -- inflating scope, and therefore severity, in exactly the case (two
    detections of the same underlying defect) merging exists to normalize
    away."""
    all_observation_ids = sorted({oid for f in sources for oid in f.get("observation_ids", [])})
    all_source_urls = sorted({u for f in sources for u in f.get("source_urls", [])})
    total_count = len(all_source_urls)
    total_in_scope = max((f.get("affected") or {}).get("total_in_scope", 0) for f in sources)
    best_confidence = max((f["confidence"] for f in sources), key=confidence_index)

    base = max(sources, key=lambda f: (confidence_index(f["confidence"]), (f.get("affected") or {}).get("count", 0)))

    merged = dict(base)
    merged["observation_ids"] = all_observation_ids
    merged["source_urls"] = all_source_urls
    merged["affected"] = {"count": total_count, "sample_urls": all_source_urls[:5], "total_in_scope": total_in_scope}
    merged["confidence"] = best_confidence
    merged["suggested_action"] = dict(base["suggested_action"])
    return merged


def merge_duplicate_findings(findings: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Findings sharing a check_id and a substantially overlapping URL set
    (Jaccard >= 0.5) are the same underlying (check_id, template_cluster)
    finding surfacing twice in the pooled set -- merge rather than
    duplicate-report it. Each detector skill already aggregates internally
    (PROJECT_CONTEXT.md D-7); this is a defensive second pass over the *pooled*
    set, not the primary aggregation."""
    by_check: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        by_check[finding["check_id"]].append(finding)

    merged_findings: List[Dict[str, Any]] = []
    merge_log: List[Dict[str, Any]] = []

    for check_id, group in by_check.items():
        clusters: List[Dict[str, Any]] = []
        for finding in group:
            urls = finding_url_set(finding)
            target = next((c for c in clusters if _jaccard(c["urls"], urls) >= MERGE_JACCARD_FLOOR), None)
            if target is None:
                clusters.append({"urls": urls, "sources": [finding]})
            else:
                target["sources"].append(finding)
                target["urls"] = target["urls"] | urls

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
