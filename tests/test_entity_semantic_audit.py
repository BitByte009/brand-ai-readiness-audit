"""Tests for the entity-semantic-audit skill.

Four kinds, in order below:
- Unit tests: one check function at a time, against a hand-built store + a
  directly-built entity_profile.
- Integration tests: the full `build_entity_profile.py` -> `detect_entity.py`
  pipeline, including the two-script CLI contract (profile built standalone,
  then passed in, must match building it internally).
- Regression tests: whole-site scenarios that must stay quiet (a clean site
  across archetypes; an archetype-suppressed weak-signal site) -- these guard
  against a future code change accidentally reintroducing an absence-only flag.
- Adversarial regression tests: reproduce each bug found by the hostile review
  (see the review write-up) as a failing-before/passing-after case, paired with
  a "must still fire" companion so the fix doesn't just suppress everything.

Run from the marketplace root: `python -m pytest tests/test_entity_semantic_audit.py`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "entity-semantic-audit" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _entity_util  # noqa: E402
import _entity_util as _util  # noqa: E402
import build_entity_profile  # noqa: E402
import detect_entity  # noqa: E402

from lib.common.observations import make_observation  # noqa: E402

REPORT_SCHEMA = json.loads((ROOT / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
FINDING_SCHEMA = REPORT_SCHEMA["$defs"]["finding"]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def make_store(observations, archetype="brand-product", target=None):
    return {
        "store_version": "1.0",
        "collected_at": "2026-01-01T00:00:00Z",
        "target": target or {"audited_host": "example.com"},
        "capabilities": {},
        "archetype": archetype,
        "observations": observations,
    }


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


def render_obs(url, html, status="ok"):
    value = {"url": url, "status": status, "reason": None, "final_url": url, "status_code": 200, "html": html, "evidence": {"status": status}}
    return make_observation("RENDER", url, value)


def probe_obs(url, questions):
    return make_observation("PROBE", url, {"questions": questions, "source_text_hash": "deadbeef"})


def identity_q(question_id, answered, answer=None):
    return {"id": question_id, "category": "identity", "answered": answered, "answer": answer}


def corroboration_obs(performed, query="", matches=None, url="https://example.com/#corroboration"):
    value = {"performed": performed, "query": query, "matches": matches or [], "timestamp": "2026-01-01T00:00:00Z"}
    return make_observation("CORROBORATION", url, value)


def page_html(title="", h1="", description="", jsonld=None, footer="", extra_body=""):
    head = f"<title>{title}</title>"
    if description:
        head += f'<meta name="description" content="{description}">'
    if jsonld is not None:
        head += f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
    body = f"<h1>{h1}</h1>" if h1 else ""
    body += extra_body
    if footer:
        body += f"<footer>{footer}</footer>"
    return f"<html><head>{head}</head><body>{body}</body></html>"


def org_node(name="Acme", description=None, address=None, same_as=None, url=None, node_type="Organization"):
    node = {"@context": "https://schema.org", "@type": node_type, "name": name}
    if description:
        node["description"] = description
    if address:
        node["address"] = address
    if same_as:
        node["sameAs"] = same_as
    if url:
        node["url"] = url
    return node


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


# ---------------------------------------------------------------------------
# Unit tests -- D-ENTITY-01
# ---------------------------------------------------------------------------


def test_normalize_name_merges_legal_suffix_variants():
    assert _util.normalize_name("Acme Inc.") == _util.normalize_name("Acme")
    assert _util.normalize_name("Acme, LLC") == _util.normalize_name("Acme")


def test_d_entity_01_fires_on_zero_name_candidates():
    html = page_html(title="", h1="")
    store = make_store([fetch_obs("https://example.com/", html)])
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_01(store, profile)
    assert len(findings) == 1
    assert "No canonical entity name found" in findings[0]["title"]
    assert findings[0]["severity"] == "high"
    assert_finding_shape(findings[0])


def test_d_entity_01_fires_on_inconsistent_names():
    store = make_store(
        [
            fetch_obs("https://example.com/a1", page_html(title="Acme")),
            fetch_obs("https://example.com/a2", page_html(title="Acme")),
            fetch_obs("https://example.com/b1", page_html(title="Zenith")),
            fetch_obs("https://example.com/b2", page_html(title="Zenith")),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_01(store, profile)
    assert len(findings) == 1
    assert "consistently" in findings[0]["title"]
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_entity_01_never_fires_with_dominant_name_and_legal_suffix_variant():
    store = make_store(
        [
            fetch_obs("https://example.com/a", page_html(title="Acme")),
            fetch_obs("https://example.com/b", page_html(title="Acme")),
            fetch_obs("https://example.com/c", page_html(title="Acme")),
            fetch_obs("https://example.com/d", page_html(title="Acme", footer="© 2026 Acme Inc.")),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_01(store, profile)
    assert findings == []


# ---------------------------------------------------------------------------
# Unit tests -- D-ENTITY-02
# ---------------------------------------------------------------------------


def test_d_entity_02_fires_when_type_never_stated():
    store = make_store([fetch_obs("https://example.com/", page_html(title="Acme"))])
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_02(store, profile)
    assert len(findings) == 1
    assert findings[0]["confidence"] == "medium"  # no probe to corroborate
    assert_finding_shape(findings[0])


def test_d_entity_02_fires_with_high_confidence_when_probe_corroborates():
    url = "https://example.com/"
    store = make_store(
        [
            fetch_obs(url, page_html(title="Acme")),
            probe_obs(url, [identity_q("Q2", False)]),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_02(store, profile)
    assert len(findings) == 1
    assert findings[0]["confidence"] == "high"


def test_d_entity_02_never_fires_when_type_word_present():
    html = page_html(title="Acme", extra_body="<p>Acme is a company that builds tools.</p>")
    store = make_store([fetch_obs("https://example.com/", html)])
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_02(store, profile)
    assert findings == []


# ---------------------------------------------------------------------------
# Unit tests -- D-ENTITY-03
# ---------------------------------------------------------------------------


def test_d_entity_03_fires_on_confirmed_collision_with_no_distinguisher():
    store = make_store(
        [
            fetch_obs("https://example.com/", page_html(title="Acme")),
            corroboration_obs(
                True,
                query="Acme",
                matches=[
                    {"name": "Acme", "source_url": "https://acme-other.example/", "category": "organization"},
                    {"name": "Acme", "source_url": "https://acme-third.example/", "category": "organization"},
                ],
            ),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_03(store, profile)
    assert len(findings) == 1
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_entity_03_never_fires_without_corroboration_record():
    store = make_store([fetch_obs("https://example.com/", page_html(title="Acme"))])
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_03(store, profile)
    assert findings == []


def test_d_entity_03_never_fires_when_a_distinguisher_is_present():
    html = page_html(title="Acme", extra_body="<p>Acme is a company that builds tools.</p>")
    store = make_store(
        [
            fetch_obs("https://example.com/", html),
            corroboration_obs(
                True,
                query="Acme",
                matches=[
                    {"name": "Acme", "source_url": "https://acme-other.example/", "category": "organization"},
                    {"name": "Acme", "source_url": "https://acme-third.example/", "category": "organization"},
                ],
            ),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_03(store, profile)
    assert findings == []


# ---------------------------------------------------------------------------
# Unit tests -- D-ENTITY-04
# ---------------------------------------------------------------------------


def test_d_entity_04_fires_on_conflicting_entity_level_descriptions():
    home = page_html(title="Acme", description="Acme builds developer tools for small teams.")
    about = page_html(title="Acme", description="Quarterly financial results and investor relations updates.")
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/about", about),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_04(store, profile)
    hits = [f for f in findings if "description" in f["title"]]
    assert len(hits) == 1
    assert_finding_shape(hits[0])
    assert_evidence_binds(store, hits)


def test_d_entity_04_never_fires_on_different_product_page_descriptions():
    a = page_html(title="Acme", description="The Widget Pro is a compact tool for cutting steel.")
    b = page_html(title="Acme", description="The Gadget Mini is a lightweight tool for home repairs.")
    store = make_store(
        [
            fetch_obs("https://example.com/product/widget", a),
            fetch_obs("https://example.com/product/gadget", b),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_04(store, profile)
    assert findings == []


def test_d_entity_04_fires_on_conflicting_address_with_no_branch_label():
    node_a = org_node(address={"streetAddress": "1 Main St", "addressLocality": "Springfield", "postalCode": "11111"})
    node_b = org_node(address={"streetAddress": "2 Other Rd", "addressLocality": "Shelbyville", "postalCode": "22222"})
    store = make_store(
        [
            fetch_obs("https://example.com/", page_html(title="Acme", jsonld=node_a)),
            fetch_obs("https://example.com/contact", page_html(title="Acme", jsonld=node_b)),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_04(store, profile)
    hits = [f for f in findings if "address" in f["title"]]
    assert len(hits) == 1
    assert_finding_shape(hits[0])


def test_d_entity_04_never_fires_on_distinctly_named_multi_location_addresses():
    node_a = org_node(
        name="Acme Downtown", address={"streetAddress": "1 Main St", "addressLocality": "Springfield", "postalCode": "11111"}
    )
    node_b = org_node(
        name="Acme Uptown", address={"streetAddress": "2 Other Rd", "addressLocality": "Shelbyville", "postalCode": "22222"}
    )
    store = make_store(
        [
            fetch_obs("https://example.com/downtown", page_html(title="Acme", jsonld=node_a)),
            fetch_obs("https://example.com/uptown", page_html(title="Acme", jsonld=node_b)),
        ]
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_04(store, profile)
    assert [f for f in findings if "address" in f["title"]] == []


# ---------------------------------------------------------------------------
# Unit tests -- D-ENTITY-05
# ---------------------------------------------------------------------------


def test_d_entity_05_fires_only_when_compounded_with_sibling_failure():
    store = make_store([fetch_obs("https://example.com/", page_html(title="", h1=""))])
    profile = build_entity_profile.build_entity_profile(store)

    d01 = detect_entity.check_d_entity_01(store, profile)
    assert d01  # sibling did fire

    findings = detect_entity.check_d_entity_05(store, profile, sibling_fired=True)
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_entity_05_never_fires_standalone():
    html = page_html(title="Acme", extra_body="<p>Acme is a company that builds tools.</p>")
    store = make_store([fetch_obs("https://example.com/", html)])
    profile = build_entity_profile.build_entity_profile(store)

    # name is a single consistent candidate and type is stated -> no sibling failure
    d01 = detect_entity.check_d_entity_01(store, profile)
    d02 = detect_entity.check_d_entity_02(store, profile)
    assert not d01 and not d02

    findings = detect_entity.check_d_entity_05(store, profile, sibling_fired=False)
    assert findings == []


def test_d_entity_05_never_fires_when_anchor_present():
    node = org_node(same_as=["https://linkedin.com/company/acme"])
    store = make_store([fetch_obs("https://example.com/", page_html(title="", h1="", jsonld=node))])
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_05(store, profile, sibling_fired=True)
    assert findings == []


# ---------------------------------------------------------------------------
# Unit tests -- D-ENTITY-06
# ---------------------------------------------------------------------------


def test_d_entity_06_fires_when_offering_unclear_on_brand_product():
    home = page_html(title="Acme", extra_body='<a href="/contact">Contact</a>')
    contact = page_html(title="Acme - Contact")
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/contact", contact),
        ],
        archetype="brand-product",
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_06(store, profile)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert_finding_shape(findings[0])


def test_d_entity_06_never_fires_when_offering_stated_one_click_away():
    home = page_html(title="Acme", extra_body='<a href="/services">Services</a>')
    services = page_html(title="Services", extra_body="<p>We provide consulting services for small teams.</p>")
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/services", services),
        ],
        archetype="brand-product",
    )
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_06(store, profile)
    assert findings == []


def test_d_entity_06_never_fires_on_suppressed_archetype():
    home = page_html(title="Docs Home")
    store = make_store([fetch_obs("https://example.com/", home)], archetype="documentation")
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_06(store, profile)
    assert findings == []


def test_d_entity_06_rethresholded_on_publisher_editorial():
    home = page_html(title="The Daily Post")
    store = make_store([fetch_obs("https://example.com/", home)], archetype="publisher-editorial")
    profile = build_entity_profile.build_entity_profile(store)

    findings = detect_entity.check_d_entity_06(store, profile)
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert findings[0]["confidence"] == "medium"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_integration_detect_entity_builds_profile_internally_when_omitted():
    store = make_store([fetch_obs("https://example.com/", page_html(title="", h1=""))])

    findings_no_profile = detect_entity.detect_entity(store)
    profile = build_entity_profile.build_entity_profile(store)
    findings_with_profile = detect_entity.detect_entity(store, profile)

    assert findings_no_profile == findings_with_profile
    assert by_check(findings_no_profile, "D-ENTITY-01")


def test_integration_entity_profile_reads_graph_identity_node_with_type_uri():
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "https://schema.org/Organization",
                "name": "Northstar Instruments",
                "url": "https://example.com/",
            }
        ],
    }
    store = make_store(
        [fetch_obs("https://example.com/", page_html(jsonld=graph))]
    )

    profile = build_entity_profile.build_entity_profile(store)

    assert profile["fields"]["canonical_name"]["value"] == "Northstar Instruments"
    assert profile["identity_anchor"]["self_url"] == "https://example.com/"


def test_integration_multi_check_pipeline_on_realistic_site():
    home = page_html(
        title="Acme",
        h1="Acme",
        description="Acme builds developer tools for small teams.",
        jsonld=org_node(description="Acme builds developer tools for small teams."),
        extra_body='<a href="/about">About</a> <a href="/pricing">Pricing</a>',
    )
    about = page_html(
        title="Zenith",  # inconsistent name candidate
        h1="Zenith",
        jsonld=org_node(name="Zenith"),  # explicit conflicting entity, not just a page topic
        description="Quarterly financial results and investor relations updates.",  # conflicting description
    )
    pricing = page_html(title="Acme - Pricing", extra_body="<p>We offer three subscription plans.</p>")

    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/about", about),
            fetch_obs("https://example.com/pricing", pricing),
        ]
    )

    profile = build_entity_profile.build_entity_profile(store)
    findings = detect_entity.detect_entity(store, profile)

    fired_checks = {f["check_id"] for f in findings}
    assert "D-ENTITY-01" in fired_checks  # Acme vs Zenith, no dominant share
    assert "D-ENTITY-04" in fired_checks  # conflicting entity-level descriptions
    assert "D-ENTITY-06" not in fired_checks  # pricing page (depth-1) states the offering

    for finding in findings:
        assert_finding_shape(finding)
    assert_evidence_binds(store, findings)


def test_integration_cli_two_stage_matches_single_stage(tmp_path):
    store = make_store(
        [
            fetch_obs("https://example.com/", page_html(title="", h1="")),
        ]
    )
    store_path = tmp_path / "store.json"
    store_path.write_text(json.dumps(store), encoding="utf-8")

    profile_path = tmp_path / "profile.json"
    build_result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "build_entity_profile.py"), "--store", str(store_path), "--out", str(profile_path)],
        capture_output=True,
        text=True,
    )
    assert build_result.returncode == 0, build_result.stderr

    two_stage = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "detect_entity.py"),
            "--store",
            str(store_path),
            "--profile",
            str(profile_path),
        ],
        capture_output=True,
        text=True,
    )
    assert two_stage.returncode == 0, two_stage.stderr

    single_stage = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "detect_entity.py"), "--store", str(store_path)],
        capture_output=True,
        text=True,
    )
    assert single_stage.returncode == 0, single_stage.stderr

    assert json.loads(two_stage.stdout) == json.loads(single_stage.stdout)
    assert len(json.loads(two_stage.stdout)) >= 1


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("archetype", ["brand-product", "institutional", "ecommerce"])
def test_regression_clean_unambiguous_site_yields_no_findings(archetype):
    node = org_node(
        description="Acme is a company that builds developer tools for small teams.",
        address={"streetAddress": "1 Main St", "addressLocality": "Springfield", "postalCode": "11111"},
        same_as=["https://linkedin.com/company/acme"],
        url="https://example.com/",
    )
    home = page_html(
        title="Acme",
        h1="Acme",
        description="Acme is a company that builds developer tools for small teams.",
        jsonld=node,
        extra_body='<p>Acme is a company. We build developer tools for small teams.</p> <a href="/about">About</a>',
    )
    about = page_html(
        title="Acme - About",
        h1="About Acme",
        description="Acme is a company that builds developer tools for small teams.",
        footer="© 2026 Acme Inc.",
    )
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/about", about),
        ],
        archetype=archetype,
    )

    findings = detect_entity.detect_entity(store)
    assert findings == []


def test_regression_archetype_suppression_holds_on_weak_signal_documentation_site():
    """A documentation site with genuinely no offering statement anywhere must
    still never fire D-ENTITY-06 -- guards against a future regression that
    drops the archetype gate and starts treating absence alone as a defect."""
    home = page_html(title="Project Docs", h1="Project Docs")
    guide = page_html(title="Getting Started", h1="Getting Started")
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/guide", guide),
        ],
        archetype="documentation",
    )

    findings = detect_entity.detect_entity(store)
    assert by_check(findings, "D-ENTITY-06") == []


# ---------------------------------------------------------------------------
# Adversarial regression tests (hostile review)
# ---------------------------------------------------------------------------


def test_hostile_01_render_lens_prevents_false_no_name_finding():
    """A JS-rendered site: raw HTML is an empty shell, the brand name only
    exists in the rendered DOM. Before the fix, this skill read HTTP_FETCH
    only and reported 'no canonical entity name found anywhere' -- a false
    positive on a large and common class of real sites."""
    raw_shell = '<html><head><title></title></head><body><div id="root"></div></body></html>'
    rendered = page_html(title="Acme", h1="Acme")
    store = make_store(
        [
            fetch_obs("https://example.com/", raw_shell),
            render_obs("https://example.com/", rendered),
        ]
    )

    findings = detect_entity.detect_entity(store)
    assert by_check(findings, "D-ENTITY-01") == []


def test_hostile_01b_render_lens_still_fires_when_render_unavailable():
    """Companion: when no usable render exists, raw HTML is still the best
    evidence available and the check must still work off it."""
    store = make_store(
        [
            fetch_obs("https://example.com/", "<html><head><title></title></head><body></body></html>"),
            render_obs("https://example.com/", "", status="unavailable"),
        ]
    )

    findings = detect_entity.detect_entity(store)
    assert by_check(findings, "D-ENTITY-01") != []


def test_hostile_02_legal_trading_name_pair_never_fires_on_small_site():
    """A completely ordinary pattern: marketing name 'Zephyr' in title/h1, the
    registered legal name only in JSON-LD Organization.name. On a 1-page site
    this used to break the 70% dominance floor and false-positive."""
    node = org_node(name="Acme Holdings LLC")
    html = page_html(title="Zephyr", h1="Zephyr", jsonld=node)
    store = make_store([fetch_obs("https://example.com/", html)])

    findings = detect_entity.detect_entity(store)
    assert by_check(findings, "D-ENTITY-01") == []


def test_hostile_02b_genuine_two_name_conflict_still_fires():
    """Companion: the legal/trading-name suppression must not swallow a real
    conflict where the minority name is ALSO public-facing (title/h1), not
    confined to the legal register."""
    store = make_store(
        [
            fetch_obs("https://example.com/a", page_html(title="Acme")),
            fetch_obs("https://example.com/b", page_html(title="Zenith")),
        ]
    )

    findings = detect_entity.detect_entity(store)
    assert by_check(findings, "D-ENTITY-01") != []


def test_hostile_03_address_abbreviation_never_fires():
    """'123 Main St' vs. '123 Main Street' is the same real address written
    two conventional ways -- extremely common across a site's own pages."""
    node_a = org_node(address={"streetAddress": "123 Main St", "addressLocality": "Springfield", "postalCode": "11111"})
    node_b = org_node(address={"streetAddress": "123 Main Street", "addressLocality": "Springfield", "postalCode": "11111"})
    store = make_store(
        [
            fetch_obs("https://example.com/", page_html(title="Acme", jsonld=node_a)),
            fetch_obs("https://example.com/contact", page_html(title="Acme", jsonld=node_b)),
        ]
    )

    findings = detect_entity.detect_entity(store)
    assert by_check(findings, "D-ENTITY-04") == []


def test_hostile_03b_genuinely_different_address_still_fires():
    """Companion: a real address conflict (different street and city) must
    still be caught after normalizing abbreviations."""
    node_a = org_node(address={"streetAddress": "1 Main St", "addressLocality": "Springfield", "postalCode": "11111"})
    node_b = org_node(address={"streetAddress": "99 Other Ave", "addressLocality": "Shelbyville", "postalCode": "22222"})
    store = make_store(
        [
            fetch_obs("https://example.com/", page_html(title="Acme", jsonld=node_a)),
            fetch_obs("https://example.com/contact", page_html(title="Acme", jsonld=node_b)),
        ]
    )

    findings = detect_entity.detect_entity(store)
    assert by_check(findings, "D-ENTITY-04") != []


def test_hostile_04_third_party_copyright_outside_footer_is_ignored():
    """A photo credit's copyright notice anywhere on the page must never be
    read as the site's own footer attribution -- it isn't inside a <footer>."""
    html = (
        '<html><head><title>Acme</title></head><body>'
        '<h1>Acme</h1><p class="credit">Photo © 2024 Getty Images</p>'
        '</body></html>'
    )
    assert _entity_util.footer_copyright_name(html) is None


def test_hostile_04b_real_footer_copyright_still_captured():
    """Companion: a genuine <footer> copyright line must still be read."""
    html = "<html><body><footer>© 2026 Acme Inc.</footer></body></html>"
    assert _entity_util.footer_copyright_name(html) == "Acme Inc"


def test_hostile_05_short_tagline_vs_detailed_blurb_never_fires():
    """A short homepage tagline that is a near-verbatim prefix of a longer,
    fully consistent about-page blurb must not be scored as a conflict just
    because SequenceMatcher penalizes the length difference."""
    home = page_html(title="Acme", description="Acme builds developer tools for small teams.")
    about = page_html(
        title="Acme",
        description=(
            "Acme builds developer tools for small teams. Founded in 2020, Acme is "
            "trusted by over 500 engineering teams worldwide to ship faster with "
            "better tooling, CI integration, and observability built in from day one."
        ),
    )
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/about", about),
        ]
    )

    findings = detect_entity.detect_entity(store)
    assert [f for f in findings if f["check_id"] == "D-ENTITY-04" and "description" in f["title"]] == []


def test_hostile_05b_genuinely_unrelated_descriptions_still_fire():
    """Companion: re-asserted here with the updated similarity function to be
    explicit that the fix doesn't blunt real conflict detection."""
    home = page_html(title="Acme", description="Acme builds developer tools for small teams.")
    about = page_html(title="Acme", description="Quarterly financial results and investor relations updates.")
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/about", about),
        ]
    )

    findings = detect_entity.detect_entity(store)
    assert [f for f in findings if f["check_id"] == "D-ENTITY-04" and "description" in f["title"]] != []


def test_hostile_06_educational_organization_never_labeled_university():
    """A coding bootcamp or K-12 school typed EducationalOrganization must not
    be mischaracterized as literally 'university' -- a fact the site never
    stated, propagated into entity_profile for downstream skills."""
    assert _entity_util.TYPE_LABEL_MAP["EducationalOrganization"] != "university"
    assert _entity_util.TYPE_LABEL_MAP["EducationalOrganization"] == "educational institution"


def test_hostile_07_personal_portfolio_name_absence_is_downgraded():
    """archetype-applicability.md declares D-ENTITY-01 RETHR for
    personal-portfolio; the check must actually honor that, not just document
    it -- a sparse personal/link-in-bio site is not a high-severity defect."""
    store = make_store(
        [fetch_obs("https://example.com/", "<html><head><title></title></head><body></body></html>")],
        archetype="personal-portfolio",
    )

    findings = detect_entity.check_d_entity_01(store, build_entity_profile.build_entity_profile(store))
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"


def test_hostile_07b_brand_product_name_absence_stays_high_severity():
    """Companion: the downgrade must be archetype-specific, not global."""
    store = make_store(
        [fetch_obs("https://example.com/", "<html><head><title></title></head><body></body></html>")],
        archetype="brand-product",
    )

    findings = detect_entity.check_d_entity_01(store, build_entity_profile.build_entity_profile(store))
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_hostile_07c_personal_portfolio_type_absence_is_downgraded():
    store = make_store(
        [fetch_obs("https://example.com/", page_html(title="Jane Doe"))],
        archetype="personal-portfolio",
    )

    findings = detect_entity.check_d_entity_02(store, build_entity_profile.build_entity_profile(store))
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert findings[0]["confidence"] == "low"  # medium (no probe) downgraded once more


# ---------------------------------------------------------------------------
# Structured identity authority (D-ENTITY-01/04) and conservative aliases
# ---------------------------------------------------------------------------
#
# A page title is a document label; an Organization node's `name` is an entity
# declaration. Authority is earned by five conditions, and each test below
# removes exactly one of them.

import build_entity_profile as _bep

ORG = '{"@context":"https://schema.org","@type":"Organization","name":"Meridian Bearings",%s"description":"An industrial bearing supplier."}'


def _page(url, title, jsonld=ORG % "", body="Meridian Bearings supplies industrial bearings to machine shops.", desc=None):
    meta = f'<meta name="description" content="{desc}">' if desc else ""
    script = f'<script type="application/ld+json">{jsonld}</script>' if jsonld else ""
    html = f"<html><head><title>{title}</title>{meta}{script}</head><body><h1>{title}</h1><p>{body}</p></body></html>"
    return make_observation("HTTP_FETCH", url, {"html": html, "status_code": 200, "final_url": url})


def _profile(observations):
    return _bep.build_entity_profile({"observations": observations, "archetype": "brand-product",
                                      "target": {"audited_host": "example.com"}})


SITE = ["https://example.com/", "https://example.com/support", "https://example.com/pricing"]
TITLES = ["Meridian Bearings", "Support - Meridian Bearings", "Pricing - Meridian Bearings"]


# -- A: identical valid Organization markup across pages --------------------

def test_consistent_structured_identity_outranks_per_page_titles():
    profile = _profile([_page(u, t) for u, t in zip(SITE, TITLES)])
    name = profile["fields"]["canonical_name"]
    assert name["value"] == "Meridian Bearings"
    assert name["consistent"] is True
    assert name["determined_by"] == "structured_identity"
    assert name["candidates"], "the observed candidates are still carried as evidence"
    assert detect_entity.check_d_entity_01({"observations": []}, profile) == []


def test_per_page_meta_descriptions_are_not_conflicting_entity_descriptions():
    # Distinct per-page descriptions are correct practice, not a contradiction.
    observations = [_page(u, t, desc=d) for u, t, d in zip(
        SITE, TITLES,
        ["Meridian Bearings supplies precision bearings to Nordic machine shops.",
         "Answers about stock ranges, dispatch times and returns.",
         "Trade pricing, volume discounts and payment terms."])]
    profile = _profile(observations)
    assert detect_entity.check_d_entity_04({"observations": []}, profile) == []


# -- B: markup that contradicts the visible site keeps reporting ------------

def test_structured_identity_invisible_on_the_page_earns_no_authority():
    invisible = (ORG % "").replace("Meridian Bearings", "Completely Different Holdings")
    observations = [_page(u, t, jsonld=invisible) for u, t in zip(SITE, TITLES)]
    assert _bep._structured_identity(_bep.effective_pages({"observations": observations})) is None


# -- C: markup on one page is not a sitewide claim ---------------------------

def test_structured_identity_on_a_single_page_is_not_sitewide_truth():
    observations = [_page(SITE[0], TITLES[0])] + [_page(u, t, jsonld=None) for u, t in zip(SITE[1:], TITLES[1:])]
    assert _bep._structured_identity(_bep.effective_pages({"observations": observations})) is None


# -- D: malformed or nameless markup earns nothing ---------------------------

@pytest.mark.parametrize("jsonld,reason", [
    ("{not valid json", "unparseable"),
    ('{"@context":"https://schema.org","@type":"Organization"}', "no name property"),
    ('{"@context":"https://schema.org","@type":"Organization","name":"   "}', "blank name"),
], ids=["unparseable", "nameless", "blank"])
def test_malformed_structured_identity_earns_no_authority(jsonld, reason):
    observations = [_page(u, t, jsonld=jsonld) for u, t in zip(SITE, TITLES)]
    assert _bep._structured_identity(_bep.effective_pages({"observations": observations})) is None, reason


# -- E: competing organizations are never resolved arbitrarily --------------

def test_two_competing_organizations_are_not_arbitrarily_resolved():
    other = (ORG % "").replace("Meridian Bearings", "Nordic Bearings Group")
    observations = [_page(SITE[0], TITLES[0]), _page(SITE[1], TITLES[1], jsonld=other),
                    _page(SITE[2], TITLES[2])]
    assert _bep._structured_identity(_bep.effective_pages({"observations": observations})) is None


def test_a_third_party_node_pointing_at_another_site_is_not_adopted():
    foreign = ORG % '"url":"https://payments.vendor.example/",'
    observations = [_page(u, t, jsonld=foreign) for u, t in zip(SITE, TITLES)]
    assert _bep._structured_identity(_bep.effective_pages({"observations": observations})) is None


def test_the_www_spelling_of_the_same_site_is_not_treated_as_foreign():
    same = ORG % '"url":"https://www.example.com/",'
    observations = [_page(u, t, jsonld=same) for u, t in zip(SITE, TITLES)]
    assert _bep._structured_identity(_bep.effective_pages({"observations": observations})) is not None


# -- F: non-organization markup does not establish identity -----------------

@pytest.mark.parametrize("node_type", ["Product", "Article", "WebPage", "BreadcrumbList"])
def test_non_identity_markup_does_not_satisfy_entity_identity(node_type):
    node = '{"@context":"https://schema.org","@type":"%s","name":"Meridian Bearings"}' % node_type
    observations = [_page(u, t, jsonld=node) for u, t in zip(SITE, TITLES)]
    assert _bep._structured_identity(_bep.effective_pages({"observations": observations})) is None


# -- G: non-ASCII entity names behave identically ---------------------------

def test_structured_identity_authority_holds_for_non_ascii_names():
    greek = '{"@context":"https://schema.org","@type":"Organization","name":"Μερίντιαν Ρουλεμάν"}'
    titles = ["Μερίντιαν Ρουλεμάν", "Υποστήριξη - Μερίντιαν Ρουλεμάν", "Τιμές - Μερίντιαν Ρουλεμάν"]
    observations = [_page(u, t, jsonld=greek, body="Η Μερίντιαν Ρουλεμάν πουλάει ρουλεμάν ακριβείας.")
                    for u, t in zip(SITE, titles)]
    profile = _profile(observations)
    assert profile["fields"]["canonical_name"]["value"] == "Μερίντιαν Ρουλεμάν"
    assert profile["fields"]["canonical_name"]["determined_by"] == "structured_identity"


# -- aliases -----------------------------------------------------------------

def test_a_single_page_title_does_not_become_a_sitewide_alias():
    profile = _profile([_page(u, t) for u, t in zip(SITE, TITLES)])
    aliases = (profile["fields"]["aliases"]["value"] or "")
    assert "Support" not in aliases and "Pricing" not in aliases


def test_a_name_repeated_across_pages_is_accepted_as_an_alias():
    # A trading name carried in the h1 of several pages is real alternate identity.
    observations = [_page(u, t, body="Meridian Bearings supplies bearings.") for u, t in zip(SITE, TITLES)]
    observations += [make_observation("HTTP_FETCH", u, {"html":
        f'<html><head><title>Meridian Nordic</title>{"<script type=\"application/ld+json\">" + (ORG % "") + "</script>"}</head>'
        "<body><h1>Meridian Nordic</h1><p>Meridian Bearings supplies bearings.</p></body></html>",
        "status_code": 200, "final_url": u}) for u in ("https://example.com/a", "https://example.com/b")]
    profile = _profile(observations)
    assert "Meridian Nordic" in (profile["fields"]["aliases"]["value"] or "")


def test_the_canonical_name_is_never_demoted_to_an_alias():
    profile = _profile([_page(u, t) for u, t in zip(SITE, TITLES)])
    assert profile["fields"]["canonical_name"]["value"] == "Meridian Bearings"
    assert "Meridian Bearings" not in (profile["fields"]["aliases"]["value"] or "")
