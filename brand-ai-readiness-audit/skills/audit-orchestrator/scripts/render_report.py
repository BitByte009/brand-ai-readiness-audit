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
from typing import Any, Dict, List, Optional

_SEVERITY_ORDER = ["critical", "high", "medium", "low"]


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
            lines.append(f"\n**{finding.get('id', '')} — {finding.get('title', '')}**")
            lines.append(f"- Evidence: {finding.get('evidence', '')}")
            action = finding.get("suggested_action", {}) or {}
            if action.get("summary"):
                lines.append(f"- Suggested action: {action['summary']}")
    return lines


def _coverage_section(coverage: List[Dict[str, Any]]) -> List[str]:
    lines = ["\n## Coverage"]
    if not coverage:
        lines.append("\nEvery check ran to completion.")
        return lines
    for entry in coverage:
        lines.append(f"- `{entry.get('reason', '')}` ({entry.get('status', '')}): {entry.get('detail', '')} — affects {entry.get('scope', '')}")
    return lines


def _proactive_section(opportunities: List[Dict[str, Any]]) -> List[str]:
    lines = ["\n## Proactive opportunities"]
    if not opportunities:
        lines.append("\nNone identified.")
        return lines
    for item in opportunities:
        lines.append(f"- **{item.get('title', '')}**: {item.get('opportunity', '')}")
    return lines


def render_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary", {}) or {}
    lines = [
        f"# Audit report — {report.get('site', 'unknown site')}",
        f"\nAudited at: {report.get('audited_at', '')}",
        f"\n## Summary\nTotal findings: {summary.get('total_findings', 0)} "
        f"(critical: {summary.get('critical', 0)}, high: {summary.get('high', 0)}, "
        f"medium: {summary.get('medium', 0)}, low: {summary.get('low', 0)})",
        "",
    ]
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

    markdown = render_markdown(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
