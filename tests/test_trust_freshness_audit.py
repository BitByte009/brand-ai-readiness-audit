"""Tests for the trust-freshness-audit skill.

Four kinds, in order below:
- Unit tests: one check function at a time, against a hand-built store + a
  directly-built claim_table.
- Integration tests: the full `build_claim_table.py` -> `detect_trust.py`
  pipeline (two-script CLI contract), and `corroborate.py`'s standalone
  capability-detected recording.
- Regression tests: whole-site scenarios that must stay quiet, plus the two
  hard honesty rules this skill is built around: never claim corroboration
  that wasn't checked, and never conflate "found nothing" with "found a
  different entity."

Run from the marketplace root: `python -m pytest tests/test_trust_freshness_audit.py`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "trust-freshness-audit" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _trust_util  # noqa: E402
import build_claim_table  # noqa: E402
import corroborate  # noqa: E402
import detect_trust  # noqa: E402

from lib.common.observations import make_observation  # noqa: E402

REPORT_SCHEMA = json.loads((ROOT / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
FINDING_SCHEMA = REPORT_SCHEMA["$defs"]["finding"]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def make_store(observations, archetype="brand-product", collected_at="2026-01-01T00:00:00Z"):
    return {
        "store_version": "1.0",
        "collected_at": collected_at,
        "target": {"audited_host": "example.com"},
        "capabilities": {},
        "archetype": archetype,
        "observations": observations,
    }


def fetch_obs(url, html, status_code=200, headers=None):
    value = {
        "status_code": status_code,
        "final_url": url,
        "redirect_chain": [],
        "headers": headers if headers is not None else {"Content-Type": "text/html; charset=utf-8"},
        "encoding": "utf-8",
        "elapsed_ms": 100,
        "evidence": {"status": "ok", "content_type": "text/html", "redirect_count": 0, "final_url": url},
        "html": html,
    }
    return make_observation("HTTP_FETCH", url, value)


def render_obs(url, html, status="ok"):
    value = {"url": url, "status": status, "reason": None, "final_url": url, "status_code": 200, "html": html, "evidence": {"status": status}}
    return make_observation("RENDER", url, value)


def classification_obs(url, page_type):
    return make_observation("PAGE_CLASSIFICATION", url, {"page_type": page_type})


def corroboration_obs(claim_id, performed, query="", sources=None, url="https://example.com/"):
    value = {
        "claim_id": claim_id,
        "performed": performed,
        "query": query,
        "method": "web_search",
        "timestamp": "2026-01-01T00:00:00Z",
        "sources": sources or [],
    }
    return make_observation("CLAIM_CORROBORATION", url, value)


def page_html(title="Acme", body="", jsonld=None, footer=""):
    head = f"<title>{title}</title>"
    if jsonld is not None:
        head += f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
    body_html = f"<h1>{title}</h1><p>{body}</p>"
    if footer:
        body_html += f"<footer>{footer}</footer>"
    return f"<html><head>{head}</head><body>{body_html}</body></html>"


def assert_finding_shape(finding):
    candidate = {"id": "F-001", **finding}
    jsonschema.validate(candidate, FINDING_SCHEMA)


def assert_evidence_binds(store, findings):
    known_ids = {obs["id"] for obs in store["observations"]}
    for finding in findings:
        for oid in finding["observation_ids"]:
            assert oid in known_ids, f"{finding['check_id']} cites unresolvable observation id {oid}"


def by_check(findings, check_id):
    return [f for f in findings if f["check_id"] == check_id]


ENTITY_PROFILE = {
    "fields": {
        "canonical_name": {"value": "Acme"},
        "entity_type": {"value": "company"},
    },
    "identity_anchor": {"same_as": ["https://linkedin.com/company/acme"]},
}


# ---------------------------------------------------------------------------
# Unit tests -- D-TRUST-01
# ---------------------------------------------------------------------------


def test_d_trust_01_fires_on_undated_time_sensitive_claim():
    html = page_html(body="Now available: our new pricing plan for all customers.")
    store = make_store([fetch_obs("https://example.com/pricing", html)])
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_01(store, table)
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_trust_01_never_fires_with_a_date_signal():
    html = page_html(
        body="Now available: our new pricing plan for all customers.",
        jsonld={"@type": "WebPage", "dateModified": "2026-01-01"},
    )
    store = make_store([fetch_obs("https://example.com/pricing", html)])
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_01(store, table)
    assert findings == []


def test_d_trust_01_never_fires_on_evergreen_content():
    html = page_html(body="Our product helps teams collaborate on shared documents.")
    store = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_01(store, table)
    assert findings == []


def test_d_trust_01_rethresholds_by_archetype():
    html = page_html(body="Now available: our new pricing plan for all customers.")

    publisher_store = make_store([fetch_obs("https://example.com/", html)], archetype="publisher-editorial")
    publisher_table = build_claim_table.build_claim_table(publisher_store)
    publisher_findings = detect_trust.check_d_trust_01(publisher_store, publisher_table)
    assert publisher_findings[0]["severity"] == "high"

    docs_store = make_store([fetch_obs("https://example.com/", html)], archetype="documentation")
    docs_table = build_claim_table.build_claim_table(docs_store)
    docs_findings = detect_trust.check_d_trust_01(docs_store, docs_table)
    assert docs_findings[0]["severity"] == "low"


# ---------------------------------------------------------------------------
# Unit tests -- D-TRUST-02
# ---------------------------------------------------------------------------


def test_d_trust_02_fires_on_past_dated_upcoming_event():
    html = page_html(body="Join us for our upcoming conference on January 5, 2020 in person.")
    store = make_store([fetch_obs("https://example.com/events", html)], collected_at="2026-01-01T00:00:00Z")
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_02(store, table)
    hits = [f for f in findings if "conference" in f["evidence"] or "dated event" in f["title"]]
    assert len(hits) == 1
    assert_finding_shape(hits[0])


def test_d_trust_02_never_fires_on_future_dated_event():
    html = page_html(body="Join us for our upcoming conference on January 5, 2030 in person.")
    store = make_store([fetch_obs("https://example.com/events", html)], collected_at="2026-01-01T00:00:00Z")
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_02(store, table)
    assert findings == []


def test_d_trust_02_copyright_alone_does_not_establish_staleness():
    html = page_html(body="Welcome to our site.", footer="© 2019 Acme Inc.")
    store = make_store([fetch_obs("https://example.com/", html)], collected_at="2026-01-01T00:00:00Z")
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_02(store, table)
    hits = [f for f in findings if "copyright" in f["title"].lower()]
    assert hits == []


@pytest.mark.parametrize("html", [
    '<a href="mailto:bonjour@example.org">Écrivez-nous</a>',
    '<a href="tel:+33123456789">Appelez</a>',
    '<form><input type="email"><textarea name="message"></textarea></form>',
    page_html(jsonld={"@graph": [{"@type": "https://schema.org/Organization", "name": "研究所"}]}),
])
def test_accountability_does_not_require_english_page_names(html):
    store = make_store([fetch_obs("https://example.com/資料/42", html)])
    assert detect_trust.check_d_trust_06(store, {}) == []


@pytest.mark.parametrize("path", ["/about-face", "/contact-lenses", "/products/contact-paper"])
def test_product_path_substrings_do_not_establish_accountability(path):
    store = make_store([fetch_obs("https://example.com" + path, page_html(body="Catalog item 12345678"))])
    findings = detect_trust.check_d_trust_06(store, {})
    assert len(findings) == 1
    assert "operator" in findings[0]["title"]


@pytest.mark.parametrize("html", [
    '<meta name="author" content="李明">',
    '<a rel="author" href="/people/42">Émilie Durand</a>',
    '<span itemprop="author">研究チーム</span>',
    page_html(jsonld={"@graph": [
        {"@type": "Article", "author": {"@id": "#writer"}},
        {"@id": "#writer", "@type": "Person", "name": "أمل"},
    ]}),
])
def test_author_signals_are_not_english_byline_specific(html):
    assert _trust_util.find_author_byline(html, "")


def test_empty_contact_and_author_links_are_not_named_channels():
    assert not _trust_util.has_contact_method('<a href="mailto:">Email</a><a href="tel:">Phone</a>')
    assert not _trust_util.has_contact_info("Order 123456789, copyright 2010-2026")
    assert not _trust_util.find_author_byline('<a rel="author" href="/people/42"></a>', "")


def test_author_findings_scope_only_anonymous_articles():
    named, anonymous = "https://example.com/a", "https://example.com/b"
    store = make_store([
        fetch_obs(named, '<meta name="author" content="李明">'),
        fetch_obs(anonymous, page_html(body="A substantive article.")),
        classification_obs(named, "article"), classification_obs(anonymous, "article"),
    ])
    hits = [f for f in detect_trust.check_d_trust_06(store, {}) if "author" in f["title"]]
    assert len(hits) == 1
    assert hits[0]["affected"] == {"count": 1, "sample_urls": [anonymous], "total_in_scope": 2}
    assert set(hits[0]["observation_ids"]) <= {obs["id"] for obs in store["observations"]}


def test_d_trust_02_never_fires_stale_copyright_when_a_recent_date_exists():
    html = page_html(
        body="Welcome to our site.",
        jsonld={"@type": "WebPage", "dateModified": "2026-01-01"},
        footer="© 2019 Acme Inc.",
    )
    store = make_store([fetch_obs("https://example.com/", html)], collected_at="2026-01-01T00:00:00Z")
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_02(store, table)
    assert [f for f in findings if "copyright" in f["title"].lower()] == []


# ---------------------------------------------------------------------------
# Unit tests -- D-TRUST-03
# ---------------------------------------------------------------------------


def test_d_trust_03_fires_on_conflicting_founded_year():
    a = page_html(body="Acme was founded in 2015 and has grown steadily since.")
    b = page_html(body="Acme was founded in 2018 by a small team of engineers.")
    store = make_store(
        [
            fetch_obs("https://example.com/about", a),
            fetch_obs("https://example.com/press", b),
        ]
    )
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_03(store, table)
    assert len(findings) == 1
    assert "founded_year" in findings[0]["title"]
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_trust_03_never_fires_on_matching_founded_year():
    a = page_html(body="Acme was founded in 2015 and has grown steadily since.")
    b = page_html(body="Acme was founded in 2015 by a small team of engineers.")
    store = make_store(
        [
            fetch_obs("https://example.com/about", a),
            fetch_obs("https://example.com/press", b),
        ]
    )
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_03(store, table)
    assert findings == []


def test_d_trust_03_never_extracts_price_as_a_comparable_claim():
    """Scope guardrail: price/spec facts must never become entity_fact claims
    at all -- they legitimately vary by product/plan/region on almost every
    commercial site (trust-checks.md D-TRUST-03 scope note)."""
    a = page_html(body="Our starter plan costs $99 per month.")
    b = page_html(body="Our enterprise plan costs $999 per month.")
    store = make_store(
        [
            fetch_obs("https://example.com/starter", a),
            fetch_obs("https://example.com/enterprise", b),
        ]
    )
    table = build_claim_table.build_claim_table(store)

    price_claims = [c for c in table["claims"] if c.get("key") == "price"]
    assert price_claims == []
    assert detect_trust.check_d_trust_03(store, table) == []


# ---------------------------------------------------------------------------
# Unit tests -- D-TRUST-04
# ---------------------------------------------------------------------------


def test_d_trust_04_fires_on_unattributed_superlative():
    html = page_html(body="We are the #1 leading provider in the industry today.")
    store = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_04(store, table)
    assert len(findings) == 1
    assert findings[0]["severity"] == "low"
    assert_finding_shape(findings[0])


def test_d_trust_04_never_fires_when_citation_is_nearby():
    html = page_html(body="According to a 2024 industry report, we are the #1 leading provider.")
    store = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_04(store, table)
    assert findings == []


def test_d_trust_04_never_matches_ordinary_adjectives():
    html = page_html(body="We provide a great, high-quality, amazing service.")
    store = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store)

    assert [c for c in table["claims"] if c["claim_type"] == "superlative_stat"] == []


# ---------------------------------------------------------------------------
# Unit tests -- D-TRUST-05
# ---------------------------------------------------------------------------


def test_d_trust_05_fires_when_no_sources_found():
    html = page_html(body="We are the #1 leading provider in the industry today.")
    store_no_corrob = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store_no_corrob)
    claim = next(c for c in table["claims"] if c["claim_type"] == "superlative_stat")

    store = make_store(
        [fetch_obs("https://example.com/", html), corroboration_obs(claim["id"], True, query=claim["text"], sources=[])]
    )
    findings = detect_trust.check_d_trust_05(store, table)
    assert len(findings) == 1
    assert "own site" in findings[0]["title"]
    assert_finding_shape(findings[0])


def test_d_trust_05_never_fires_without_a_real_corroboration_record():
    """Corroboration-honesty hard rule: no CLAIM_CORROBORATION observation at
    all must never be treated as 'not corroborated' -- it must be silent."""
    html = page_html(body="We are the #1 leading provider in the industry today.")
    store = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_05(store, table)
    assert findings == []


def test_d_trust_05_never_fires_when_a_genuine_match_exists():
    html = page_html(body="We are the #1 leading provider in the industry today.")
    store_probe = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store_probe)
    claim = next(c for c in table["claims"] if c["claim_type"] == "superlative_stat")

    sources = [{"url": "https://press.example/acme", "title": "Acme named #1 provider", "snippet": "Acme, a company, ...", "entity_match": True}]
    store = make_store(
        [fetch_obs("https://example.com/", html), corroboration_obs(claim["id"], True, sources=sources)]
    )
    findings = detect_trust.check_d_trust_05(store, table)
    assert findings == []


def test_d_trust_05_identity_confusion_reported_distinctly():
    """A source that mentions the queried name but is confirmed to be about a
    different entity must be reported as identity confusion, never conflated
    with 'nothing was found' (corroboration-honesty.md rule 6)."""
    html = page_html(body="We are the #1 leading provider in the industry today.")
    store_probe = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store_probe)
    claim = next(c for c in table["claims"] if c["claim_type"] == "superlative_stat")

    sources = [{"url": "https://unrelated.example/acme-rival", "title": "Acme Rival Corp news", "snippet": "unrelated content", "entity_match": False}]
    store = make_store(
        [fetch_obs("https://example.com/", html), corroboration_obs(claim["id"], True, sources=sources)]
    )
    findings = detect_trust.check_d_trust_05(store, table)
    assert len(findings) == 1
    assert "different entity" in findings[0]["title"]
    assert "different" in findings[0]["observed_signal"] or "unconfirmed" in findings[0]["observed_signal"]


# ---------------------------------------------------------------------------
# Unit tests -- D-TRUST-06
# ---------------------------------------------------------------------------


def test_d_trust_06_fires_when_no_about_or_contact_found():
    html = page_html(body="Welcome to our product.")
    store = make_store([fetch_obs("https://example.com/", html)])
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_06(store, table)
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_trust_06_never_fires_when_only_about_is_missing():
    html = page_html(body="Welcome to our product.")
    store = make_store(
        [
            fetch_obs("https://example.com/", html),
            fetch_obs("https://example.com/contact", page_html(body="Email us at hello@example.com.")),
        ]
    )
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_06(store, table)
    assert [f for f in findings if "about" in f["title"].lower()] == []


def test_d_trust_06_fires_on_articles_with_no_named_author():
    html = page_html(body="This is our latest blog post about industry trends.")
    store = make_store(
        [
            fetch_obs("https://example.com/blog/post-1", html),
            fetch_obs("https://example.com/about", page_html(body="About us.")),
            fetch_obs("https://example.com/contact", page_html(body="Email hello@example.com.")),
            classification_obs("https://example.com/blog/post-1", "article"),
        ]
    )
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_06(store, table)
    assert len(findings) == 1
    assert "author" in findings[0]["title"].lower()


def test_d_trust_06_never_fires_when_article_has_named_author():
    html = page_html(body="This article was written by Jane Smith for our readers.")
    store = make_store(
        [
            fetch_obs("https://example.com/blog/post-1", html),
            fetch_obs("https://example.com/about", page_html(body="About us.")),
            fetch_obs("https://example.com/contact", page_html(body="Email hello@example.com.")),
            classification_obs("https://example.com/blog/post-1", "article"),
        ]
    )
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_06(store, table)
    assert findings == []


def test_d_trust_06_never_fires_on_personal_portfolio_archetype():
    html = page_html(body="Welcome to my personal site.")
    store = make_store([fetch_obs("https://example.com/", html)], archetype="personal-portfolio")
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_06(store, table)
    assert findings == []


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_integration_detect_trust_builds_claim_table_internally_when_omitted():
    html = page_html(body="Now available: our new pricing plan for all customers.")
    store = make_store([fetch_obs("https://example.com/", html)])

    findings_no_table = detect_trust.detect_trust(store)
    table = build_claim_table.build_claim_table(store)
    findings_with_table = detect_trust.detect_trust(store, table)

    assert findings_no_table == findings_with_table
    assert by_check(findings_no_table, "D-TRUST-01")


def test_integration_cli_two_stage_matches_single_stage(tmp_path):
    html = page_html(body="Now available: our new pricing plan for all customers.")
    store = make_store([fetch_obs("https://example.com/", html)])
    store_path = tmp_path / "store.json"
    store_path.write_text(json.dumps(store), encoding="utf-8")

    table_path = tmp_path / "claims.json"
    build_result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "build_claim_table.py"), "--store", str(store_path), "--out", str(table_path)],
        capture_output=True,
        text=True,
    )
    assert build_result.returncode == 0, build_result.stderr

    two_stage = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "detect_trust.py"), "--store", str(store_path), "--claim-table", str(table_path)],
        capture_output=True,
        text=True,
    )
    assert two_stage.returncode == 0, two_stage.stderr

    single_stage = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "detect_trust.py"), "--store", str(store_path)],
        capture_output=True,
        text=True,
    )
    assert single_stage.returncode == 0, single_stage.stderr

    assert json.loads(two_stage.stdout) == json.loads(single_stage.stdout)
    assert len(json.loads(two_stage.stdout)) >= 1


def test_integration_corroborate_cli_produces_honest_record_without_results(tmp_path):
    claim = {"id": "CLAIM-abc123", "text": "We are #1", "source_url": "https://example.com/"}
    claim_path = tmp_path / "claim.json"
    claim_path.write_text(json.dumps(claim), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "corroborate.py"), "--claim", str(claim_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    observation = json.loads(result.stdout)
    assert observation["value"]["performed"] is False
    assert observation["value"]["sources"] == []
    assert observation["value"]["reason"] == "SEARCH_UNAVAILABLE"


def test_integration_corroborate_cli_runs_entity_match_with_results(tmp_path):
    claim = {"id": "CLAIM-abc123", "text": "We are #1", "source_url": "https://example.com/"}
    claim_path = tmp_path / "claim.json"
    claim_path.write_text(json.dumps(claim), encoding="utf-8")

    results = [{"url": "https://linkedin.com/company/acme", "title": "Acme", "snippet": "Acme is a company."}]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(ENTITY_PROFILE), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "corroborate.py"),
            "--claim",
            str(claim_path),
            "--results",
            str(results_path),
            "--entity-profile",
            str(profile_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    observation = json.loads(result.stdout)
    assert observation["value"]["performed"] is True
    assert observation["value"]["sources"][0]["entity_match"] is True


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("archetype", ["brand-product", "ecommerce", "institutional"])
def test_regression_clean_site_yields_no_findings(archetype):
    home = page_html(
        title="Acme",
        body="Acme is a company that builds developer tools for small teams.",
        jsonld={"@type": "WebPage", "dateModified": "2026-01-01"},
    )
    about = page_html(title="Acme - About", body="Acme was founded in 2015 and is based in Springfield.")
    contact = page_html(title="Acme - Contact", body="Email us at hello@example.com or call 555-123-4567.")
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/about", about),
            fetch_obs("https://example.com/contact", contact),
        ],
        archetype=archetype,
    )

    findings = detect_trust.detect_trust(store)
    assert findings == []


def test_regression_corroboration_never_fabricated_without_a_record():
    """No CLAIM_CORROBORATION observation anywhere in the store must never
    produce a D-TRUST-05 finding, on a site with plenty of claims that would
    otherwise be checked."""
    html = page_html(body="We are the #1 leading provider. Acme was founded in 2015.")
    store = make_store([fetch_obs("https://example.com/", html)])

    findings = detect_trust.detect_trust(store)
    assert by_check(findings, "D-TRUST-05") == []


def test_regression_record_corroboration_distinguishes_unavailable_from_empty():
    """corroborate.py itself must never blur 'capability absent' with 'search
    ran and found nothing' -- these are different facts about what happened."""
    claim = {"id": "CLAIM-x", "text": "claim text", "source_url": "https://example.com/"}

    absent = corroborate.record_corroboration(claim, search_results=None)
    assert absent["value"]["performed"] is False

    ran_but_empty = corroborate.record_corroboration(claim, search_results=[])
    assert ran_but_empty["value"]["performed"] is True
    assert ran_but_empty["value"]["sources"] == []


# ---------------------------------------------------------------------------
# Hostile-review regression tests
# ---------------------------------------------------------------------------


def test_hostile_01_archival_article_about_past_event_never_flagged_stale():
    """A news/blog article published on or before the date of the event it
    describes was true when written -- an accurate historical record, not a
    stale claim. Confirmed false-positive: this used to fire D-TRUST-02."""
    html = page_html(
        title="Election Preview",
        body="Join us to discuss the upcoming election on November 3, 2020 and what it means.",
        jsonld={"@type": "Article", "datePublished": "2020-10-01"},
    )
    store = make_store([fetch_obs("https://example.com/blog/2020-election-preview", html)], collected_at="2026-01-01T00:00:00Z")
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_02(store, table)
    assert findings == []


def test_hostile_01b_republished_page_still_presenting_stale_event_still_fires():
    """Companion: a page recently updated/republished that still presents a
    long-past event as upcoming is a genuine currency bug and must still fire."""
    html = page_html(
        title="Election Preview",
        body="Join us to discuss the upcoming election on November 3, 2020 and what it means.",
        jsonld={"@type": "Article", "dateModified": "2025-12-01"},
    )
    store = make_store([fetch_obs("https://example.com/blog/stale", html)], collected_at="2026-01-01T00:00:00Z")
    table = build_claim_table.build_claim_table(store)

    findings = detect_trust.check_d_trust_02(store, table)
    assert len(findings) == 1


def test_hostile_02_phone_numbers_never_extracted_as_comparable_claims():
    """Sales and support lines are a near-universal, legitimate multi-number
    pattern -- phone must never be a D-TRUST-03 comparison key at all."""
    sales = page_html(title="Acme - Sales", body="Sales: call 555-100-2000 today.")
    support = page_html(title="Acme - Support", body="Support line: 555-900-8000 for help.")
    store = make_store(
        [
            fetch_obs("https://example.com/sales", sales),
            fetch_obs("https://example.com/support", support),
        ]
    )
    table = build_claim_table.build_claim_table(store)

    assert [c for c in table["claims"] if c.get("key") == "phone"] == []
    assert detect_trust.check_d_trust_03(store, table) == []


def test_hostile_03_disclaimer_disambiguation_never_scored_as_entity_match():
    """A source explicitly warning it is NOT the entity must never be treated
    as corroboration -- confirmed to invert the identity-confusion guard."""
    entity_profile = {
        "fields": {"canonical_name": {"value": "Acme"}, "entity_type": {"value": "company"}},
        "identity_anchor": {"same_as": []},
    }
    source = {
        "url": "https://unrelated.example/disambiguation",
        "title": "Acme is not affiliated with this company",
        "snippet": "This page clarifies that Acme is not the same company as our organization.",
    }
    assert _trust_util.source_matches_entity(source, entity_profile) is False


def test_hostile_03b_genuine_corroborating_source_still_matches():
    """Companion: the disambiguation guard must not blunt real corroboration."""
    entity_profile = {
        "fields": {"canonical_name": {"value": "Acme"}, "entity_type": {"value": "company"}},
        "identity_anchor": {"same_as": ["https://linkedin.com/company/acme"]},
    }
    source = {"url": "https://linkedin.com/company/acme", "title": "Acme - LinkedIn", "snippet": "Acme is a company on LinkedIn."}
    assert _trust_util.source_matches_entity(source, entity_profile) is True


def test_hostile_04_corroboration_worthiness_excludes_dateable_claims():
    """time_sensitive/dated_offer/dated_event claims need a date, not a
    second opinion -- corroborating them externally is an unnecessary lookup."""
    assert _trust_util.is_corroboration_worthy({"claim_type": "time_sensitive"}) is False
    assert _trust_util.is_corroboration_worthy({"claim_type": "dated_event"}) is False
    assert _trust_util.is_corroboration_worthy({"claim_type": "dated_offer"}) is False


def test_hostile_04b_corroboration_worthiness_includes_actionable_claims():
    """Companion: entity_fact and unattributed superlative claims are exactly
    what D-TRUST-05 can act on, and must remain corroboration candidates."""
    assert _trust_util.is_corroboration_worthy({"claim_type": "entity_fact", "key": "founded_year"}) is True
    assert _trust_util.is_corroboration_worthy({"claim_type": "superlative_stat", "attributed": False}) is True
    assert _trust_util.is_corroboration_worthy({"claim_type": "superlative_stat", "attributed": True}) is False


def test_hostile_04c_corroborate_cli_warns_but_still_records_unworthy_claim(tmp_path, capsys):
    """The selectivity rule is advisory, not a silent override -- an explicit
    request must still be honored (and honestly recorded), just flagged."""
    claim = {"id": "CLAIM-x", "claim_type": "time_sensitive", "text": "now available", "source_url": "https://example.com/"}
    claim_path = tmp_path / "claim.json"
    claim_path.write_text(json.dumps(claim), encoding="utf-8")

    results = [{"url": "https://example.com/press", "title": "press", "snippet": "..."}]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "corroborate.py"), "--claim", str(claim_path), "--results", str(results_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "likely unnecessary" in result.stderr
    observation = json.loads(result.stdout)
    assert observation["value"]["performed"] is True
