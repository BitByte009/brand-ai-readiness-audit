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
import importlib
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
MARKETPLACE_ROOT = SCRIPTS_DIR.parents[2]
for _path in (str(MARKETPLACE_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from lib.common.budget import Budget  # noqa: E402
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

    for module_name, skill, args in [
        ("detect_crawl", "crawl-render-audit", (store,)),
        ("detect_render", "crawl-render-audit", (store,)),
        ("detect_extract", "crawl-render-audit", (store,)),
        ("detect_entity", "entity-semantic-audit", (store, entity_profile)),
        ("detect_trust", "trust-freshness-audit", (store,)),
        ("detect_engagement", "engagement-audit", (store, entity_profile)),
    ]:
        def invoke():
            return getattr(importlib.import_module(module_name), module_name)(*args)
        pooled.extend(_run_detector(skill, invoke, failures=failures, coverage=coverage))
    opportunities = _run_detector("crawl-render-audit/proactive", lambda: importlib.import_module("detect_extract").proactive_opportunities(store), failures=failures, coverage=coverage)
    return {"pooled_findings": pooled, "skill_failures": failures, "coverage": coverage, "proactive_opportunities": opportunities}


def _prioritize(pooled_findings: List[Dict[str, Any]], store: Dict[str, Any], failures: List[Dict[str, Any]], coverage: List[Dict[str, Any]]) -> Dict[str, Any]:
    path = str(MARKETPLACE_ROOT / "skills" / "evidence-prioritization" / "scripts")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import score as score_mod
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
def _run_audit(
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

    proactive_opportunities = _run_detector("audit-orchestrator/proactive", proactive_mod.generate_proactive_opportunities,
                                           store, prioritized["demoted"], failures=skill_failures, coverage=coverage)
    proactive_opportunities.extend(detector_result.get("proactive_opportunities", []))

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
    if options.get("include_evidence"):
        report["evidence_store"] = store

    is_valid, errors = validate_report_schema(report)
    report["run"]["schema_valid"] = is_valid
    if not is_valid:
        # references/degraded-mode.md: always emit *something* schema-shaped.
        # This should be unreachable given the construction above; if it ever
        # isn't, the errors are recorded rather than raised so the run still
        # completes, and the malformed parts are visible for debugging.
        report["run"]["schema_errors"] = errors

    return report


def _failure_report(url: str, reason: str, detail: str) -> Dict[str, Any]:
    return {"site": str(url) or "unknown", "audited_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "summary": _summarize([]), "findings": [], "scope": {}, "proactive_opportunities": [],
            "coverage": [{"check_id": "X-COV-01", "status": "failed", "reason": reason, "detail": detail,
                          "scope": "audit incomplete; no conclusion about site quality"}],
            "run": {"schema_valid": True, "skill_failures": [{"skill": "audit-lifecycle", "error": detail}]}}


def run_audit(url: str, options=None, **kwargs) -> Dict[str, Any]:
    """Library API: unexpected lifecycle failures become explicit coverage gaps."""
    import time
    started = time.monotonic()
    try:
        report = _run_audit(url, options, **kwargs)
    except Exception as exc:
        report = _failure_report(url, "AUDIT_FAILED", f"{type(exc).__name__}: {exc}")
    report["run"]["elapsed_s"] = round(time.monotonic() - started, 3)
    return report


def _worker(connection, url, options):
    import os
    if os.name == "posix":
        os.setsid()  # descendants can be reclaimed when the process deadline expires
    try:
        connection.send(run_audit(url, options))
    finally:
        connection.close()


def run_with_deadline(url, options, timeout_s=280):
    """A separate process bounds DNS, browser startup and detector CPU time."""
    import multiprocessing
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, url, options))
    process.start()
    sender.close()
    try:
        if receiver.poll(timeout_s):
            try:
                return receiver.recv()
            except EOFError:
                return _failure_report(url, "AUDIT_FAILED", "Audit worker exited without a report.")
        return _failure_report(url, "BUDGET_EXHAUSTED", f"Audit exceeded {timeout_s}s process deadline.")
    finally:
        import os
        import signal
        if os.name == "posix":
            try:
                if os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        receiver.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a website for AI-discoverability and on-site-engagement failures.")
    parser.add_argument("url", help="The URL or domain to audit.")
    parser.add_argument("--out-dir", default=".", help="Directory to write report.json and report.md into.")
    parser.add_argument("--max-pages", type=int, help="Override the raw-crawl page budget.")
    parser.add_argument("--save-evidence", action="store_true", help="Also write observations.json for evidence replay.")
    args = parser.parse_args(argv)

    options: Dict[str, Any] = {}
    if args.max_pages is not None:
        if args.max_pages < 1:
            parser.error("--max-pages must be positive")
        options["budget"] = {"raw_crawl_max_pages": args.max_pages}
    options["include_evidence"] = args.save_evidence

    report = run_with_deadline(args.url, options)
    evidence_store = report.pop("evidence_store", None)
    valid, errors = validate_report_schema(report)
    if not valid:
        parser.exit(2, "Report validation failed; no report written: " + "; ".join(errors) + "\n")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if evidence_store is not None:
        (out_dir / "observations.json").write_text(json.dumps(evidence_store, indent=2), encoding="utf-8")

    import render_report

    (out_dir / "report.md").write_text(render_report.render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
