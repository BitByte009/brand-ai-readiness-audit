"""Normalizes detector output into the finding schema; rejects structurally
invalid or unsupported findings.

Inputs:  pooled findings (from all four detector skills)
Outputs: (normalized_findings, rejected)
Nature:  deterministic

See ../references/evidence-validation.md for the rejection criteria and
../references/confidence-model.md for the thin-sample confidence adjustment
applied here.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional, Tuple

from _prioritization_util import CONFIDENCE_ORDER, SEVERITY_ORDER

REQUIRED_STRING_FIELDS = ["check_id", "category", "title", "evidence", "mechanism", "impact", "observed_signal"]
REQUIRED_LIST_FIELDS = ["observation_ids", "source_urls"]
THIN_SAMPLE_FLOOR = 3


def _rejection_reason(finding: Any) -> Optional[str]:
    if not isinstance(finding, dict):
        return "not a finding object"

    for field in REQUIRED_STRING_FIELDS:
        value = finding.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"missing or empty required field '{field}'"

    for field in REQUIRED_LIST_FIELDS:
        if not isinstance(finding.get(field), list):
            return f"'{field}' must be a list"

    severity = str(finding.get("severity", "")).lower()
    if severity not in SEVERITY_ORDER:
        return f"invalid severity '{finding.get('severity')}'"

    confidence = str(finding.get("confidence", "")).lower()
    if confidence not in CONFIDENCE_ORDER:
        return f"invalid confidence '{finding.get('confidence')}'"

    affected = finding.get("affected")
    if not isinstance(affected, dict) or "count" not in affected or "total_in_scope" not in affected:
        return "missing or malformed 'affected' block"

    suggested = finding.get("suggested_action")
    if not isinstance(suggested, dict) or not suggested.get("summary") or not suggested.get("priority"):
        return "missing or malformed 'suggested_action' block"

    return None


def normalize_findings(findings: List[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (normalized, rejected). `rejected` entries are
    {"finding": <original>, "reason": <str>} -- never entering findings[] or
    demoted[]. See evidence-validation.md."""
    normalized: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for finding in findings:
        reason = _rejection_reason(finding)
        if reason:
            rejected.append({"finding": finding, "reason": reason})
            continue

        clone = dict(finding)
        clone["severity"] = str(clone["severity"]).lower()
        clone["confidence"] = str(clone["confidence"]).lower()
        clone["suggested_action"] = dict(clone["suggested_action"])

        # confidence-model.md: a thin supporting sample (< 3 in scope) drops
        # confidence one tier -- applied uniformly here so it can't drift into
        # four different per-skill implementations.
        affected = clone["affected"]
        total_in_scope = affected.get("total_in_scope", affected.get("count", 1)) or 1
        if total_in_scope < THIN_SAMPLE_FLOOR and clone["confidence"] == "high":
            clone["confidence"] = "medium"
            clone["_normalization_notes"] = clone.get("_normalization_notes", []) + [
                f"confidence -1 tier: supporting sample ({total_in_scope}) below the thin-sample floor ({THIN_SAMPLE_FLOOR})"
            ]

        normalized.append(clone)

    return normalized, rejected


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize pooled findings and reject structurally invalid ones.")
    parser.add_argument("--findings", required=True, help="Path to a JSON file containing a list of pooled findings.")
    parser.add_argument("--out", help="Path to write {'normalized':[...], 'rejected':[...]} JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.findings, "r", encoding="utf-8") as handle:
        findings = json.load(handle)

    normalized, rejected = normalize_findings(findings)
    output = json.dumps({"normalized": normalized, "rejected": rejected}, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
