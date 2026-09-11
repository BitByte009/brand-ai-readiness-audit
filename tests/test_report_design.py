"""Executable valid/invalid report examples; no network or model required."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/audit-orchestrator/scripts"))
import render_report
import run_audit
from lib.common.schema import load_schema, validate_report
from jsonschema import Draft202012Validator


def example(enriched=False):
    finding = {"id": "F-001", "title": "Public content is blocked", "severity": "high",
               "evidence": "Unauthenticated GET returned HTTP 403.",
               "suggested_action": {"summary": "Restore anonymous access to public content.", "priority": "high"}}
    if enriched:
        finding.update(category="crawl", confidence="high", mechanism="Origin access control denies anonymous requests.",
                       impact="Crawlers cannot read the affected public content.",
                       source_urls=["https://example.org/public"], observation_ids=["OBS-001"],
                       affected={"count": 1, "total_in_scope": None, "sample_urls": ["https://example.org/public"]})
        finding["suggested_action"].update(how_to_fix="Remove authentication from the public route; keep private routes protected.",
                                            validation="Repeat an anonymous GET and confirm HTTP 200 with the expected content.")
    return {"site": "example.org", "audited_at": "2026-09-05T12:00:00Z",
            "summary": {"total_findings": 1, "critical": 0, "high": 1, "medium": 0, "low": 0}, "findings": [finding]}


@pytest.mark.parametrize("enriched", [False, True])
def test_valid_examples_round_trip(enriched):
    Draft202012Validator.check_schema(load_schema("report.schema.json"))
    report = example(enriched)
    assert validate_report(json.loads(json.dumps(report))) == (True, [])


@pytest.mark.parametrize("field", ["site", "audited_at", "summary", "findings"])
def test_missing_required_report_field(field):
    report = example()
    del report[field]
    assert not validate_report(report)[0]


@pytest.mark.parametrize("field", ["id", "title", "severity", "evidence", "suggested_action"])
def test_missing_required_finding_field(field):
    report = example()
    del report["findings"][0][field]
    assert not validate_report(report)[0]


@pytest.mark.parametrize("path,value", [
    (("site",), "  "), (("audited_at",), "yesterday"),
    (("audited_at",), "2026-09-05T12:00:00"),
    (("summary", "total_findings"), 9), (("summary", "high"), 0),
    (("findings", 0, "title"), " "), (("findings", 0, "evidence"), ""),
    (("findings", 0, "severity"), "urgent"), (("findings", 0, "confidence"), 0.9),
    (("findings", 0, "mechanism"), []), (("findings", 0, "impact"), {}),
    (("findings", 0, "suggested_action", "summary"), ""),
    (("findings", 0, "suggested_action", "priority"), "low"),
    (("findings", 0, "suggested_action", "how_to_fix"), []),
    (("findings", 0, "suggested_action", "validation"), False),
    (("findings", 0, "source_urls"), ["javascript:alert(1)"]),
    (("findings", 0, "observation_ids"), ["OBS-1", "OBS-1"]),
    (("findings", 0, "affected", "count"), -1),
    (("findings", 0, "affected", "count"), 0),
    (("findings", 0, "affected", "total_in_scope"), 0),
    (("findings", 0, "related_findings"), ["F-002"]),
    (("findings", 0, "related_findings"), ["F-001"]),
])
def test_invalid_examples(path, value):
    report = example(True)
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not validate_report(report)[0]


def test_duplicate_ids_rejected():
    report = example()
    report["findings"].append(copy.deepcopy(report["findings"][0]))
    report["summary"].update(total_findings=2, high=2)
    assert any("duplicate" in error for error in validate_report(report)[1])


def test_duplicate_content_with_different_ids_rejected():
    report = example()
    other = copy.deepcopy(report["findings"][0])
    other["id"] = "F-002"
    report["findings"].append(other)
    report["summary"].update(total_findings=2, high=2)
    assert any("duplicate finding content" in error for error in validate_report(report)[1])


def test_nonfinite_extension_is_not_machine_readable_json():
    report = example()
    report["run"] = {"duration": float("nan")}
    assert not validate_report(report)[0]


def test_empty_degraded_report_and_robot_pattern_scope_remain_valid():
    report = example(True)
    report["findings"][0]["affected"]["sample_urls"] = ["/public/*"]
    assert validate_report(report)[0]
    report["findings"] = []
    report["summary"].update(total_findings=0, high=0)
    report["coverage"] = [{"reason": "RENDER_UNAVAILABLE", "status": "partial"}]
    assert validate_report(report)[0]


def test_render_cli_validates_before_writing(tmp_path):
    source, output = tmp_path / "report.json", tmp_path / "report.md"
    source.write_text(json.dumps({"site": "example.org"}))
    with pytest.raises(SystemExit) as exc:
        render_report.main(["--report", str(source), "--out", str(output)])
    assert exc.value.code == 2
    assert not output.exists()


def test_markdown_exposes_mechanism_sources_and_unknown_scope():
    report = example(True)
    markdown = render_report.render_markdown(report)
    for value in ["Why this happens:", "Origin access control", "Why it matters:", "https://example.org/public",
                  "OBS-001", "total scope not measured", "How to fix:", "Validation:"]:
        assert value in markdown
    assert "Every check ran" not in markdown
    assert "None in-scope" not in markdown
    assert report == example(True)  # presentation must not mutate evidence


def test_markdown_keeps_priority_order_and_surfaces_limitations():
    report = example()
    low = copy.deepcopy(report["findings"][0])
    low.update(id="F-002", severity="low", title="Lower priority issue")
    report["findings"].insert(0, low)
    report["coverage"] = [{"reason": "RENDER_UNAVAILABLE", "status": "partial", "detail": "Browser missing", "scope": "render checks"}]
    markdown = render_report.render_markdown(report)
    assert markdown.index("F-001") < markdown.index("F-002")
    assert markdown.index("coverage limitations") < markdown.index("## Findings")


def test_untrusted_text_cannot_inject_html_or_markdown():
    report = example(True)
    report["findings"][0]["evidence"] = '<script>alert(1)</script>\n# Forged heading [click](javascript:alert(1))'
    markdown = render_report.render_markdown(report)
    assert "<script>" not in markdown
    assert "\n# Forged" not in markdown
    assert "[click](" not in markdown


def test_cli_refuses_invalid_report_without_writing(tmp_path, monkeypatch):
    report = example()
    report["summary"]["high"] = 7
    monkeypatch.setattr(run_audit, "run_with_deadline", lambda *args: report)
    with pytest.raises(SystemExit) as exc:
        run_audit.main(["example.org", "--out-dir", str(tmp_path)])
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


def test_evidence_drop_removes_dangling_related_references(monkeypatch):
    from test_audit_orchestrator import make_fetch, robots_missing, FIXED_NOW, NO_SLEEP
    kept = example(True)["findings"][0]
    kept.update(observation_ids=[], source_urls=["https://example.org/"], related_findings=["F-002"])
    dropped = copy.deepcopy(kept)
    dropped.update(id="F-002", observation_ids=["OBS-fabricated"], related_findings=["F-001"])
    monkeypatch.setattr(run_audit, "_prioritize", lambda *args: {
        "findings": [kept, dropped], "demoted": [], "merge_log": [], "calibration_log": [], "rejected_findings": []})
    report = run_audit.run_audit("https://example.org/", fetch=make_fetch({"https://example.org/": "<h1>Public page</h1>"}),
                                 robots_fetcher=robots_missing, render_capability={"available": False, "reason": "test"},
                                 now=FIXED_NOW, sleep=NO_SLEEP)
    assert len(report["findings"]) == 1
    assert report["findings"][0]["related_findings"] == []
    assert validate_report(report) == (True, [])
