"""Confidence, severity matrix, demotion, distribution guard, ranking, scoring trace.

Inputs:  aggregated findings, optional store metadata
Outputs: scored findings + demoted[] + rejected[] + calibration_log + merge_log
Nature:  deterministic

See ../references/severity-matrix.md for the five-factor model (impact,
confidence, scope, importance, urgency), the critical-severity allowlist, the
distribution guard, and the ranking key this file implements.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional, Tuple

from _prioritization_util import affected_url_set, confidence_index, finding_url_set, severity_index, SEVERITY_ORDER
from aggregate_dedupe import merge_duplicate_findings
from normalize import normalize_findings

# severity-matrix.md: reachable ONLY by these four checks -- a ceiling AND a
# floor for exactly this set (nothing else may reach critical; these four are
# never capped down by a modifier either, since the check that produced them
# already determined it is total invisibility).
CRITICAL_ALLOWLIST = {"D-CRAWL-01", "D-CRAWL-03", "D-CRAWL-09", "D-CRAWL-15"}

# severity-matrix.md ranking key: actively-worsening or time-bound checks sort
# ahead of same-tier, same-confidence findings. Ranking-only -- never a
# severity input (see the doc for why).
URGENT_CHECK_IDS = {"D-CRAWL-15", "D-CRAWL-09", "D-CRAWL-04", "D-TRUST-02"}

DISTRIBUTION_GUARD_THRESHOLD = 0.3

# severity-matrix.md: below this many kept findings, a high+critical ratio
# is not evidence of a distribution problem -- it's just how many findings
# there happen to be. Recalibration describes a *pattern* across a report;
# with too few findings there is no pattern to correct, only individual
# severities that should stand on their own evidence.
DISTRIBUTION_GUARD_MIN_FINDINGS = 5


# ---------------------------------------------------------------------------
# Severity modifiers
# ---------------------------------------------------------------------------


def _scope_modifier(finding: Dict[str, Any]) -> Tuple[int, Optional[str]]:
    affected = finding.get("affected") or {}
    count = affected.get("count", 1)
    total = affected.get("total_in_scope")
    if not isinstance(total, (int, float)) or total <= 0:
        return 0, None
    if total <= 1:
        # No real population to be broad or narrow across -- a check whose
        # target is inherently singular (one robots.txt, one homepage) isn't
        # "broad scope" just because its one instance is affected. Without
        # this floor, every such finding scored 100% and silently inflated.
        return 0, None
    ratio = count / total
    if ratio >= 0.8:
        return 1, f"scope +1: affects {ratio:.0%} of in-scope items (>=80%)"
    if count == 1:
        return -1, "scope -1: single instance, non-central"
    return 0, None


def _url_identity(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port == 443) or (parsed.scheme.lower() == "http" and port == 80)
    netloc = host if not port or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower() or "https", netloc, path, parsed.query, ""))


def _importance_modifier(finding: Dict[str, Any], store: Optional[Dict[str, Any]] = None) -> Tuple[int, Optional[str]]:
    if not store:
        return 0, None
    target = store.get("target", {}) or {}
    requested = target.get("normalized_url") or target.get("requested_url")
    if requested:
        requested_id = _url_identity(str(requested))
        urls = affected_url_set(finding)
        if any(_url_identity(str(url)) == requested_id for url in urls):
            return 1, "importance +1: the explicitly requested audit target is affected"
    return 0, None


def _confidence_modifier(finding: Dict[str, Any]) -> Tuple[int, Optional[str]]:
    if finding.get("confidence") == "low":
        return -1, "confidence -1: low-confidence finding"
    return 0, None


def score_finding(finding: Dict[str, Any], store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply the modifier cell table to one finding, enforce the critical cap,
    and record a scoring_trace -- never mutating the original evidence fields
    (title, mechanism, impact, observed_signal, evidence, observation_ids,
    source_urls, affected, suggested_action.summary/how_to_fix/validation)."""
    original_severity = finding["severity"]
    original_confidence = finding["confidence"]
    index = severity_index(original_severity)

    trace: List[str] = []
    for modifier_fn in (_scope_modifier, _confidence_modifier):
        delta, note = modifier_fn(finding)
        if delta:
            index += delta
            trace.append(note)
    delta, note = _importance_modifier(finding, store)
    if delta:
        index += delta
        trace.append(note)

    index = max(0, min(index, len(SEVERITY_ORDER) - 1))
    final_severity = SEVERITY_ORDER[index]

    # The allowlist is a ceiling AND a floor (severity-matrix.md): a
    # total-invisibility check's severity can never be capped up past
    # critical by another check borrowing it, but it also can never be
    # knocked down from critical by a modifier -- e.g. a low-confidence
    # robots.txt-disallow is still a critical-severity finding; confidence
    # alone decides whether it is later demoted out of findings[], not a
    # quietly deflated severity label.
    affected = finding.get('affected') or {}
    total = affected.get('total_in_scope')
    broad = isinstance(total, (int, float)) and total >= 3 and affected.get('count', 0) == total
    whole_site = finding.get('whole_site_invisibility') is True
    eligible = finding['check_id'] in CRITICAL_ALLOWLIST and (broad or whole_site) and finding['confidence'] == 'high'
    if final_severity == 'critical' and not eligible:
        final_severity = "high"
        trace.append("critical-cap: requires confirmed broad or whole-site invisibility and high confidence")

    scored = dict(finding)
    scored["severity"] = final_severity
    scored["suggested_action"] = dict(finding["suggested_action"])
    scored["suggested_action"]["priority"] = final_severity
    scored["scoring_trace"] = {
        "original_severity": original_severity,
        "original_confidence": original_confidence,
        "final_severity": final_severity,
        "final_confidence": finding["confidence"],
        "modifiers_applied": trace,
    }
    return scored


# ---------------------------------------------------------------------------
# Demotion
# ---------------------------------------------------------------------------


def demote_low_confidence(findings: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """confidence-model.md: the confidence floor is the `low` tier itself.
    Severity is already scored and preserved in scoring_trace before this
    runs, so a demoted finding still carries useful context."""
    kept, demoted = [], []
    for finding in findings:
        if finding["confidence"] == "low":
            demoted.append(finding)
        else:
            kept.append(finding)
    return kept, demoted


# ---------------------------------------------------------------------------
# Distribution guard
# ---------------------------------------------------------------------------


def apply_distribution_guard(
    findings: List[Dict[str, Any]], threshold: float = DISTRIBUTION_GUARD_THRESHOLD
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Report an unusual severity distribution without rewriting evidence.

    Adding unrelated findings must never change an existing finding's
    severity.  The ratio remains useful diagnostic telemetry, so retain it as
    a calibration warning rather than a quota.
    """
    calibration_log: List[Dict[str, Any]] = []
    if len(findings) < DISTRIBUTION_GUARD_MIN_FINDINGS:
        return findings, calibration_log

    def high_critical_ratio(items: List[Dict[str, Any]]) -> float:
        return sum(1 for f in items if f["severity"] in ("high", "critical")) / len(items)

    if high_critical_ratio(findings) <= threshold:
        return findings, calibration_log

    calibration_log.append(
        {
            "type": "severity_distribution_warning",
            "high_critical_ratio": high_critical_ratio(findings),
            "threshold": threshold,
            "finding_count": len(findings),
        }
    )

    return findings, calibration_log


# ---------------------------------------------------------------------------
# Cross-skill relationship marking (never merges -- see dedupe-rules.md)
# ---------------------------------------------------------------------------


def link_related_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for finding in findings:
        finding.setdefault("related_findings", [])

    for i in range(len(findings)):
        for j in range(i + 1, len(findings)):
            a, b = findings[i], findings[j]
            if a["check_id"] == b["check_id"]:
                continue  # same-check overlap is the merge case, not a cross-reference
            if finding_url_set(a) & finding_url_set(b):
                a["related_findings"].append(b["id"])
                b["related_findings"].append(a["id"])

    return findings


# ---------------------------------------------------------------------------
# Ranking and id assignment
# ---------------------------------------------------------------------------


def rank_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(finding: Dict[str, Any]):
        return (
            -severity_index(finding["severity"]),
            -confidence_index(finding["confidence"]),
            0 if finding["check_id"] in URGENT_CHECK_IDS else 1,
            -(finding.get("affected") or {}).get("count", 1),
            finding["check_id"],
        )

    return sorted(findings, key=sort_key)


def assign_ids(findings: List[Dict[str, Any]], prefix: str = "F", width: int = 3) -> List[Dict[str, Any]]:
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"{prefix}-{index:0{width}d}"
    return findings


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------


def prioritize_findings(pooled_findings: List[Any], store: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The full evidence-prioritization pipeline: normalize -> reject ->
    deduplicate -> score -> demote -> distribution-guard -> rank -> assign ids
    -> cross-link. `store` is accepted for forward compatibility (e.g. a real
    link-centrality signal in place of the depth heuristic) but is not
    required -- every factor here is self-contained on the findings
    themselves, which is what keeps this skill's output reproducible from the
    findings alone."""
    normalized, rejected = normalize_findings(pooled_findings)
    deduped, merge_log = merge_duplicate_findings(normalized)
    scored = [score_finding(f, store) for f in deduped]
    kept, demoted = demote_low_confidence(scored)
    kept, calibration_log = apply_distribution_guard(kept)
    ranked = rank_findings(kept)
    ranked = assign_ids(ranked, prefix="F")
    ranked = link_related_findings(ranked)
    demoted = assign_ids(demoted, prefix="D")

    return {
        "findings": ranked,
        "demoted": demoted,
        "rejected": rejected,
        "merge_log": merge_log,
        "calibration_log": calibration_log,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the full evidence-prioritization pipeline over pooled findings.")
    parser.add_argument("--findings", required=True, help="Path to a JSON file containing a list of pooled findings from all detector skills.")
    parser.add_argument("--store", help="Optional observation-store JSON for scope and importance metadata.")
    parser.add_argument("--out", help="Path to write the result JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.findings, "r", encoding="utf-8") as handle:
        findings = json.load(handle)

    store = None
    if args.store:
        with open(args.store, "r", encoding="utf-8") as handle:
            store = json.load(handle)
    result = prioritize_findings(findings, store)
    output = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
