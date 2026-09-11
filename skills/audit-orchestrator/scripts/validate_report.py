"""Schema enforcement plus evidence-binding validation: drops any finding
whose observation IDs do not resolve against the store.

Inputs:  findings, store
Outputs: (kept findings, drop log)
Nature:  deterministic

PROJECT_CONTEXT.md D-3 / PHASE1B Defect B: evidence-binding validation is
mechanical schema enforcement, not scoring -- it belongs here, in the
orchestrator, never in evidence-prioritization (which never touches the
observation store at all; see its own evidence-validation.md). "A finding
survives only if every observation ID it cites resolves in the store" is
enforced by this function, not by asking a skill to behave.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
if str(MARKETPLACE_ROOT) not in sys.path:
    sys.path.insert(0, str(MARKETPLACE_ROOT))

from lib.common.schema import validate_report as validate_report_schema  # noqa: E402


def bind_evidence(findings: List[Dict[str, Any]], store: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """A finding is dropped -- not demoted, not rescored, simply removed --
    if none of its evidence traces back to a real observation in the store.

    Two ways a finding legitimately binds evidence, both already used across
    the detector skills:
    1. `observation_ids` citing observations that resolve in the store (a
       positive signal: "this specific observation shows the defect").
    2. `source_urls` naming pages the store actually has an observation for,
       used with an empty `observation_ids` by every *absence* check across
       crawl-render-audit, entity-semantic-audit and trust-freshness-audit
       (there is no single observation ID that proves something is *missing*
       -- the evidence is "we fetched these pages and the signal was not
       there"). Requiring a positive observation_id for an absence finding
       would silently drop a large, deliberate class of legitimate findings;
       requiring *some* real, resolvable anchor (an ID or a fetched URL)
       still refuses a finding that points to nothing real at all.
    A finding with neither a resolvable observation_id nor a known
    source_url is dropped as unsupported."""
    known_ids = {obs.get("id") for obs in store.get("observations", []) if obs.get("id")}
    known_urls = {obs.get("source_url") for obs in store.get("observations", []) if obs.get("source_url")}
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []

    for finding in findings:
        cited_ids = finding.get("observation_ids") or []
        cited_urls = finding.get("source_urls") or []

        if cited_ids:
            unresolved = [oid for oid in cited_ids if oid not in known_ids]
            if unresolved:
                dropped.append(
                    {
                        "finding_id": finding.get("id"),
                        "check_id": finding.get("check_id"),
                        "reason": f"unresolved observation_ids: {sorted(unresolved)}",
                    }
                )
                continue
            kept.append(finding)
            continue

        # No observation_ids cited: fall back to source_urls resolving
        # against real, fetched pages (see docstring, case 2).
        if cited_urls and all(url in known_urls for url in cited_urls):
            # Materialize the page anchors so exported reports are replayable,
            # including absence findings. IDs refer to actual observed pages,
            # not fabricated positive evidence of absence.
            finding["observation_ids"] = sorted({obs["id"] for obs in store.get("observations", [])
                                                 if obs.get("source_url") in cited_urls and obs.get("id")})
            kept.append(finding)
            continue

        unresolved_urls = [url for url in cited_urls if url not in known_urls]
        reason = (
            f"unresolved source_urls: {sorted(unresolved_urls)}"
            if unresolved_urls
            else "no observation_ids or source_urls cited"
        )
        dropped.append({"finding_id": finding.get("id"), "check_id": finding.get("check_id"), "reason": reason})

    return kept, dropped


def validate_final_report(report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Schema-enforce the assembled report. Never raises -- a failure here
    is recorded, not thrown, so degraded mode can still emit *something*
    schema-shaped (see references/degraded-mode.md: a crash scores zero on
    every rubric line simultaneously)."""
    return validate_report_schema(report)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bind findings' evidence against a store and drop unresolvable ones.")
    parser.add_argument("--findings", required=True, help="Path to a JSON file containing a list of scored findings.")
    parser.add_argument("--store", required=True, help="Path to the observation store JSON file.")
    parser.add_argument("--out", help="Path to write {'findings':[...], 'dropped':[...]} JSON. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.findings, "r", encoding="utf-8") as handle:
        findings = json.load(handle)
    with open(args.store, "r", encoding="utf-8") as handle:
        store = json.load(handle)

    kept, dropped = bind_evidence(findings, store)
    output = json.dumps({"findings": kept, "dropped": dropped}, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
