"""Entrypoint executable: lifecycle, capability detection, collection,
detector invocation, scoring, evidence binding, emission. Contains no check
logic and assigns no severity -- see SKILL.md's "Explicitly NOT this skill's
job".

Inputs:  url, options
Outputs: report.json, report.md
Nature:  deterministic orchestration

This is the ONLY entrypoint in the marketplace (marketplace.json marks it
"entrypoint": true; the other five skills are invoked only from here, never
directly). `run_audit()` composes them in a fixed order and never re-fetches:
one collection pass (lib/site_observer.collect), then the four detector
skills, then evidence-prioritization, then evidence-binding + schema
validation, then the proactive layer, then emission.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
for _path in (str(MARKETPLACE_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from lib.common.budget import Budget  # noqa: E402
from lib.common.network_policy import MAX_REQUESTS_PER_AUDIT  # noqa: E402
from lib.common.extract import with_parse_cache  # noqa: E402
from lib.common.schema import validate_report as validate_report_schema  # noqa: E402
from lib.site_observer.collect import collect  # noqa: E402

import proactive as proactive_mod  # noqa: E402
import validate_report as validate_report_mod  # noqa: E402

DETECTOR_SCRIPT_DIRS = ["crawl-render-audit", "entity-semantic-audit", "trust-freshness-audit", "engagement-audit"]
SEVERITY_TIERS = ["critical", "high", "medium", "low"]


def _register_detector_paths() -> None:
    for skill_dir in DETECTOR_SCRIPT_DIRS:
        path = str(MARKETPLACE_ROOT / "skills" / skill_dir / "scripts")
        if path not in sys.path:
            sys.path.insert(0, path)


def _run_detector(name: str, fn: Callable[..., List[Dict[str, Any]]], *args: Any, failures: List[Dict[str, Any]], coverage: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Never lets one detector's exception stop the others, or the audit,
    from completing -- graceful skill-failure handling. The failure is
    recorded twice: once for operators (`run.skill_failures`) and once as a
    coverage gap so the report itself explains the missing checks rather
    than silently having fewer findings than expected."""
    try:
        return fn(*args) or []
    except Exception as exc:  # noqa: BLE001 - a misbehaving detector must never take the audit down
        failures.append({"skill": name, "error": f"{type(exc).__name__}: {exc}"})
        coverage.append(
            {
                "check_id": "X-COV-01",
                "status": "failed",
                "reason": "SKILL_FAILED",
                "detail": f"{name} raised {type(exc).__name__}: {exc}",
                "scope": name,
            }
        )
        return []


def _invoke_detectors(store: Dict[str, Any]) -> Dict[str, Any]:
    _register_detector_paths()

    pooled: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []

    entity_profile: Optional[Dict[str, Any]] = None
    try:
        import build_entity_profile

        entity_profile = build_entity_profile.build_entity_profile(store)
    except Exception as exc:  # noqa: BLE001
        failures.append({"skill": "entity-semantic-audit", "stage": "build_entity_profile", "error": f"{type(exc).__name__}: {exc}"})
        coverage.append(
            {
                "check_id": "X-COV-01",
                "status": "failed",
                "reason": "SKILL_FAILED",
                "detail": f"build_entity_profile raised {type(exc).__name__}: {exc}",
                "scope": "entity-semantic-audit, engagement-audit (shared entity profile)",
            }
        )

    import detect_crawl
    import detect_engagement
    import detect_entity
    import detect_extract
    import detect_render
    import detect_trust

    pooled.extend(_run_detector("crawl-render-audit", detect_crawl.detect_crawl, store, failures=failures, coverage=coverage))
    pooled.extend(_run_detector("crawl-render-audit", detect_render.detect_render, store, failures=failures, coverage=coverage))
    pooled.extend(_run_detector("crawl-render-audit", detect_extract.detect_extract, store, failures=failures, coverage=coverage))
    pooled.extend(_run_detector("entity-semantic-audit", detect_entity.detect_entity, store, entity_profile, failures=failures, coverage=coverage))
    pooled.extend(_run_detector("trust-freshness-audit", detect_trust.detect_trust, store, failures=failures, coverage=coverage))
    pooled.extend(_run_detector("engagement-audit", detect_engagement.detect_engagement, store, entity_profile, failures=failures, coverage=coverage))

    return {"pooled_findings": pooled, "skill_failures": failures, "coverage": coverage}


def _prioritize(pooled_findings: List[Dict[str, Any]], store: Dict[str, Any], failures: List[Dict[str, Any]], coverage: List[Dict[str, Any]]) -> Dict[str, Any]:
    path = str(MARKETPLACE_ROOT / "skills" / "evidence-prioritization" / "scripts")
    if path not in sys.path:
        sys.path.insert(0, path)
    import score as score_mod

    try:
        return score_mod.prioritize_findings(pooled_findings, store)
    except Exception as exc:  # noqa: BLE001
        failures.append({"skill": "evidence-prioritization", "error": f"{type(exc).__name__}: {exc}"})
        coverage.append(
            {
                "check_id": "X-COV-01",
                "status": "failed",
                "reason": "SKILL_FAILED",
                "detail": f"evidence-prioritization raised {type(exc).__name__}: {exc}",
                "scope": "all findings for this audit",
            }
        )
        return {"findings": [], "demoted": [], "rejected": pooled_findings, "merge_log": [], "calibration_log": []}


def _summarize(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {tier: 0 for tier in SEVERITY_TIERS}
    for finding in findings:
        severity = finding.get("severity")
        if severity in counts:
            counts[severity] += 1
    return {"total_findings": len(findings), **counts}


@with_parse_cache
def run_audit(
    url: str,
    options: Optional[Dict[str, Any]] = None,
    *,
    fetch: Optional[Callable[[str], Dict[str, Any]]] = None,
    robots_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
    render_capability: Optional[Dict[str, Any]] = None,
    now: Optional[Callable[[], datetime.datetime]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> Dict[str, Any]:
    """Run one full audit end to end and return a schema-shaped report dict.

    Never raises: every stage from collection onward is wrapped so a single
    failure degrades to a coverage gap rather than taking the whole audit
    down (references/degraded-mode.md: a crash scores zero on every rubric
    line simultaneously). `fetch`/`robots_fetcher`/`render_capability`/`now`
    are injectable seams for tests; a real invocation leaves them unset and
    gets the real network client.
    """
    options = options or {}
    now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
    budget = Budget(options.get("budget"))

    collected = collect(
        url,
        budget=budget,
        fetch=fetch,
        robots_fetcher=robots_fetcher,
        render_capability=render_capability,
        now=now,
        sleep=sleep,
    )
    store = collected["store"]
    coverage: List[Dict[str, Any]] = list(collected["coverage"])
    skill_failures: List[Dict[str, Any]] = []

    detector_result = _invoke_detectors(store)
    skill_failures.extend(detector_result["skill_failures"])
    coverage.extend(detector_result["coverage"])

    prioritized = _prioritize(detector_result["pooled_findings"], store, skill_failures, coverage)

    kept_findings, dropped = validate_report_mod.bind_evidence(prioritized["findings"], store)
    kept_ids = {finding["id"] for finding in kept_findings}
    for finding in kept_findings:
        if "related_findings" in finding:
            finding["related_findings"] = [ref for ref in finding["related_findings"] if ref in kept_ids and ref != finding["id"]]
    if dropped:
        coverage.append(
            {
                "check_id": "X-COV-01",
                "status": "partial",
                "reason": "EVIDENCE_UNRESOLVED",
                "detail": f"{len(dropped)} finding(s) dropped: evidence did not resolve against the store",
                "scope": "the specific dropped findings, logged in run.evidence_binding_drops",
            }
        )

    proactive_opportunities = proactive_mod.generate_proactive_opportunities(store, prioritized["demoted"], kept_findings)

    report: Dict[str, Any] = {
        "site": store["target"]["audited_host"],
        "audited_at": store["collected_at"],
        "summary": _summarize(kept_findings),
        "findings": kept_findings,
        "scope": collected["scope"],
        "coverage": coverage,
        "proactive_opportunities": proactive_opportunities,
        "demoted": prioritized["demoted"],
        "run": {
            "capabilities": store["capabilities"],
            "budget": collected["budget"],
            "skill_failures": skill_failures,
            "evidence_binding_drops": dropped,
            "merge_log": prioritized.get("merge_log", []),
            "calibration_log": prioritized.get("calibration_log", []),
            "rejected_findings": prioritized.get("rejected", []),
        },
    }

    is_valid, errors = validate_report_schema(report)
    report["run"]["schema_valid"] = is_valid
    if not is_valid:
        # references/degraded-mode.md: always emit *something* schema-shaped.
        # This should be unreachable given the construction above; if it ever
        # isn't, the errors are recorded rather than raised so the run still
        # completes, and the malformed parts are visible for debugging.
        report["run"]["schema_errors"] = errors

    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a website for AI-discoverability and on-site-engagement failures.")
    parser.add_argument("url", help="The URL or domain to audit.")
    parser.add_argument("--out-dir", default=".", help="Directory to write report.json and report.md into.")
    parser.add_argument("--max-pages", type=int, help="Override the raw-crawl page budget.")
    args = parser.parse_args(argv)

    options: Dict[str, Any] = {}
    if args.max_pages is not None:
        # The per-origin request ceiling in network_policy already caps real
        # load, but an operator should not be able to ask for a crawl the
        # platform has no intention of performing, nor for a zero-page audit
        # that would look like a clean site rather than a skipped one.
        if not 1 <= args.max_pages <= MAX_REQUESTS_PER_AUDIT:
            parser.error(f"--max-pages must be between 1 and {MAX_REQUESTS_PER_AUDIT}")
        options["budget"] = {"raw_crawl_max_pages": args.max_pages}

    report = run_audit(args.url, options)
    valid, errors = validate_report_schema(report)
    if not valid:
        parser.exit(2, "Report validation failed; no report written: " + "; ".join(errors) + "\n")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    import render_report

    (out_dir / "report.md").write_text(render_report.render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
