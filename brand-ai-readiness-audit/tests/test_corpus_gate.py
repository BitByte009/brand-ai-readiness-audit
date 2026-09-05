"""The corpus must fail CI for measured failures, independently of fixture names."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "harness"))
from run_corpus import fixture_failed


@pytest.mark.parametrize("key", [
    "false_positives", "false_negatives", "guardrail_violations",
    "missing_expected_coverage", "skill_failures",
])
def test_corpus_gate_rejects_regressions(key):
    assert fixture_failed({"schema_valid": True, key: ["unexpected"]})


@pytest.mark.parametrize("key", ["evidence_quality", "recommendation_quality", "severity_quality"])
def test_corpus_gate_rejects_quality_failures(key):
    assert fixture_failed({"schema_valid": True, key: {"failing": [{"ok": False}]}})


def test_corpus_gate_requires_valid_schema_but_accepts_clean_results():
    assert fixture_failed({"schema_valid": False})
    assert not fixture_failed({"schema_valid": True})
