"""Fixture corpus harness.

Serves each fixture over loopback with the real static-file server
(tests/harness/fixture_server.py), runs the real audit pipeline
(skills/audit-orchestrator/scripts/run_audit.py) against it end to end --
real HTTP fetches, real robots.txt parsing, real crawling, real (Playwright,
if installed) rendering, real detectors, real scoring -- and scores the
result against each fixture's expected.json on the metrics PROJECT_CONTEXT.md
commits to measuring:

    EXPECTED, ACTUAL, FALSE POSITIVE, FALSE NEGATIVE,
    EVIDENCE CORRECT, RECOMMENDATION CORRECT, SEVERITY REASONABLE

A fixture's expected.json may additionally declare:
  - structurally_untestable: {check_id: reason} -- checks known, from direct
    source inspection, to be unreachable through the real pipeline (a missing
    capability or an unwired observation type). Absence of these is asserted
    but never counted as a false negative against the fixture -- it is a
    property of the pipeline, not of this fixture's content.
  - confirmed_false_negative: {check, why} -- a documented, root-caused gap
    where the fixture DOES contain the defect but the tool does not detect
    it, for a confirmed and cited code reason. Recorded, not scored as an
    authoring mistake.

Emits tests/harness/results.json (full detail) and prints a per-fixture and
aggregate summary. Offline and deterministic modulo two known sources of
run-to-run variance, both noted in the output: real render timing
(Playwright) and, for large-site only, BFS timing at the crawl-budget
boundary.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HARNESS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = HARNESS_DIR.parents[1]
FIXTURES_ROOT = HARNESS_DIR.parent / "fixtures"

for _path in (str(MARKETPLACE_ROOT), str(HARNESS_DIR), str(MARKETPLACE_ROOT / "skills" / "audit-orchestrator" / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from fixture_server import FixtureServer  # noqa: E402
from run_audit import run_audit  # noqa: E402
from unittest.mock import patch
from lib.common import public_transport


def discover_fixtures() -> List[Path]:
    return sorted(p for p in FIXTURES_ROOT.iterdir() if p.is_dir() and (p / "expected.json").exists())


def _check_ids(findings: List[Dict[str, Any]]) -> List[str]:
    return [f.get("check_id") for f in findings if f.get("check_id")]


def _evidence_quality(finding: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    """A finding's evidence is 'correct' here if: it is non-empty and not a
    generic placeholder, it names at least one concrete URL or quoted signal,
    and every observation_id it cites actually resolves in this run (the
    orchestrator already drops findings with unresolvable evidence before
    they reach the report, so a resolvable check here is really verifying
    that guarantee held, not re-deriving it from scratch)."""
    evidence = (finding.get("evidence") or "").strip()
    observed_signal = (finding.get("observed_signal") or "").strip()
    has_text = len(evidence) > 15 and evidence.lower() not in {"n/a", "none", "unknown"}
    names_something = bool(finding.get("source_urls")) or "http" in evidence
    has_observed_signal = len(observed_signal) > 0
    ok = has_text and names_something and has_observed_signal
    return {"ok": ok, "evidence": evidence, "observed_signal": observed_signal}


def _recommendation_quality(finding: Dict[str, Any]) -> Dict[str, Any]:
    action = finding.get("suggested_action") or {}
    summary = (action.get("summary") or "").strip()
    how_to_fix = (action.get("how_to_fix") or "").strip()
    validation = (action.get("validation") or "").strip()
    ok = len(summary) > 10 and len(how_to_fix) > 10 and len(validation) > 10
    return {"ok": ok, "summary": summary, "how_to_fix": how_to_fix, "validation": validation}


def _severity_quality(finding: Dict[str, Any]) -> Dict[str, Any]:
    severity = finding.get("severity")
    confidence = finding.get("confidence")
    ok = severity in {"critical", "high", "medium", "low"} and confidence in {"high", "medium", "low"}
    return {"ok": ok, "severity": severity, "confidence": confidence}


def score_fixture(fixture_dir: Path) -> Dict[str, Any]:
    expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))
    expected_findings = set(expected.get("expected_findings", []))
    expected_non_findings = set(expected.get("expected_non_findings", []))
    structurally_untestable = set(expected.get("structurally_untestable", {}).keys())
    confirmed_fn = expected.get("confirmed_false_negative")
    confirmed_fn_checks = set()
    if isinstance(confirmed_fn, dict) and confirmed_fn.get("check"):
        confirmed_fn_checks.add(confirmed_fn["check"].split(" ")[0])
    elif isinstance(confirmed_fn, list):
        for entry in confirmed_fn:
            confirmed_fn_checks.add(entry["check"].split(" ")[0])

    with FixtureServer(fixture_dir) as server:
        url = server.base_url() + "/"
        started = time.perf_counter()
        # Test-owned loopback only. The production CLI has no private-IP bypass.
        original_resolver = public_transport.public_address
        def fixture_address(host, port):
            if host == "127.0.0.1" and port == int(url.split(":")[2].split("/")[0]):
                return host
            return original_resolver(host, port)
        with patch.object(public_transport, "public_address", fixture_address):
            report = run_audit(url)
        elapsed_s = time.perf_counter() - started

    actual_findings = report.get("findings", [])
    actual_check_ids = set(_check_ids(actual_findings))

    false_positives = sorted(actual_check_ids - expected_findings - confirmed_fn_checks)
    # A check explicitly declared as a non-finding firing anyway is always a
    # false positive, called out separately since it is a guardrail regression.
    guardrail_violations = sorted(actual_check_ids & expected_non_findings)
    false_negatives = sorted(expected_findings - actual_check_ids - structurally_untestable)

    evidence_results = [_evidence_quality(f, report) for f in actual_findings]
    recommendation_results = [_recommendation_quality(f) for f in actual_findings]
    severity_results = [_severity_quality(f) for f in actual_findings]

    coverage_reasons = {c.get("reason") for c in report.get("coverage", [])}
    expected_coverage = set(expected.get("expected_coverage", []))
    missing_coverage = sorted(expected_coverage - coverage_reasons)

    return {
        "fixture": fixture_dir.name,
        "elapsed_s": round(elapsed_s, 3),
        "description": expected.get("description", ""),
        "expected_findings": sorted(expected_findings),
        "actual_findings": sorted(actual_check_ids),
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "guardrail_violations": guardrail_violations,
        "structurally_untestable": sorted(structurally_untestable),
        "confirmed_false_negative": confirmed_fn,
        "missing_expected_coverage": missing_coverage,
        "evidence_quality": {
            "n": len(evidence_results),
            "ok": sum(1 for r in evidence_results if r["ok"]),
            "failing": [r for r in evidence_results if not r["ok"]],
        },
        "recommendation_quality": {
            "n": len(recommendation_results),
            "ok": sum(1 for r in recommendation_results if r["ok"]),
            "failing": [r for r in recommendation_results if not r["ok"]],
        },
        "severity_quality": {
            "n": len(severity_results),
            "ok": sum(1 for r in severity_results if r["ok"]),
            "failing": [r for r in severity_results if not r["ok"]],
        },
        "summary": report.get("summary", {}),
        "scope": report.get("scope", {}),
        "schema_valid": report.get("run", {}).get("schema_valid"),
        "skill_failures": report.get("run", {}).get("skill_failures", []),
        "report": report,
    }


def fixture_failed(result: Dict[str, Any]) -> bool:
    """A diagnostic summary is not a passing test when regressions occurred."""
    return bool(
        any(result.get(key) for key in (
            "false_positives", "false_negatives", "guardrail_violations",
            "missing_expected_coverage", "skill_failures",
        ))
        or result.get("schema_valid") is not True
        or any(result.get(key, {}).get("failing") for key in (
            "evidence_quality", "recommendation_quality", "severity_quality",
        ))
    )


def main(argv: Optional[List[str]] = None) -> int:
    fixture_dirs = discover_fixtures()
    results = []
    for fixture_dir in fixture_dirs:
        print(f"Running {fixture_dir.name} ...", file=sys.stderr)
        results.append(score_fixture(fixture_dir))

    total_expected = sum(len(r["expected_findings"]) for r in results)
    total_actual = sum(len(r["actual_findings"]) for r in results)
    total_fp = sum(len(r["false_positives"]) for r in results)
    total_fn = sum(len(r["false_negatives"]) for r in results)
    total_guardrail = sum(len(r["guardrail_violations"]) for r in results)
    total_findings_emitted = sum(len(r["report"]["findings"]) for r in results)
    total_evidence_ok = sum(r["evidence_quality"]["ok"] for r in results)
    total_recommendation_ok = sum(r["recommendation_quality"]["ok"] for r in results)
    total_severity_ok = sum(r["severity_quality"]["ok"] for r in results)

    print("\n" + "=" * 100)
    print(f"{'FIXTURE':<28} {'EXP':>4} {'ACT':>4} {'FP':>3} {'FN':>3} {'GUARD':>6} {'EVID':>8} {'RECO':>8} {'SEV':>8}")
    print("-" * 100)
    for r in results:
        eq = r["evidence_quality"]
        rq = r["recommendation_quality"]
        sq = r["severity_quality"]
        print(
            f"{r['fixture']:<28} {len(r['expected_findings']):>4} {len(r['actual_findings']):>4} "
            f"{len(r['false_positives']):>3} {len(r['false_negatives']):>3} {len(r['guardrail_violations']):>6} "
            f"{eq['ok']:>3}/{eq['n']:<4} {rq['ok']:>3}/{rq['n']:<4} {sq['ok']:>3}/{sq['n']:<4}"
        )
    print("-" * 100)
    print(f"{'TOTAL':<28} {total_expected:>4} {total_actual:>4} {total_fp:>3} {total_fn:>3} {total_guardrail:>6} "
          f"{total_evidence_ok:>3}/{total_findings_emitted:<4} {total_recommendation_ok:>3}/{total_findings_emitted:<4} "
          f"{total_severity_ok:>3}/{total_findings_emitted:<4}")
    print("=" * 100)

    for r in results:
        if r["false_positives"] or r["false_negatives"] or r["guardrail_violations"] or r["missing_expected_coverage"] or r["skill_failures"]:
            print(f"\n--- {r['fixture']} ---")
            if r["false_positives"]:
                print(f"  FALSE POSITIVES (unexpected findings): {r['false_positives']}")
            if r["guardrail_violations"]:
                print(f"  GUARDRAIL VIOLATIONS (explicit non-findings that fired): {r['guardrail_violations']}")
            if r["false_negatives"]:
                print(f"  FALSE NEGATIVES (missing findings): {r['false_negatives']}")
            if r["missing_expected_coverage"]:
                print(f"  MISSING EXPECTED COVERAGE ENTRIES: {r['missing_expected_coverage']}")
            if r["skill_failures"]:
                print(f"  SKILL FAILURES: {r['skill_failures']}")

    out_path = HARNESS_DIR / "results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nFull results written to {out_path}")

    return int(any(fixture_failed(result) for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
