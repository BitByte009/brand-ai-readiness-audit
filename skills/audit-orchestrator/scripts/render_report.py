"""Renders report.json to the human-readable report.md a non-expert can act on.

Inputs:  report.json (in memory or on disk)
Outputs: report.md
Nature:  deterministic

Pure string formatting over an already-validated report -- no interpretation,
no new facts, nothing that could disagree with report.json.
"""

from __future__ import annotations

import argparse
import json
import html
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

MARKETPLACE_ROOT = Path(__file__).resolve().parents[3]
if str(MARKETPLACE_ROOT) not in sys.path:
    sys.path.insert(0, str(MARKETPLACE_ROOT))
from lib.common.schema import validate_report

_SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def _text(value: Any) -> str:
    """Treat fetched text as text, never as executable HTML or Markdown."""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]",
                   lambda match: f"\\u{ord(match.group()):04x}", str(value))
    return re.sub(r"([\\`*_{\[\]}|~])", r"\\\1", html.escape(value)).replace("\n", " ").replace("\r", " ")


def _findings_section(findings: List[Dict[str, Any]]) -> List[str]:
    lines = ["## Findings"]
    if not findings:
        lines.append("\nNone.")
        return lines
    by_severity: Dict[str, List[Dict[str, Any]]] = {tier: [] for tier in _SEVERITY_ORDER}
    for finding in findings:
        by_severity.setdefault(finding.get("severity", "low"), []).append(finding)

    for tier in _SEVERITY_ORDER:
        items = by_severity.get(tier, [])
        if not items:
            continue
        lines.append(f"\n### {tier.capitalize()} ({len(items)})")
        for finding in items:
            lines.append(f"\n**{_text(finding.get('id', ''))} — {_text(finding.get('title', ''))}**")
            lines.append("")
            lines.append(f"- Confidence: {_text(finding.get('confidence', 'unknown'))}")
            for label, key in [("Category", "category"), ("Why this happens", "mechanism"), ("Why it matters", "impact")]:
                if finding.get(key):
                    lines.append(f"- {label}: {_text(finding[key])}")
            affected = finding.get("affected", {}) or {}
            count, total = affected.get('count'), affected.get('total_in_scope')
            scope = f"{count} of {total} in-scope items" if total is not None and count is not None else f"{count if count is not None else 'Unknown number of'} observed affected items; total scope not measured"
            lines.append(f"- Affected scope: {scope}")
            lines.append(f"- Evidence: {_text(finding.get('evidence', ''))}")
            for label, key in [("Sources", "source_urls"), ("Observation references", "observation_ids"), ("Related findings", "related_findings")]:
                if finding.get(key):
                    lines.append(f"- {label}: " + "; ".join(_text(value) for value in finding[key]))
            action = finding.get("suggested_action", {}) or {}
            if action.get("summary"):
                lines.append(f"- Suggested action: {_text(action['summary'])}")
            for label, key in [("How to fix", "how_to_fix"), ("Validation", "validation")]:
                if action.get(key):
                    lines.append(f"- {label}: {_text(action[key])}")
    return lines


def _coverage_section(coverage: List[Dict[str, Any]]) -> List[str]:
    lines = ["\n## Coverage"]
    if not coverage:
        lines.append("\nNo coverage limitations were recorded. This is not proof that every possible check ran or that the site has no issues.")
        return lines
    for entry in coverage:
        lines.append(f"\n- {_text(entry.get('reason', ''))} ({_text(entry.get('status', ''))}): {_text(entry.get('detail', ''))} — affects {_text(entry.get('scope', ''))}")
    return lines


def _proactive_section(opportunities: List[Dict[str, Any]]) -> List[str]:
    lines = ["\n## Proactive opportunities"]
    if not opportunities:
        lines.append("\nNone identified.")
        return lines
    for item in opportunities:
        lines.append(f"\n- **{_text(item.get('title', ''))}**: {_text(item.get('opportunity', ''))}")
        for label, key in [("Why this helps", "expected_mechanism"), ("Expected benefit", "expected_effect")]:
            if item.get(key):
                lines.append(f"  - {label}: {_text(item[key])}")
        if item.get("source_urls"):
            lines.append("  - Sources: " + "; ".join(_text(url) for url in item["source_urls"]))
    return lines


def render_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary", {}) or {}
    lines = [
        f"# Audit report — {_text(report.get('site', 'unknown site'))}",
        f"\nAudited at: {_text(report.get('audited_at', ''))}",
        f"\n## Summary\n\nTotal findings: {summary.get('total_findings', 0)} "
        f"(critical: {summary.get('critical', 0)}, high: {summary.get('high', 0)}, "
        f"medium: {summary.get('medium', 0)}, low: {summary.get('low', 0)})",
        "",
        "Findings are ordered by severity, then the audit's ranking within each tier. Severity describes impact; confidence describes strength of evidence, not a probability. Scope refers to observed items, not the entire website.",
        "",
    ]
    if report.get("coverage"):
        lines.extend(["This audit has coverage limitations: see Coverage before treating missing findings as a pass.", ""])
    scope = report.get("scope", {})
    if scope:
        lines.extend([f"Observed scope: {scope.get('pages_crawled', 0)} pages crawled; "
                      f"{scope.get('pages_rendered', 0)} render attempts; "
                      f"site type: {_text(scope.get('archetype') or 'undetermined')}.", ""])
    failed = bool(report.get("run", {}).get("skill_failures")) or any(
        c.get("reason") == "AUDIT_FAILED" for c in report.get("coverage", []))
    if failed or (scope and scope.get("pages_crawled") == 0):
        lines.extend(["**Audit incomplete. Missing findings must not be interpreted as a clean bill of health.**", ""])
    findings = sorted(report.get("findings", []), key=lambda f: _SEVERITY_ORDER.index(f["severity"]))
    if findings:
        lines.extend(["## First actions", "", "Start with these ranked recommendations; details and verification steps follow.", ""])
        for index, finding in enumerate(findings[:3], 1):
            action = finding.get("suggested_action", {})
            lines.append(f"{index}. **{_text(finding.get('id', ''))} ({_text(action.get('priority', finding['severity']))})** — {_text(action.get('summary', ''))}")
        lines.append("")
    lines.extend(_findings_section(report.get("findings", [])))
    lines.extend(_coverage_section(report.get("coverage", [])))
    lines.extend(_proactive_section(report.get("proactive_opportunities", [])))
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render report.json to report.md.")
    parser.add_argument("--report", required=True, help="Path to report.json.")
    parser.add_argument("--out", help="Path to write report.md. Defaults to stdout.")
    args = parser.parse_args(argv)

    with open(args.report, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    valid, errors = validate_report(report)
    if not valid:
        parser.exit(2, "Report validation failed: " + "; ".join(errors) + "\n")

    markdown = render_markdown(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
