"""Tests for the audit-orchestrator skill -- the marketplace's only entrypoint.

Two kinds:
- Unit tests: the new site_observer/lib pieces this skill depends on (budget,
  schema, crawl, collect, classify) and the orchestrator's own validate_report
  / proactive helpers, one at a time.
- Integration tests: `run_audit()` end to end against a synthetic, injected
  site (never real network), showing multiple detector skills independently
  produce findings and the orchestrator composes them into one prioritized,
  schema-valid report.

Run from the marketplace root: `python -m pytest tests/test_audit_orchestrator.py`.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR_SCRIPTS = ROOT / "skills" / "audit-orchestrator" / "scripts"
if str(ORCHESTRATOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_SCRIPTS))

import proactive  # noqa: E402
import run_audit  # noqa: E402
import validate_report  # noqa: E402

from lib.common.budget import Budget  # noqa: E402
from lib.common.observations import make_observation  # noqa: E402
from lib.common.schema import validate_report as validate_report_schema  # noqa: E402
from lib.site_observer.classify import classify_archetype  # noqa: E402
from lib.site_observer.collect import collect  # noqa: E402
from lib.site_observer.crawl import crawl, stratified_sample, template_shape  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

FIXED_NOW = lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)  # noqa: E731
NO_SLEEP = lambda seconds: None  # noqa: E731


def make_fetch(pages_html: Dict[str, str], status_overrides: Optional[Dict[str, int]] = None):
    status_overrides = status_overrides or {}

    def fetch(url: str) -> Dict[str, Any]:
        html = pages_html.get(url)
        status = status_overrides.get(url, 200 if html is not None else 404)
        return {
            "status_code": status,
            "final_url": url,
            "redirect_chain": [],
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "encoding": "utf-8",
            "elapsed_ms": 5,
            "evidence": {"status": "ok" if status < 400 else "http_error"},
            "html": html or "",
        }

    return fetch


def robots_missing(origin: str) -> Dict[str, Any]:
    return {"url": origin + "/robots.txt", "status": "missing", "allow_all": True, "document": {"groups": [], "sitemap": [], "rules": []}}


def robots_disallow_all(origin: str) -> Dict[str, Any]:
    return {
        "url": origin + "/robots.txt",
        "status": "ok",
        "allow_all": False,
        "document": {"groups": [{"user_agent": "*", "allow": [], "disallow": ["/"]}], "sitemap": [], "rules": ["/"]},
    }


def robots_error(origin: str) -> Dict[str, Any]:
    return {"url": origin + "/robots.txt", "status": "error", "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}


def acme_site() -> Dict[str, str]:
    home = (
        '<html><head><title>Acme Corp</title>'
        '<meta name="description" content="Acme makes widgets">'
        '<script type="application/ld+json">{"@type":"Organization","name":"Acme Corp"}</script>'
        '<meta name="robots" content="noindex"></head>'
        "<body><h1>Acme</h1><p>" + ("Acme builds industrial widgets for factories worldwide. " * 20) + "</p>"
        '<a href="/about">about</a><a href="/products">products</a></body></html>'
    )
    about = "<html><head><title>About</title></head><body><p>" + ("About Acme. " * 30) + "</p></body></html>"
    products = "<html><head><title>Products</title></head><body><p>" + ("Products list. " * 30) + "</p></body></html>"
    return {
        "https://acme.example/": home,
        "https://acme.example/about": about,
        "https://acme.example/products": products,
    }


# ---------------------------------------------------------------------------
# Unit tests -- lib/common/budget.py
# ---------------------------------------------------------------------------


def test_budget_page_cap_enforced():
    budget = Budget({"raw_crawl_max_pages": 2})
    assert budget.can_fetch_page()
    budget.record_page_fetch()
    budget.record_page_fetch()
    assert not budget.can_fetch_page()


def test_budget_stage_time_left_uses_injectable_clock():
    ticks = iter([100.0, 100.0, 130.0])
    budget = Budget({"raw_crawl_s": 20}, clock=lambda: next(ticks))
    budget.start_stage("raw_crawl")
    assert budget.stage_time_left_s("raw_crawl", "raw_crawl_s") == 20
    assert budget.stage_exceeded("raw_crawl", "raw_crawl_s")  # 30s elapsed > 20s budget


def test_budget_model_call_cap_enforced():
    budget = Budget({"model_calls_max": 1})
    assert budget.can_call_model()
    budget.record_model_call()
    assert not budget.can_call_model()


# ---------------------------------------------------------------------------
# Unit tests -- lib/common/schema.py
# ---------------------------------------------------------------------------


def test_validate_report_schema_accepts_minimal_valid_report():
    ok, errors = validate_report_schema(
        {"site": "x", "audited_at": "2026-01-01T00:00:00Z", "summary": {"total_findings": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}, "findings": []}
    )
    assert ok
    assert errors == []


def test_validate_report_schema_rejects_missing_required_fields():
    ok, errors = validate_report_schema({"site": "x"})
    assert not ok
    assert any("required" in e for e in errors)


# ---------------------------------------------------------------------------
# Unit tests -- lib/site_observer/classify.py
# ---------------------------------------------------------------------------


def test_classify_archetype_from_jsonld_local_business():
    obs = make_observation("HTTP_FETCH", "https://x.example/", {"html": '<script type="application/ld+json">{"@type":"LocalBusiness"}</script>'})
    assert classify_archetype({"observations": [obs]}) == "local-business"


def test_classify_archetype_from_graph_node_with_schema_type_uri():
    html = """
    <script type="Application/LD+JSON; charset=utf-8">
      {"@context":"https://schema.org","@graph":[
        {"@type":"https://schema.org/LocalBusiness","name":"Northstar Repair"}
      ]}
    </script>
    """
    obs = make_observation("HTTP_FETCH", "https://x.example/", {"html": html})

    assert classify_archetype({"observations": [obs]}) == "local-business"


def test_classify_archetype_returns_empty_when_unclear():
    assert classify_archetype({"observations": []}) == ""


# ---------------------------------------------------------------------------
# Unit tests -- lib/site_observer/crawl.py
# ---------------------------------------------------------------------------


def test_crawl_discovers_same_host_links_and_excludes_external():
    pages = {
        "https://example.com/": '<a href="/about">about</a><a href="https://other.example/x">ext</a>',
        "https://example.com/about": "<p>about</p>",
    }
    result = crawl("https://example.com/", make_fetch(pages), robots=None, max_pages=10)
    assert sorted(result["pages"].keys()) == ["https://example.com/", "https://example.com/about"]


def test_crawl_respects_robots_disallow_for_discovered_paths():
    pages = {
        "https://example.com/": '<a href="/private/x">private</a><a href="/public">public</a>',
        "https://example.com/private/x": "<p>secret</p>",
        "https://example.com/public": "<p>public</p>",
    }
    robots = {"status": "ok", "document": {"groups": [{"user_agent": "*", "allow": [], "disallow": ["/private"]}]}}
    result = crawl("https://example.com/", make_fetch(pages), robots=robots, max_pages=10)
    assert "https://example.com/private/x" not in result["pages"]
    assert "https://example.com/public" in result["pages"]
    assert "https://example.com/private/x" in result["skipped_robots"]


def test_crawl_respects_max_pages_budget():
    pages = {f"https://example.com/p{i}": f'<a href="/p{i+1}">next</a>' for i in range(20)}
    pages["https://example.com/"] = '<a href="/p0">start</a>'
    result = crawl("https://example.com/", make_fetch(pages), robots=None, max_pages=5)
    assert len(result["pages"]) == 5


def test_crawl_disallow_all_seed_yields_zero_pages():
    def fetch_should_never_be_called(url):
        raise AssertionError(f"fetch must never be called when the seed itself is disallowed: {url}")

    robots = {"status": "ok", "document": {"groups": [{"user_agent": "*", "allow": [], "disallow": ["/"]}]}}
    result = crawl("https://example.com/", fetch_should_never_be_called, robots=robots, max_pages=10)
    assert result["pages"] == {}
    assert result["skipped_robots"] == ["https://example.com/"]


def test_crawl_applies_polite_delay_between_but_not_before_first_fetch():
    pages = {"https://example.com/": '<a href="/a">a</a>', "https://example.com/a": ""}
    calls: List[float] = []
    crawl("https://example.com/", make_fetch(pages), robots=None, max_pages=10, polite_delay_s=0.3, sleep=calls.append)
    assert calls == [0.3]


def test_template_shape_collapses_numeric_ids():
    assert template_shape("/product/123") == "/product/#"
    assert template_shape("/about") == "/about"


def test_stratified_sample_spreads_across_clusters_before_repeating():
    clusters = {"/a": ["u1", "u2", "u3"], "/b": ["u4"]}
    assert stratified_sample(clusters, 2) == ["u1", "u4"]


# ---------------------------------------------------------------------------
# Unit tests -- lib/site_observer/collect.py
# ---------------------------------------------------------------------------


def test_collect_deep_page_audits_requested_url_not_the_homepage():
    pages = acme_site()
    result = collect(
        "https://acme.example/products",
        budget=Budget(),
        fetch=make_fetch(pages),
        robots_fetcher=robots_missing,
        render_capability={"available": False, "reason": "x"},
        now=FIXED_NOW,
        sleep=NO_SLEEP,
    )
    fetched_urls = {obs["source_url"] for obs in result["store"]["observations"] if obs["type"] == "HTTP_FETCH"}
    assert "https://acme.example/products" in fetched_urls
    assert "https://acme.example/" not in fetched_urls  # never silently collapses to the homepage


def test_collect_records_cross_domain_redirect_as_requested_vs_audited_host():
    def fetch(url):
        if url == "https://acme.example/":
            return {"status_code": 301, "final_url": "https://www.acme.example/", "redirect_chain": [], "headers": {}, "encoding": "utf-8", "elapsed_ms": 1, "evidence": {"status": "ok"}, "html": "<title>Home</title>"}
        return {"status_code": 200, "final_url": url, "redirect_chain": [], "headers": {}, "encoding": "utf-8", "elapsed_ms": 1, "evidence": {"status": "ok"}, "html": ""}

    result = collect("https://acme.example/", budget=Budget(), fetch=fetch, robots_fetcher=robots_missing, render_capability={"available": False, "reason": "x"}, now=FIXED_NOW, sleep=NO_SLEEP)
    target = result["store"]["target"]
    assert target["requested_host"] == "acme.example"
    assert target["audited_host"] == "www.acme.example"


def test_collect_disallow_all_crawls_nothing_and_reports_coverage():
    def fetch_should_never_be_called(url):
        raise AssertionError("fetch must never be called: robots.txt disallows everything")

    result = collect("https://acme.example/", budget=Budget(), fetch=fetch_should_never_be_called, robots_fetcher=robots_disallow_all, render_capability={"available": False, "reason": "x"}, now=FIXED_NOW, sleep=NO_SLEEP)
    assert result["scope"]["pages_crawled"] == 0
    assert result["scope"]["disallowed"] is True
    assert any(c["reason"] == "ROBOTS_DISALLOWED" for c in result["coverage"])


def test_collect_respects_max_pages_budget_override():
    pages = {f"https://acme.example/p{i}": '<a href="/p{}">next</a>'.format(i + 1) for i in range(20)}
    pages["https://acme.example/"] = '<a href="/p0">start</a>'
    result = collect("https://acme.example/", budget=Budget({"raw_crawl_max_pages": 4}), fetch=make_fetch(pages), robots_fetcher=robots_missing, render_capability={"available": False, "reason": "x"}, now=FIXED_NOW, sleep=NO_SLEEP)
    assert result["scope"]["pages_crawled"] == 4
    assert any(c["reason"] == "BUDGET_EXHAUSTED" for c in result["coverage"])


# ---------------------------------------------------------------------------
# Unit tests -- validate_report.py (evidence binding)
# ---------------------------------------------------------------------------


def _minimal_finding(**overrides) -> Dict[str, Any]:
    base = {
        "id": "F-001",
        "check_id": "D-TEST-01",
        "category": "test",
        "title": "test finding",
        "severity": "medium",
        "confidence": "high",
        "mechanism": "some mechanism",
        "impact": "some impact",
        "observed_signal": "some signal",
        "evidence": "evidence text",
        "observation_ids": [],
        "source_urls": [],
        "affected": {"count": 1, "sample_urls": [], "total_in_scope": 1},
        "suggested_action": {"summary": "fix it", "priority": "medium"},
    }
    base.update(overrides)
    return base


def test_bind_evidence_keeps_finding_with_resolvable_observation_id():
    store = {"observations": [make_observation("HTTP_FETCH", "https://x.example/", {"html": ""})]}
    obs_id = store["observations"][0]["id"]
    finding = _minimal_finding(observation_ids=[obs_id])
    kept, dropped = validate_report.bind_evidence([finding], store)
    assert kept == [finding]
    assert dropped == []


def test_bind_evidence_drops_finding_with_unresolvable_observation_id():
    store = {"observations": [make_observation("HTTP_FETCH", "https://x.example/", {"html": ""})]}
    finding = _minimal_finding(observation_ids=["OBS-FAKE-doesnotexist"])
    kept, dropped = validate_report.bind_evidence([finding], store)
    assert kept == []
    assert len(dropped) == 1
    assert "unresolved observation_ids" in dropped[0]["reason"]


def test_bind_evidence_accepts_absence_finding_anchored_by_source_urls():
    """The marketplace-wide pattern: an absence finding cites no positive
    observation_id but names the pages it examined -- must not be dropped
    just because it has no observation_ids."""
    store = {"observations": [make_observation("HTTP_FETCH", "https://x.example/about", {"html": ""})]}
    finding = _minimal_finding(observation_ids=[], source_urls=["https://x.example/about"])
    kept, dropped = validate_report.bind_evidence([finding], store)
    assert kept == [finding]
    assert dropped == []


def test_bind_evidence_drops_finding_with_no_evidence_at_all():
    store = {"observations": [make_observation("HTTP_FETCH", "https://x.example/", {"html": ""})]}
    finding = _minimal_finding(observation_ids=[], source_urls=[])
    kept, dropped = validate_report.bind_evidence([finding], store)
    assert kept == []
    assert dropped[0]["reason"] == "no observation_ids or source_urls cited"


def test_bind_evidence_drops_finding_whose_source_url_was_never_fetched():
    store = {"observations": [make_observation("HTTP_FETCH", "https://x.example/", {"html": ""})]}
    finding = _minimal_finding(observation_ids=[], source_urls=["https://x.example/never-fetched"])
    kept, dropped = validate_report.bind_evidence([finding], store)
    assert kept == []
    assert "unresolved source_urls" in dropped[0]["reason"]


# ---------------------------------------------------------------------------
# Unit tests -- proactive.py
# ---------------------------------------------------------------------------


def test_proactive_flags_missing_sameas_for_organization_markup():
    obs = make_observation("HTTP_FETCH", "https://x.example/", {"html": '<script type="application/ld+json">{"@type":"Organization","name":"X"}</script>'})
    opportunities = proactive.generate_proactive_opportunities({"observations": [obs]}, demoted=[])
    assert any(o["source"] == "identity_anchor_gap" for o in opportunities)


def test_proactive_says_nothing_when_sameas_present():
    obs = make_observation("HTTP_FETCH", "https://x.example/", {"html": '<script type="application/ld+json">{"@type":"Organization","name":"X","sameAs":["https://en.wikipedia.org/wiki/X"]}</script>'})
    opportunities = proactive.generate_proactive_opportunities({"observations": [obs]}, demoted=[])
    assert not any(o["source"] == "identity_anchor_gap" for o in opportunities)


def test_proactive_reframes_demoted_findings_never_as_defects():
    demoted = [{"check_id": "D-TEST-01", "title": "some claim", "observed_signal": "weak evidence", "mechanism": "m", "impact": "i", "evidence": "e"}]
    opportunities = proactive.generate_proactive_opportunities({"observations": []}, demoted=demoted)
    assert len(opportunities) == 1
    assert opportunities[0]["source"] == "demoted_finding"


# ---------------------------------------------------------------------------
# Integration tests -- run_audit() end to end
# ---------------------------------------------------------------------------


def test_marketplace_declares_exactly_one_entrypoint():
    manifest = json.loads((ROOT / "marketplace.json").read_text(encoding="utf-8"))
    entrypoints = [s for s in manifest["skills"] if s.get("entrypoint")]
    assert len(entrypoints) == 1
    assert entrypoints[0]["id"] == "audit-orchestrator"


def test_run_audit_composes_findings_from_multiple_detector_skills():
    """The central integration scenario: crawl-render-audit (noindex),
    entity-semantic-audit (missing type/offering/anchor) and engagement-audit
    each independently produce findings over the same store, and run_audit
    composes them into one prioritized, schema-valid report."""
    pages = acme_site()
    report = run_audit.run_audit(
        "https://acme.example/",
        fetch=make_fetch(pages),
        robots_fetcher=robots_missing,
        render_capability={"available": False, "reason": "x"},
        now=FIXED_NOW,
        sleep=NO_SLEEP,
    )

    check_prefixes = {f["check_id"].split("-")[0] + "-" + f["check_id"].split("-")[1] for f in report["findings"]}
    assert "D-CRAWL" in check_prefixes
    assert "D-ENTITY" in check_prefixes
    assert len({f["check_id"] for f in report["findings"]}) >= 3

    is_valid, errors = validate_report_schema(report)
    assert is_valid, errors
    assert report["run"]["schema_valid"] is True
    assert report["run"]["evidence_binding_drops"] == []
    assert report["run"]["skill_failures"] == []
    assert report["summary"]["total_findings"] == len(report["findings"])


def test_run_audit_is_deterministic_given_the_same_inputs():
    pages = acme_site()
    kwargs = dict(fetch=make_fetch(pages), robots_fetcher=robots_missing, render_capability={"available": False, "reason": "x"}, now=FIXED_NOW, sleep=NO_SLEEP)
    report_a = run_audit.run_audit("https://acme.example/", **kwargs)
    report_b = run_audit.run_audit("https://acme.example/", **kwargs)
    assert report_a == report_b


def test_run_audit_never_fetches_a_page_when_robots_disallows_all():
    def fetch_should_never_be_called(url):
        raise AssertionError(f"a page fetch is a rate/compliance violation when robots disallows everything: {url}")

    report = run_audit.run_audit(
        "https://acme.example/",
        fetch=fetch_should_never_be_called,
        robots_fetcher=robots_disallow_all,
        render_capability={"available": False, "reason": "x"},
        now=FIXED_NOW,
        sleep=NO_SLEEP,
    )
    assert {f["check_id"] for f in report["findings"]} == {"D-CRAWL-01"}
    assert report["scope"]["pages_crawled"] == 0
    assert any(c["reason"] == "ROBOTS_DISALLOWED" for c in report["coverage"])
    is_valid, errors = validate_report_schema(report)
    assert is_valid, errors


def test_run_audit_robots_unreachable_yields_critical_finding_and_valid_report():
    def fetch_should_never_be_called(url):
        raise AssertionError("crawl must not proceed when robots.txt itself could not be read")

    report = run_audit.run_audit(
        "https://acme.example/",
        fetch=fetch_should_never_be_called,
        robots_fetcher=robots_error,
        render_capability={"available": False, "reason": "x"},
        now=FIXED_NOW,
        sleep=NO_SLEEP,
    )
    assert any(f["check_id"] == "D-CRAWL-15" and f["severity"] == "critical" for f in report["findings"])
    is_valid, errors = validate_report_schema(report)
    assert is_valid, errors


def test_run_audit_handles_one_skill_raising_without_losing_the_others(monkeypatch):
    """Graceful skill-failure handling: one detector raising must not take
    down the audit or hide the other three skills' findings."""
    detect_trust_path = str(ROOT / "skills" / "trust-freshness-audit" / "scripts")
    if detect_trust_path not in sys.path:
        sys.path.insert(0, detect_trust_path)
    import detect_trust

    def boom(store, claim_table=None):
        raise RuntimeError("synthetic detector failure")

    monkeypatch.setattr(detect_trust, "detect_trust", boom)

    pages = acme_site()
    report = run_audit.run_audit(
        "https://acme.example/",
        fetch=make_fetch(pages),
        robots_fetcher=robots_missing,
        render_capability={"available": False, "reason": "x"},
        now=FIXED_NOW,
        sleep=NO_SLEEP,
    )

    assert any(f["check_id"] == "D-CRAWL-03" for f in report["findings"])  # crawl-render-audit still ran
    assert any(f["check_id"].startswith("D-ENTITY") for f in report["findings"])  # entity-semantic-audit still ran
    assert any(sf["skill"] == "trust-freshness-audit" for sf in report["run"]["skill_failures"])
    assert any(c["reason"] == "SKILL_FAILED" and c["scope"] == "trust-freshness-audit" for c in report["coverage"])
    is_valid, errors = validate_report_schema(report)
    assert is_valid, errors


def test_run_audit_drops_a_fabricated_unsupported_finding(monkeypatch):
    """A detector that emits a finding citing an observation ID that does
    not exist in the store must have that finding dropped, never emitted."""
    detect_crawl_path = str(ROOT / "skills" / "crawl-render-audit" / "scripts")
    if detect_crawl_path not in sys.path:
        sys.path.insert(0, detect_crawl_path)
    import detect_crawl

    def fabricated(store):
        return [_minimal_finding(id=None, check_id="D-CRAWL-99", observation_ids=["OBS-FAKE-not-real"], source_urls=[])]

    monkeypatch.setattr(detect_crawl, "detect_crawl", fabricated)

    pages = acme_site()
    report = run_audit.run_audit(
        "https://acme.example/",
        fetch=make_fetch(pages),
        robots_fetcher=robots_missing,
        render_capability={"available": False, "reason": "x"},
        now=FIXED_NOW,
        sleep=NO_SLEEP,
    )
    assert not any(f.get("check_id") == "D-CRAWL-99" for f in report["findings"])
    assert any(d["check_id"] == "D-CRAWL-99" for d in report["run"]["evidence_binding_drops"])


def test_run_audit_respects_page_budget_override():
    pages = {f"https://acme.example/p{i}": '<a href="/p{}">next</a>'.format(i + 1) for i in range(30)}
    pages["https://acme.example/"] = '<a href="/p0">start</a>'
    report = run_audit.run_audit(
        "https://acme.example/",
        options={"budget": {"raw_crawl_max_pages": 6}},
        fetch=make_fetch(pages),
        robots_fetcher=robots_missing,
        render_capability={"available": False, "reason": "x"},
        now=FIXED_NOW,
        sleep=NO_SLEEP,
    )
    assert report["scope"]["pages_crawled"] == 6


def test_run_audit_writes_report_json_and_report_md(tmp_path, monkeypatch):
    """CLI path: exactly one entrypoint, writing both artifacts."""
    pages = acme_site()
    real_run_audit = run_audit.run_audit

    def fake_run_audit(url, options=None, **kwargs):
        return real_run_audit(url, options, fetch=make_fetch(pages), robots_fetcher=robots_missing, render_capability={"available": False, "reason": "x"}, now=FIXED_NOW, sleep=NO_SLEEP)

    monkeypatch.setattr(run_audit, "run_audit", fake_run_audit)
    exit_code = run_audit.main(["https://acme.example/", "--out-dir", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["site"] == "acme.example"
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "acme.example" in markdown
