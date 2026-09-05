"""Tests for the evidence-prioritization skill.

Two kinds:
- Unit tests: one stage at a time (validation/rejection, dedup/merge, severity
  scoring + critical cap, demotion, distribution guard, cross-skill linking,
  ranking, id assignment).
- Integration tests: the full `prioritize_findings()` pipeline, including one
  that runs real `crawl-render-audit`/`entity-semantic-audit` detectors on a
  synthetic store and pools their actual output through this skill -- a
  genuine cross-skill composition test, not just hand-built fixtures.

Run from the marketplace root: `python -m pytest tests/test_evidence_prioritization.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "evidence-prioritization" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import aggregate_dedupe as ad  # noqa: E402
import normalize as nm  # noqa: E402
import score as sc  # noqa: E402

REPORT_SCHEMA = json.loads((ROOT / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
FINDING_SCHEMA = REPORT_SCHEMA["$defs"]["finding"]


# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------


def make_finding(
    check_id="D-CRAWL-04",
    category="discoverability",
    severity="medium",
    confidence="high",
    count=1,
    total=1,
    urls=None,
    title=None,
    observation_ids=None,
    extrapolated=False,
    mechanism="some mechanism",
    affected_urls=None,
):
    urls = urls if urls is not None else ["https://example.com/deep/page"]
    affected_urls = affected_urls if affected_urls is not None else urls
    return {
        "check_id": check_id,
        "category": category,
        "title": title or f"{check_id} finding",
        "severity": severity,
        "confidence": confidence,
        "mechanism": mechanism,
        "impact": "some impact",
        "observed_signal": "some signal",
        "evidence": "some evidence text",
        "observation_ids": observation_ids if observation_ids is not None else ["OBS-X-1"],
        "source_urls": urls,
        "affected": {
            "count": count,
            "sample_urls": affected_urls[:5],
            "total_in_scope": total,
            **({"extrapolated": True} if extrapolated else {}),
        },
        "suggested_action": {"summary": "fix it", "priority": severity, "how_to_fix": "do x", "validation": "check y"},
    }


def assert_finding_shape(finding):
    jsonschema.validate(finding, FINDING_SCHEMA)


def test_context_url_does_not_promote_affected_page_importance():
    target = "https://example.com/"
    finding = make_finding(urls=[target, target + "article"], affected_urls=[target + "article"])
    assert sc._importance_modifier(finding, {"target": {"requested_url": target}}) == (0, None)


def test_unknown_population_does_not_infer_sitewide_scope():
    from lib.common.findings import affected_block

    urls = ["https://example.com/a", "https://example.com/b"]
    assert affected_block(urls)["total_in_scope"] is None
    finding = make_finding(count=2, total=None, urls=urls)
    assert sc._scope_modifier(finding) == (0, None)
    assert sc.score_finding(finding)["severity"] == "medium"


def test_dedupe_is_permutation_invariant_for_equal_confidence():
    first = make_finding(title="First", urls=["https://example.com/a"])
    second = make_finding(title="Second", urls=["https://example.com/a", "https://example.com/b"])
    assert ad.merge_duplicate_findings([first, second])[0] == ad.merge_duplicate_findings([second, first])[0]


# ---------------------------------------------------------------------------
# Unit tests -- normalize.py (validation / rejection)
# ---------------------------------------------------------------------------


def test_normalize_accepts_well_formed_finding():
    findings = [make_finding()]
    normalized, rejected = nm.normalize_findings(findings)
    assert len(normalized) == 1
    assert rejected == []


def test_normalize_lowercases_severity_and_confidence_without_rejecting():
    finding = make_finding(severity="High", confidence="MEDIUM")
    normalized, rejected = nm.normalize_findings([finding])
    assert rejected == []
    assert normalized[0]["severity"] == "high"
    assert normalized[0]["confidence"] == "medium"


@pytest.mark.parametrize(
    "mutation,expected_reason_fragment",
    [
        (lambda f: f.pop("check_id"), "missing or empty required field 'check_id'"),
        (lambda f: f.__setitem__("title", "   "), "missing or empty required field 'title'"),
        (lambda f: f.__setitem__("observation_ids", "not-a-list"), "'observation_ids' must be a list"),
        (lambda f: f.__setitem__("severity", "urgent"), "invalid severity"),
        (lambda f: f.__setitem__("confidence", "certain"), "invalid confidence"),
        (lambda f: f.pop("affected"), "missing or malformed 'affected' block"),
        (lambda f: f.__setitem__("suggested_action", {"summary": "x"}), "missing or malformed 'suggested_action' block"),
    ],
)
def test_normalize_rejects_structurally_invalid_findings(mutation, expected_reason_fragment):
    finding = make_finding()
    mutation(finding)
    normalized, rejected = nm.normalize_findings([finding])
    assert normalized == []
    assert len(rejected) == 1
    assert expected_reason_fragment in rejected[0]["reason"]


def test_normalize_rejects_non_dict_finding():
    normalized, rejected = nm.normalize_findings(["not a finding", 42, None])
    assert normalized == []
    assert len(rejected) == 3
    assert all(r["reason"] == "not a finding object" for r in rejected)


def test_normalize_drops_confidence_only_for_explicit_thin_extrapolation():
    finding = make_finding(confidence="high", count=1, total=20, extrapolated=True)
    normalized, _ = nm.normalize_findings([finding])
    assert normalized[0]["confidence"] == "medium"


def test_normalize_preserves_single_direct_observation_confidence():
    finding = make_finding(check_id="D-EXTRACT-04", confidence="high", count=1, total=1)
    normalized, _ = nm.normalize_findings([finding])
    assert normalized[0]["confidence"] == "high"


def test_normalize_never_touches_confidence_at_or_above_floor():
    finding = make_finding(confidence="high", count=3, total=5)
    normalized, _ = nm.normalize_findings([finding])
    assert normalized[0]["confidence"] == "high"


# ---------------------------------------------------------------------------
# Unit tests -- aggregate_dedupe.py
# ---------------------------------------------------------------------------


def test_dedupe_merges_same_check_overlapping_urls():
    a = make_finding(check_id="D-CRAWL-04", urls=["https://example.com/a"], count=1, total=10, confidence="medium")
    b = make_finding(check_id="D-CRAWL-04", urls=["https://example.com/a", "https://example.com/b"], count=2, total=10, confidence="high")

    merged, merge_log = ad.merge_duplicate_findings([a, b])
    assert len(merged) == 1
    # count is the size of the URL UNION ({a, b} = 2), never a sum of the
    # sources' own counts -- summing would double-count the shared URL "a"
    # that is exactly why these two findings merged in the first place.
    assert merged[0]["affected"]["count"] == 2
    assert merged[0]["confidence"] == "high"  # max
    assert set(merged[0]["source_urls"]) == {"https://example.com/a", "https://example.com/b"}
    assert len(merge_log) == 1
    assert merge_log[0]["merged_count"] == 2


def test_dedupe_merge_does_not_double_count_heavily_overlapping_urls():
    # Two near-identical detections of the same defect: 4 URLs each, 3 shared
    # (jaccard 3/5 = 0.6 >= 0.5, so they merge). The true affected population
    # is 5 distinct pages, not 8 -- summing the sources' counts would inflate
    # scope (and therefore severity, via the scope modifier) for the exact
    # scenario merging exists to normalize away: the same defect surfacing
    # twice in the pooled set.
    a = make_finding(check_id="D-EXTRACT-02", urls=["https://example.com/p1", "https://example.com/p2", "https://example.com/p3", "https://example.com/p4"], count=4, total=20)
    b = make_finding(check_id="D-EXTRACT-02", urls=["https://example.com/p2", "https://example.com/p3", "https://example.com/p4", "https://example.com/p5"], count=4, total=20)

    merged, _ = ad.merge_duplicate_findings([a, b])
    assert len(merged) == 1
    assert merged[0]["affected"]["count"] == 5
    assert set(merged[0]["source_urls"]) == {
        "https://example.com/p1", "https://example.com/p2", "https://example.com/p3",
        "https://example.com/p4", "https://example.com/p5",
    }


def test_dedupe_never_merges_different_check_ids():
    a = make_finding(check_id="D-CRAWL-04", urls=["https://example.com/a"])
    b = make_finding(check_id="D-EXTRACT-05", urls=["https://example.com/a"])

    merged, merge_log = ad.merge_duplicate_findings([a, b])
    assert len(merged) == 2
    assert merge_log == []


def test_dedupe_never_merges_non_overlapping_same_check():
    a = make_finding(check_id="D-CRAWL-04", urls=["https://example.com/a"])
    b = make_finding(check_id="D-CRAWL-04", urls=["https://example.com/completely-unrelated"])

    merged, merge_log = ad.merge_duplicate_findings([a, b])
    assert len(merged) == 2
    assert merge_log == []


def test_dedupe_never_merges_distinct_subchecks_on_the_same_pages():
    urls = ["https://example.com/a", "https://example.com/b"]
    description = make_finding(check_id="D-ENTITY-04", urls=urls, mechanism="conflicting descriptions")
    address = make_finding(check_id="D-ENTITY-04", urls=urls, mechanism="conflicting addresses")

    merged, merge_log = ad.merge_duplicate_findings([description, address])

    assert len(merged) == 2
    assert merge_log == []


def test_dedupe_uses_affected_urls_not_context_urls_for_scope():
    a = make_finding(
        check_id="D-CRAWL-04",
        urls=["https://example.com/context", "https://example.com/a"],
        affected_urls=["https://example.com/a"],
    )
    b = make_finding(
        check_id="D-CRAWL-04",
        urls=["https://example.com/context", "https://example.com/b"],
        affected_urls=["https://example.com/b"],
    )
    merged, _ = ad.merge_duplicate_findings([a, b])
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# Unit tests -- score.py: severity modifiers and the critical cap
# ---------------------------------------------------------------------------


def test_score_broad_scope_raises_severity():
    finding = make_finding(check_id="D-EXTRACT-05", severity="medium", confidence="high", count=9, total=10)
    scored = sc.score_finding(finding)
    assert scored["severity"] == "high"
    assert any("scope +1" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_narrow_scope_lowers_severity():
    finding = make_finding(check_id="D-CRAWL-06", severity="high", confidence="high", count=1, total=10)
    scored = sc.score_finding(finding)
    assert scored["severity"] == "medium"
    assert any("scope -1" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_explicitly_requested_deep_page_raises_severity():
    target = "https://example.com/docs/deep/topic"
    finding = make_finding(check_id="D-EXTRACT-05", severity="medium", confidence="high", urls=[target])
    scored = sc.score_finding(finding, {"target": {"requested_url": target}})
    assert scored["severity"] == "high"
    assert any("requested audit target" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_does_not_infer_importance_from_shallow_url_shape():
    finding = make_finding(check_id="D-EXTRACT-05", severity="medium", confidence="high", urls=["https://example.com/"])
    scored = sc.score_finding(finding)
    assert scored["severity"] == "medium"
    assert not any("importance" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_low_confidence_lowers_severity():
    # count=5/total=10 is deliberately scope-neutral (ratio 0.5, count != 1)
    # so this isolates the confidence modifier alone.
    finding = make_finding(check_id="D-EXTRACT-05", severity="medium", confidence="low", count=5, total=10)
    scored = sc.score_finding(finding)
    assert scored["severity"] == "low"
    assert any("confidence -1" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_critical_capped_when_check_not_on_allowlist():
    # base "high" + importance +1 (explicit audit target) would reach "critical"
    finding = make_finding(check_id="D-CRAWL-06", severity="high", confidence="high", urls=["https://example.com/"])
    scored = sc.score_finding(finding, {"target": {"requested_url": "https://example.com/"}})
    assert scored["severity"] == "high"  # capped, never critical
    assert any("critical-cap" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_allowlisted_check_reaches_critical():
    finding = make_finding(check_id="D-CRAWL-01", severity="critical", confidence="high", count=5, total=5)
    scored = sc.score_finding(finding)
    assert scored["severity"] == "critical"
    assert not any("critical-cap" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_allowlisted_check_floor_survives_low_confidence_modifier():
    # The allowlist is a floor as well as a ceiling: a low-confidence modifier
    # (-1) would otherwise knock D-CRAWL-01 from critical(3) to high(2). It
    # must be restored to critical -- confidence alone decides whether this
    # finding is later demoted, not a quietly deflated severity label.
    finding = make_finding(check_id="D-CRAWL-01", severity="critical", confidence="low", count=1, total=1)
    scored = sc.score_finding(finding)
    assert scored["severity"] == "critical"
    assert any("critical-floor" in m for m in scored["scoring_trace"]["modifiers_applied"])


def test_score_never_mutates_original_evidence_fields():
    finding = make_finding(severity="medium", confidence="high")
    scored = sc.score_finding(finding)
    for field in ("title", "mechanism", "impact", "observed_signal", "evidence", "observation_ids", "source_urls"):
        assert scored[field] == finding[field]
    assert scored["suggested_action"]["summary"] == finding["suggested_action"]["summary"]
    assert scored["suggested_action"]["how_to_fix"] == finding["suggested_action"]["how_to_fix"]


# ---------------------------------------------------------------------------
# Unit tests -- demotion
# ---------------------------------------------------------------------------


def test_demote_moves_low_confidence_out_of_findings():
    kept_candidate = sc.score_finding(make_finding(confidence="high"))
    demoted_candidate = sc.score_finding(make_finding(confidence="low"))

    kept, demoted = sc.demote_low_confidence([kept_candidate, demoted_candidate])
    assert kept == [kept_candidate]
    assert demoted == [demoted_candidate]


# ---------------------------------------------------------------------------
# Unit tests -- distribution guard
# ---------------------------------------------------------------------------


def test_distribution_guard_warns_but_preserves_evidence_backed_severities():
    # count=5/total=10 is scope-neutral (ratio 0.5, count != 1) so these three
    # score as "high" untouched, isolating the distribution guard itself.
    # Five total findings clears DISTRIBUTION_GUARD_MIN_FINDINGS so the guard
    # actually evaluates the ratio instead of short-circuiting on sample size.
    findings = [
        sc.score_finding(make_finding(check_id=f"D-EXTRACT-0{i}", severity="high", confidence="medium", count=5, total=10))
        for i in range(1, 4)
    ] + [
        sc.score_finding(make_finding(check_id=f"D-EXTRACT-0{i}", severity="low", confidence="high"))
        for i in range(8, 10)
    ]

    kept, calibration_log = sc.apply_distribution_guard(findings)
    ratio = sum(1 for f in kept if f["severity"] in ("high", "critical")) / len(kept)
    assert ratio > sc.DISTRIBUTION_GUARD_THRESHOLD
    assert [f["severity"] for f in kept[:3]] == ["high", "high", "high"]
    assert calibration_log == [{
        "type": "severity_distribution_warning",
        "high_critical_ratio": ratio,
        "threshold": sc.DISTRIBUTION_GUARD_THRESHOLD,
        "finding_count": len(findings),
    }]


def test_finding_severity_is_invariant_to_unrelated_findings():
    focal = sc.score_finding(make_finding(check_id="D-EXTRACT-01", severity="high", confidence="high", count=5, total=10))
    baseline, _ = sc.apply_distribution_guard([focal])
    expanded = [focal] + [
        sc.score_finding(make_finding(check_id=f"D-X-{i}", severity="high", confidence="high", count=5, total=10))
        for i in range(10)
    ]
    after, _ = sc.apply_distribution_guard(expanded)
    assert baseline[0]["severity"] == after[0]["severity"] == "high"


def test_distribution_guard_never_touches_critical():
    # Five total findings clears DISTRIBUTION_GUARD_MIN_FINDINGS.
    findings = [
        sc.score_finding(make_finding(check_id="D-CRAWL-01", severity="critical", confidence="high", count=1, total=1)),
        sc.score_finding(make_finding(check_id="D-EXTRACT-01", severity="high", confidence="medium", count=1, total=10)),
        sc.score_finding(make_finding(check_id="D-EXTRACT-02", severity="high", confidence="medium", count=1, total=10)),
    ] + [
        sc.score_finding(make_finding(check_id=f"D-EXTRACT-0{i}", severity="low", confidence="high"))
        for i in range(3, 5)
    ]
    kept, _ = sc.apply_distribution_guard(findings)
    critical = [f for f in kept if f["check_id"] == "D-CRAWL-01"]
    assert critical[0]["severity"] == "critical"


def test_distribution_guard_skips_recalibration_below_min_findings():
    # Two findings, one high and one low, is a 50% high-ratio -- over
    # threshold on paper -- but with only 2 findings that ratio is an
    # artifact of report size, not evidence of miscalibration. A genuinely
    # severe, well-evidenced problem must not be watered down just because
    # the rest of the report happens to be short.
    findings = [
        sc.score_finding(make_finding(check_id="D-CRAWL-06", severity="high", confidence="high", count=5, total=10)),
        sc.score_finding(make_finding(check_id="D-EXTRACT-05", severity="low", confidence="high")),
    ]
    assert len(findings) < sc.DISTRIBUTION_GUARD_MIN_FINDINGS

    kept, calibration_log = sc.apply_distribution_guard(findings)
    assert calibration_log == []
    severities = {f["check_id"]: f["severity"] for f in kept}
    assert severities["D-CRAWL-06"] == "high"
    assert severities["D-EXTRACT-05"] == "low"


def test_distribution_guard_no_op_under_threshold():
    findings = [sc.score_finding(make_finding(check_id="D-EXTRACT-01", severity="high", confidence="high", count=8, total=10))]
    findings += [
        sc.score_finding(make_finding(check_id=f"D-EXTRACT-0{i}", severity="low", confidence="high")) for i in range(2, 8)
    ]
    kept, calibration_log = sc.apply_distribution_guard(findings)
    assert calibration_log == []
    assert kept[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# Unit tests -- cross-skill relationship linking
# ---------------------------------------------------------------------------


def test_link_related_findings_cross_links_different_checks_on_shared_url():
    a = dict(make_finding(check_id="D-ENTITY-02", urls=["https://example.com/deep"]), id="F-001")
    b = dict(make_finding(check_id="E-ORIENT-01", urls=["https://example.com/deep"]), id="F-002")

    linked = sc.link_related_findings([a, b])
    assert linked[1]["id"] in linked[0]["related_findings"]
    assert linked[0]["id"] in linked[1]["related_findings"]


def test_link_related_findings_never_links_same_check_id():
    a = dict(make_finding(check_id="D-CRAWL-04", urls=["https://example.com/deep"]), id="F-001")
    b = dict(make_finding(check_id="D-CRAWL-04", urls=["https://example.com/deep"]), id="F-002")

    linked = sc.link_related_findings([a, b])
    assert linked[0]["related_findings"] == []
    assert linked[1]["related_findings"] == []


def test_link_related_findings_never_links_unrelated_urls():
    a = dict(make_finding(check_id="D-ENTITY-02", urls=["https://example.com/a"]), id="F-001")
    b = dict(make_finding(check_id="E-ORIENT-01", urls=["https://example.com/b"]), id="F-002")

    linked = sc.link_related_findings([a, b])
    assert linked[0]["related_findings"] == []
    assert linked[1]["related_findings"] == []


# ---------------------------------------------------------------------------
# Unit tests -- ranking and id assignment
# ---------------------------------------------------------------------------


def test_rank_orders_by_severity_then_confidence_then_urgency_then_count():
    low = sc.score_finding(make_finding(check_id="D-EXTRACT-05", severity="low", confidence="high"))
    medium = sc.score_finding(make_finding(check_id="D-CRAWL-05", severity="medium", confidence="high"))
    high = sc.score_finding(make_finding(check_id="D-EXTRACT-04", severity="high", confidence="high", count=1, total=1))
    urgent_high = sc.score_finding(make_finding(check_id="D-CRAWL-04", severity="high", confidence="high", count=1, total=1, urls=["https://example.com/x"]))

    ranked = sc.rank_findings([low, medium, high, urgent_high])
    assert [f["check_id"] for f in ranked][:2] == ["D-CRAWL-04", "D-EXTRACT-04"]  # both "high"; urgent one first
    assert ranked[-1]["check_id"] == "D-EXTRACT-05"  # low severity sorts last


def test_assign_ids_sequential_and_non_colliding_between_findings_and_demoted():
    findings = [make_finding(check_id=f"D-EXTRACT-0{i}") for i in range(1, 4)]
    demoted = [make_finding(check_id=f"D-CRAWL-0{i}") for i in range(1, 3)]

    sc.assign_ids(findings, prefix="F")
    sc.assign_ids(demoted, prefix="D")

    assert [f["id"] for f in findings] == ["F-001", "F-002", "F-003"]
    assert [f["id"] for f in demoted] == ["D-001", "D-002"]
    assert set(f["id"] for f in findings).isdisjoint({f["id"] for f in demoted})


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_integration_full_pipeline_shape_and_schema_conformance():
    pooled = [
        make_finding(check_id="D-CRAWL-01", severity="critical", confidence="high", count=1, total=1),
        make_finding(check_id="D-EXTRACT-05", severity="low", confidence="high", count=1, total=12),
        make_finding(check_id="D-TRUST-04", severity="low", confidence="low"),
        {"check_id": "D-BROKEN", "severity": "not-a-real-severity"},
    ]

    result = sc.prioritize_findings(pooled)

    assert len(result["findings"]) == 2  # critical + low kept; low-confidence demoted; malformed rejected
    assert len(result["demoted"]) == 1
    assert len(result["rejected"]) == 1
    for finding in result["findings"]:
        assert_finding_shape(finding)
    # ranked: critical must come first
    assert result["findings"][0]["check_id"] == "D-CRAWL-01"


def test_integration_never_creates_a_new_finding():
    """This skill may only merge, demote, rank, or drop -- never invent a
    finding not traceable to an input. Every output finding's check_id must
    exist among the pooled input check_ids."""
    pooled = [
        make_finding(check_id="D-CRAWL-04", urls=["https://example.com/a"]),
        make_finding(check_id="D-CRAWL-04", urls=["https://example.com/b"]),
        make_finding(check_id="D-EXTRACT-05"),
    ]
    input_check_ids = {f["check_id"] for f in pooled}

    result = sc.prioritize_findings(pooled)
    output_check_ids = {f["check_id"] for f in result["findings"]} | {f["check_id"] for f in result["demoted"]}
    assert output_check_ids <= input_check_ids


def test_integration_real_crawl_and_entity_findings_through_the_pipeline(tmp_path):
    """Runs the real crawl-render-audit and entity-semantic-audit detectors on
    a synthetic store and pools their actual output through this skill -- a
    genuine cross-skill composition test."""
    crawl_scripts = ROOT / "skills" / "crawl-render-audit" / "scripts"
    entity_scripts = ROOT / "skills" / "entity-semantic-audit" / "scripts"
    for path in (str(crawl_scripts), str(entity_scripts)):
        if path not in sys.path:
            sys.path.insert(0, path)

    import detect_crawl
    import detect_entity
    import build_entity_profile
    from lib.common.observations import make_observation

    def fetch_obs(url, html, status_code=200):
        value = {
            "status_code": status_code,
            "final_url": url,
            "redirect_chain": [],
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "encoding": "utf-8",
            "elapsed_ms": 100,
            "evidence": {"status": "ok", "content_type": "text/html", "redirect_count": 0, "final_url": url},
            "html": html,
        }
        return make_observation("HTTP_FETCH", url, value)

    # A page with no name candidates at all (fires D-ENTITY-01) that also
    # 404s when linked from elsewhere is out of scope here; keep it simple:
    # one page with noindex (D-CRAWL-03, critical) and no brand name anywhere
    # (D-ENTITY-01).
    html = "<html><head><title></title><meta name=\"robots\" content=\"noindex\"></head><body><h1></h1><p>" + (
        "Some content here today without any name at all. " * 10
    ) + "</p></body></html>"
    store = {
        "store_version": "1.0",
        "collected_at": "2026-01-01T00:00:00Z",
        "target": {"audited_host": "example.com"},
        "capabilities": {},
        "archetype": "brand-product",
        "observations": [fetch_obs("https://example.com/deep/page", html)],
    }

    crawl_findings = detect_crawl.detect_crawl(store)
    entity_profile = build_entity_profile.build_entity_profile(store)
    entity_findings = detect_entity.detect_entity(store, entity_profile)

    pooled = crawl_findings + entity_findings
    assert pooled, "expected at least one real finding from each detector to combine"

    result = sc.prioritize_findings(pooled)

    for finding in result["findings"]:
        assert_finding_shape(finding)
    # D-CRAWL-03 (noindex) is on this skill's critical path via its own
    # proposed severity; confirm it survived the pipeline and sorts first.
    assert any(f["check_id"] == "D-CRAWL-03" for f in result["findings"])
    assert result["findings"][0]["severity"] in ("critical", "high")


# ---------------------------------------------------------------------------
# Regression tests -- hostile-review scenarios
# ---------------------------------------------------------------------------


def test_hostile_severe_issue_weak_evidence_is_demoted_not_asserted():
    """A critical-severity, low-confidence finding (severe if true, but shaky)
    must never be reported as a confident critical defect -- it is demoted
    entirely, preserving its severity for context but keeping it out of the
    asserted findings list."""
    pooled = [make_finding(check_id="D-CRAWL-01", severity="critical", confidence="low", count=1, total=1)]
    result = sc.prioritize_findings(pooled)
    assert result["findings"] == []
    assert len(result["demoted"]) == 1
    assert result["demoted"][0]["severity"] == "critical"
    assert result["demoted"][0]["confidence"] == "low"


def test_hostile_minor_issue_strong_evidence_can_still_rise_but_not_uncapped():
    """A low-severity finding backed by overwhelming, sitewide, high-confidence
    evidence is allowed to rise (scope/importance modifiers exist precisely so
    a low base severity isn't stuck at 'low' when the pattern is real and
    pervasive) but must never bypass the critical cap for a non-allowlisted
    check."""
    pooled = [
        make_finding(
            check_id="D-EXTRACT-05",
            severity="low",
            confidence="high",
            urls=[f"https://example.com/p{i}" for i in range(20)],
            count=20,
            total=20,
        )
    ]
    result = sc.prioritize_findings(pooled)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["severity"] != "critical"  # D-EXTRACT-05 is not on the allowlist


def test_hostile_multiple_skills_same_root_cause_cross_linked_not_merged():
    """Two different skills' findings about the same underlying page (different
    check_ids, different mechanisms) are never merged into one -- each keeps
    its own evidence and severity -- but they are cross-referenced via
    related_findings so a reader can see they co-occur."""
    pooled = [
        make_finding(check_id="D-ENTITY-02", category="entity", urls=["https://example.com/about"], count=1, total=5, confidence="high"),
        make_finding(check_id="E-ORIENT-01", category="engagement", urls=["https://example.com/about"], count=1, total=5, confidence="high"),
    ]
    result = sc.prioritize_findings(pooled)
    assert len(result["findings"]) == 2
    ids_by_check = {f["check_id"]: f["id"] for f in result["findings"]}
    entity_finding = next(f for f in result["findings"] if f["check_id"] == "D-ENTITY-02")
    orient_finding = next(f for f in result["findings"] if f["check_id"] == "E-ORIENT-01")
    assert ids_by_check["E-ORIENT-01"] in entity_finding["related_findings"]
    assert ids_by_check["D-ENTITY-02"] in orient_finding["related_findings"]


def test_hostile_sitewide_high_impact_outranks_single_page_low_impact():
    """A sitewide, homepage-affecting canonical-conflict finding must rank
    ahead of, and score meaningfully higher than, an isolated single-page
    finding -- even in a small report where the distribution guard's
    min-findings floor (regression above) would otherwise incorrectly water
    the sitewide finding down to match."""
    pooled = [
        make_finding(
            check_id="D-CRAWL-06",
            severity="high",
            confidence="high",
            urls=[f"https://example.com/p{i}" for i in range(1, 10)] + ["https://example.com/"],
            count=10,
            total=10,
        ),
        make_finding(check_id="D-EXTRACT-05", severity="low", confidence="high", urls=["https://example.com/deep/page"], count=1, total=20),
    ]
    result = sc.prioritize_findings(pooled)
    assert result["findings"][0]["check_id"] == "D-CRAWL-06"
    assert result["findings"][0]["severity"] in ("high", "critical")
    assert result["findings"][1]["check_id"] == "D-EXTRACT-05"
    assert sc.severity_index(result["findings"][0]["severity"]) > sc.severity_index(result["findings"][1]["severity"])


def test_hostile_confidence_severity_disagreement_in_small_report():
    """A severe (high-severity), medium-confidence finding must not be
    silently deflated by the distribution guard just because it happens to
    share a small report with an unrelated low-severity finding -- it should
    stand on its own evidence."""
    pooled = [
        make_finding(check_id="D-CRAWL-05", severity="low", confidence="high", urls=["https://example.com/x"], count=1, total=10),
        make_finding(check_id="D-CRAWL-06", severity="high", confidence="medium", urls=["https://example.com/y"], count=1, total=None),
    ]
    result = sc.prioritize_findings(pooled)
    severities = {f["check_id"]: f["severity"] for f in result["findings"]}
    assert severities["D-CRAWL-06"] == "high"
    assert severities["D-CRAWL-05"] == "low"
