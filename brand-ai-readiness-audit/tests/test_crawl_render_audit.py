"""Tests for the crawl-render-audit skill's three detectors.

Run from the marketplace root: `python -m pytest tests/test_crawl_render_audit.py`.

The skill directory is hyphenated (`skills/crawl-render-audit`), which is not a
valid Python package path, so its `scripts/` directory is added to `sys.path`
directly -- exactly what each `detect_*.py` does for its own `_util` import.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "crawl-render-audit" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import detect_crawl  # noqa: E402
import detect_extract  # noqa: E402
import detect_render  # noqa: E402

from lib.common.observations import make_observation  # noqa: E402

REPORT_SCHEMA = json.loads((ROOT / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
FINDING_SCHEMA = REPORT_SCHEMA["$defs"]["finding"]

LOREM = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 10  # > 400 chars


# ---------------------------------------------------------------------------
# Fixture builders -- construct synthetic observation stores. No network, no
# dependency on lib/site_observer collection, per the project's offline-corpus
# testing philosophy (tests/fixtures/README.md).
# ---------------------------------------------------------------------------


def make_store(observations, target=None, capabilities=None, template_clusters=None):
    return {
        "store_version": "1.0",
        "collected_at": "2026-01-01T00:00:00Z",
        "target": target or {"audited_host": "example.com"},
        "capabilities": capabilities or {},
        "observations": observations,
        **({"template_clusters": template_clusters} if template_clusters else {}),
    }


def robots_obs(text, url="https://example.com/robots.txt"):
    from lib.common.robots import parse_robots

    parsed = parse_robots(text)
    return make_observation("ROBOTS", url, {"url": url, **parsed})


def broken_robots_obs(status, url="https://example.com/robots.txt"):
    return make_observation(
        "ROBOTS", url, {"url": url, "status": status, "allow_all": False, "document": {"groups": [], "sitemap": [], "rules": []}}
    )


def fetch_obs(
    url,
    html="",
    status_code=200,
    final_url=None,
    headers=None,
    redirect_chain=None,
    elapsed_ms=None,
):
    headers = headers if headers is not None else {"Content-Type": "text/html; charset=utf-8"}
    value = {
        "status_code": status_code,
        "final_url": final_url or url,
        "redirect_chain": redirect_chain or [],
        "headers": headers,
        "encoding": "utf-8",
        "elapsed_ms": elapsed_ms,
        "evidence": {
            "status": "ok" if status_code and status_code < 400 else "http_error",
            "content_type": headers.get("Content-Type"),
            "redirect_count": len(redirect_chain or []),
            "final_url": final_url or url,
        },
        "html": html,
    }
    return make_observation("HTTP_FETCH", url, value)


def render_obs(url, html, status="ok", status_code=200, final_url=None):
    value = {
        "url": url,
        "status": status,
        "reason": None,
        "final_url": final_url or url,
        "status_code": status_code,
        "html": html,
        "evidence": {"status": status},
    }
    return make_observation("RENDER", url, value)


def sitemap_obs(entries, status="ok", url="https://example.com/sitemap.xml"):
    return make_observation("SITEMAP", url, {"status": status, "entries": entries})


def classification_obs(url, page_type):
    return make_observation("PAGE_CLASSIFICATION", url, {"page_type": page_type})


def probe_obs(url, questions):
    return make_observation("PROBE", url, {"questions": questions, "source_text_hash": "deadbeef"})


def page(title="A Page", body=LOREM, extra_head="", h1="A Page"):
    return f"""<html><head><title>{title}</title>
    <meta name="description" content="A description of this page.">
    {extra_head}
    </head><body><h1>{h1}</h1><p>{body}</p></body></html>"""


def assert_evidence_binds(store, findings):
    known_ids = {obs["id"] for obs in store["observations"]}
    for finding in findings:
        for oid in finding["observation_ids"]:
            assert oid in known_ids, f"{finding['check_id']} cites unresolvable observation id {oid}"


def assert_finding_shape(finding):
    """An unscored finding, once given an `id`, satisfies report.schema.json's
    finding shape -- the orchestrator assigns `id`, not this skill."""
    candidate = {"id": "F-001", **finding}
    jsonschema.validate(candidate, FINDING_SCHEMA)


# ---------------------------------------------------------------------------
# D-CRAWL
# ---------------------------------------------------------------------------


def test_d_crawl_01_fires_on_disallowed_non_utility_path():
    home_html = page(body=LOREM + '<a href="/private/report">Report</a> <a href="/cart">Cart</a>')
    store = make_store(
        [
            robots_obs("User-agent: *\nDisallow: /private\nDisallow: /cart\n"),
            fetch_obs("https://example.com/", home_html),
        ]
    )

    findings = detect_crawl.detect_crawl(store)
    hits = [f for f in findings if f["check_id"] == "D-CRAWL-01"]

    assert len(hits) == 1
    assert "https://example.com/private/report" in hits[0]["source_urls"]
    assert "https://example.com/cart" not in hits[0]["source_urls"]
    assert hits[0]["severity"] == "critical"
    assert_finding_shape(hits[0])
    assert_evidence_binds(store, hits)


def test_d_crawl_01_never_fires_when_only_utility_paths_disallowed():
    home_html = page(body=LOREM + '<a href="/cart">Cart</a> <a href="/search">Search</a>')
    store = make_store(
        [
            robots_obs("User-agent: *\nDisallow: /cart\nDisallow: /search\n"),
            fetch_obs("https://example.com/", home_html),
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-01"]
    assert findings == []


def test_d_crawl_02_ai_bot_specifically_blocked_is_medium_not_error():
    store = make_store(
        [
            robots_obs(
                "User-agent: *\nDisallow: /private\n\nUser-agent: GPTBot\nDisallow: /private\nDisallow: /blog\n"
            )
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-02"]

    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert "GPTBot" in findings[0]["title"]
    assert_finding_shape(findings[0])


def test_d_crawl_03_noindex_on_substantive_page_is_critical():
    html = page(extra_head='<meta name="robots" content="noindex, follow">')
    store = make_store([fetch_obs("https://example.com/about", html)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-03"]

    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_crawl_03_never_fires_on_utility_path():
    html = page(extra_head='<meta name="robots" content="noindex">')
    store = make_store([fetch_obs("https://example.com/cart", html)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-03"]
    assert findings == []


def test_d_crawl_04_fires_on_dead_page():
    store = make_store([fetch_obs("https://example.com/dead", "<html></html>", status_code=404)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-04"]

    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert_finding_shape(findings[0])


def test_d_crawl_05_fires_on_long_redirect_chain():
    chain = [
        {"from": "https://example.com/a", "to": "https://example.com/b", "status": 301},
        {"from": "https://example.com/b", "to": "https://example.com/c", "status": 301},
        {"from": "https://example.com/c", "to": "https://example.com/d", "status": 301},
    ]
    store = make_store([fetch_obs("https://example.com/a", page(), redirect_chain=chain)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-05"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_crawl_05_never_fires_on_single_hop():
    chain = [{"from": "http://example.com/a", "to": "https://example.com/a", "status": 301}]
    store = make_store([fetch_obs("http://example.com/a", page(), redirect_chain=chain)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-05"]
    assert findings == []


def test_d_crawl_06_fires_on_same_domain_canonical_to_broken_target():
    source_html = page(extra_head='<link rel="canonical" href="https://example.com/target">')
    store = make_store(
        [
            fetch_obs("https://example.com/source", source_html),
            fetch_obs("https://example.com/target", "<html></html>", status_code=404),
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-06"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_crawl_06_never_fires_on_cross_domain_canonical():
    source_html = page(extra_head='<link rel="canonical" href="https://partner-site.com/target">')
    store = make_store([fetch_obs("https://example.com/source", source_html)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-06"]
    assert findings == []


def test_d_crawl_07_absence_only_fires_with_orphans():
    # 3 pages, home links only to /a; /b is crawled but reachable by no internal link.
    home = page(body=LOREM + '<a href="/a">A</a>')
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/a", page()),
            fetch_obs("https://example.com/b", page()),
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-07"]
    assert len(findings) == 1
    assert "https://example.com/b" in findings[0]["source_urls"]


def test_d_crawl_07_never_fires_absence_alone_on_fully_interlinked_site():
    home = page(body=LOREM + '<a href="/a">A</a> <a href="/b">B</a>')
    a = page(body=LOREM + '<a href="/">Home</a> <a href="/b">B</a>')
    b = page(body=LOREM + '<a href="/">Home</a> <a href="/a">A</a>')
    store = make_store(
        [
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/a", a),
            fetch_obs("https://example.com/b", b),
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-07"]
    assert findings == []


def test_d_crawl_07_fires_on_sitemap_rot():
    store = make_store(
        [
            sitemap_obs(
                [
                    {"loc": "https://example.com/a", "status_code": 200},
                    {"loc": "https://example.com/b", "status_code": 404},
                    {"loc": "https://example.com/c", "status_code": 404},
                ]
            )
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-07"]
    assert len(findings) == 1
    assert findings[0]["affected"]["total_in_scope"] == 3


def test_d_crawl_08_fires_on_orphaned_sitemap_page():
    home = page(body=LOREM + '<a href="/a">A</a>')
    store = make_store(
        [
            sitemap_obs(
                [
                    {"loc": "https://example.com/", "status_code": 200},
                    {"loc": "https://example.com/a", "status_code": 200},
                    {"loc": "https://example.com/orphan", "status_code": 200},
                ]
            ),
            fetch_obs("https://example.com/", home),
            fetch_obs("https://example.com/a", page()),
            fetch_obs("https://example.com/orphan", page()),
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-08"]
    assert len(findings) == 1
    assert "https://example.com/orphan" in findings[0]["source_urls"]


def test_d_crawl_08_never_fires_below_minimum_corpus():
    store = make_store(
        [
            sitemap_obs([{"loc": "https://example.com/a", "status_code": 200}]),
            fetch_obs("https://example.com/a", page()),
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-08"]
    assert findings == []


def test_d_crawl_09_fires_on_403():
    store = make_store([fetch_obs("https://example.com/blocked", "<html></html>", status_code=403)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-09"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"


def test_d_crawl_10_fires_on_slow_median_with_five_samples():
    observations = [
        fetch_obs(f"https://example.com/p{i}", page(), elapsed_ms=12000) for i in range(5)
    ]
    store = make_store(observations)

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-10"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"


def test_d_crawl_10_never_fires_below_five_samples():
    observations = [fetch_obs(f"https://example.com/p{i}", page(), elapsed_ms=12000) for i in range(3)]
    store = make_store(observations)

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-10"]
    assert findings == []


def test_d_crawl_15_fires_on_robots_5xx():
    store = make_store([broken_robots_obs("error")])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-15"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"


def test_d_crawl_15_never_fires_on_missing_robots():
    store = make_store([broken_robots_obs("missing")])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-15"]
    assert findings == []


def test_d_crawl_11_fires_when_locale_variants_carry_no_hreflang():
    store = make_store(
        [
            fetch_obs("https://example.com/en/pricing", page()),
            fetch_obs("https://example.com/fr/pricing", page()),
        ]
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-11"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_crawl_11_never_fires_with_a_single_locale():
    store = make_store([fetch_obs("https://example.com/en/pricing", page())])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-11"]
    assert findings == []


def test_d_crawl_12_fires_on_explicit_regional_block_text():
    html = page(body="Sorry, this content is not available in your region right now.")
    store = make_store([fetch_obs("https://example.com/regional", html)])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-12"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "low"


def test_d_crawl_12_never_fires_without_explicit_block_text():
    store = make_store([fetch_obs("https://example.com/regional", page())])

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-12"]
    assert findings == []


def test_d_crawl_13_fires_on_duplicate_serving_alternate_host():
    store = make_store(
        [fetch_obs("https://mirror-example.com/page", page())],
        target={"audited_host": "example.com"},
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-13"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_crawl_13_never_fires_when_alternate_canonicalizes_back():
    html = page(extra_head='<link rel="canonical" href="https://example.com/page">')
    store = make_store(
        [fetch_obs("https://mirror-example.com/page", html)],
        target={"audited_host": "example.com"},
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-13"]
    assert findings == []


def test_d_crawl_14_fires_when_budget_exhausted_and_parameter_ratio_high():
    home = page(
        body=LOREM
        + "".join(f'<a href="/list?filter={i}">F{i}</a>' for i in range(4))
        + '<a href="/list/plain">Plain</a>'
    )
    store = make_store(
        [fetch_obs("https://example.com/", home)],
        capabilities={"crawl": {"budget_exhausted": True}},
    )

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-14"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_crawl_14_never_fires_when_budget_not_exhausted():
    home = page(body=LOREM + "".join(f'<a href="/list?filter={i}">F{i}</a>' for i in range(4)))
    store = make_store([fetch_obs("https://example.com/", home)], capabilities={"crawl": {"budget_exhausted": False}})

    findings = [f for f in detect_crawl.detect_crawl(store) if f["check_id"] == "D-CRAWL-14"]
    assert findings == []


# ---------------------------------------------------------------------------
# D-RENDER
# ---------------------------------------------------------------------------


def test_d_render_01_fires_when_main_content_is_raw_shell():
    raw_html = "<html><body><nav>Home About</nav></body></html>"
    rendered_html = page(body=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/", raw_html),
            render_obs("https://example.com/", rendered_html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-01"]
    assert len(findings) == 1
    assert findings[0]["confidence"] == "medium"  # single page
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_render_01_never_fires_when_raw_and_rendered_agree():
    html = page(body=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/", html),
            render_obs("https://example.com/", html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-01"]
    assert findings == []


def test_d_render_01_inapplicable_when_render_unavailable():
    store = make_store(
        [
            fetch_obs("https://example.com/", "<html><body></body></html>"),
            render_obs("https://example.com/", "", status="unavailable"),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-01"]
    assert findings == []


def test_d_render_02_fires_when_answered_fact_only_in_rendered_text():
    raw_html = page(body="Some generic text with no price mentioned anywhere on this page at all today.")
    rendered_html = page(body="Some generic text. The price is $42 per unit, available now.")
    store = make_store(
        [
            fetch_obs("https://example.com/product", raw_html),
            render_obs("https://example.com/product", rendered_html),
            probe_obs(
                "https://example.com/product",
                [
                    {
                        "id": "price",
                        "category": "factual",
                        "relevant": True,
                        "answered": True,
                        "answer": "$42",
                        "evidence_span": "The price is $42 per unit",
                    }
                ],
            ),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-02"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_render_03_fires_on_three_or_more_rendered_only_links():
    raw_html = page(body=LOREM + '<a href="/a">A</a>')
    rendered_html = page(body=LOREM + '<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a><a href="/d">D</a>')
    store = make_store(
        [
            fetch_obs("https://example.com/", raw_html),
            render_obs("https://example.com/", rendered_html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-03"]
    assert len(findings) == 1
    assert findings[0]["affected"]["count"] == 3


def test_d_render_03_never_fires_below_three_new_links():
    raw_html = page(body=LOREM + '<a href="/a">A</a>')
    rendered_html = page(body=LOREM + '<a href="/a">A</a><a href="/b">B</a>')
    store = make_store(
        [
            fetch_obs("https://example.com/", raw_html),
            render_obs("https://example.com/", rendered_html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-03"]
    assert findings == []


def test_d_render_04_fires_when_disclosure_panel_is_empty_pre_interaction():
    html = (
        "<html><body>"
        '<button aria-controls="panel1">Details</button>'
        '<div id="panel1"></div>'
        "</body></html>"
    )
    store = make_store(
        [
            fetch_obs("https://example.com/faq", html),
            render_obs("https://example.com/faq", html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-04"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_render_04_never_fires_when_panel_has_content():
    html = (
        "<html><body>"
        '<button aria-controls="panel1">Details</button>'
        '<div id="panel1">Full answer text is already present here.</div>'
        "</body></html>"
    )
    store = make_store(
        [
            fetch_obs("https://example.com/faq", html),
            render_obs("https://example.com/faq", html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-04"]
    assert findings == []


def test_d_render_05_fires_on_large_listing_with_no_pagination():
    items = "".join(f'<div class="card">Item {i}</div>' for i in range(12))
    rendered_html = f"<html><body><div class='grid'>{items}</div></body></html>"
    raw_html = "<html><body></body></html>"
    store = make_store(
        [
            fetch_obs("https://example.com/products", raw_html),
            render_obs("https://example.com/products", rendered_html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-05"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_render_05_never_fires_when_pagination_anchor_present():
    items = "".join(f'<div class="card">Item {i}</div>' for i in range(12))
    rendered_html = f"<html><body><div class='grid'>{items}</div><a href='/products?page=2'>Next</a></body></html>"
    raw_html = "<html><body></body></html>"
    store = make_store(
        [
            fetch_obs("https://example.com/products", raw_html),
            render_obs("https://example.com/products", rendered_html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-05"]
    assert findings == []


def test_d_render_05_never_fires_below_ten_items():
    items = "".join(f'<div class="card">Item {i}</div>' for i in range(5))
    rendered_html = f"<html><body><div class='grid'>{items}</div></body></html>"
    raw_html = "<html><body></body></html>"
    store = make_store(
        [
            fetch_obs("https://example.com/products", raw_html),
            render_obs("https://example.com/products", rendered_html),
        ]
    )

    findings = [f for f in detect_render.detect_render(store) if f["check_id"] == "D-RENDER-05"]
    assert findings == []


# ---------------------------------------------------------------------------
# D-EXTRACT
# ---------------------------------------------------------------------------


def test_d_extract_01_fires_on_probe_miss_with_empty_alt_image():
    url = "https://example.com/menu"
    html = f"""<html><head><title>Menu</title><meta name="description" content="Our menu.">
    </head><body><h1>Menu</h1><p>{LOREM}</p><img src="/menu.jpg"></body></html>"""
    store = make_store(
        [
            fetch_obs(url, html),
            probe_obs(
                url,
                [{"id": "prices", "category": "factual", "relevant": True, "answered": False}],
            ),
        ]
    )

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-01"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_d_extract_01_never_fires_on_probe_miss_without_non_text_carrier():
    url = "https://example.com/menu"
    html = page(body=LOREM)  # no images, no PDFs
    store = make_store(
        [
            fetch_obs(url, html),
            probe_obs(
                url,
                [{"id": "prices", "category": "factual", "relevant": True, "answered": False}],
            ),
        ]
    )

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-01"]
    assert findings == []


def test_d_extract_02_fires_on_empty_title():
    html = """<html><head><title></title></head><body><h1>X</h1><p>{}</p></body></html>""".format(LOREM)
    store = make_store([fetch_obs("https://example.com/x", html)])

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-02"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_extract_02_fires_on_duplicate_title_across_distinct_pages():
    html_a = page(title="Same Title")
    html_b = page(title="Same Title")
    store = make_store(
        [
            fetch_obs("https://example.com/blog/my-first-post", html_a),
            fetch_obs("https://example.com/blog/my-second-post", html_b),
        ]
    )

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-02"]
    dup = [f for f in findings if "Duplicated" in f["title"]]
    assert len(dup) == 1
    assert dup[0]["affected"]["count"] == 2


def test_d_extract_03_compound_trigger_requires_both_conditions():
    url = "https://example.com/product/widget"
    html_no_schema = page()
    store_fires = make_store(
        [
            fetch_obs(url, html_no_schema),
            classification_obs(url, "product"),
            probe_obs(
                url,
                [{"id": "price", "category": "factual", "relevant": True, "answered": False}],
            ),
        ]
    )
    findings = [f for f in detect_extract.detect_extract(store_fires) if f["check_id"] == "D-EXTRACT-03"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])
    assert_evidence_binds(store_fires, findings)

    # markup absent but prose states the fact (probe answers) -> never fires
    store_prose_ok = make_store(
        [
            fetch_obs(url, html_no_schema),
            classification_obs(url, "product"),
            probe_obs(url, [{"id": "price", "category": "factual", "relevant": True, "answered": True}]),
        ]
    )
    assert [f for f in detect_extract.detect_extract(store_prose_ok) if f["check_id"] == "D-EXTRACT-03"] == []

    # schema present -> never fires regardless of probe outcome
    html_with_schema = page(
        extra_head='<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Widget","offers":{"price":"9.99","priceCurrency":"USD"}}</script>'
    )
    store_schema_ok = make_store(
        [
            fetch_obs(url, html_with_schema),
            classification_obs(url, "product"),
            probe_obs(url, [{"id": "price", "category": "factual", "relevant": True, "answered": False}]),
        ]
    )
    assert [f for f in detect_extract.detect_extract(store_schema_ok) if f["check_id"] == "D-EXTRACT-03"] == []


def test_d_extract_04_fires_on_missing_required_property():
    html = page(
        extra_head='<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Widget"}</script>'
    )
    store = make_store([fetch_obs("https://example.com/widget", html)])

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-04"]
    assert len(findings) == 1
    assert "offers.price" in findings[0]["evidence"] or "offers.price" in findings[0]["observed_signal"]


def test_d_extract_04_never_fires_when_required_properties_present():
    html = page(
        extra_head='<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Widget","offers":{"priceCurrency":"USD"}}</script>'
    )
    store = make_store([fetch_obs("https://example.com/widget", html)])

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-04"]
    assert findings == []


def test_d_extract_04_fires_on_json_parse_error():
    html = page(extra_head='<script type="application/ld+json">{not valid json</script>')
    store = make_store([fetch_obs("https://example.com/broken", html)])

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-04"]
    assert len(findings) == 1
    assert findings[0]["confidence"] == "high"


def test_d_extract_05_fires_when_no_h1():
    html = f"<html><head><title>T</title></head><body><h2>Section</h2><p>{LOREM}</p></body></html>"
    store = make_store([fetch_obs("https://example.com/no-h1", html)])

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-05"]
    assert len(findings) == 1
    assert "No h1" in findings[0]["title"]


def test_d_extract_05_never_fires_with_h1_present():
    html = page(body=LOREM)
    store = make_store([fetch_obs("https://example.com/has-h1", html)])

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-05"]
    assert [f for f in findings if "No h1" in f["title"]] == []


def test_d_extract_06_fires_on_two_unanswered_relevant_questions():
    url = "https://example.com/about"
    store = make_store(
        [
            fetch_obs(url, page()),
            probe_obs(
                url,
                [
                    {"id": "who", "category": "factual", "relevant": True, "answered": False},
                    {"id": "what", "category": "factual", "relevant": True, "answered": False},
                ],
            ),
        ]
    )

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-06"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_extract_06_never_fires_on_single_unanswered_question():
    url = "https://example.com/about"
    store = make_store(
        [
            fetch_obs(url, page()),
            probe_obs(
                url,
                [
                    {"id": "who", "category": "factual", "relevant": True, "answered": False},
                    {"id": "what", "category": "factual", "relevant": True, "answered": True},
                ],
            ),
        ]
    )

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-06"]
    assert findings == []


def test_d_extract_07_fires_when_expected_explicit_fact_is_unanswered():
    url = "https://example.com/product/widget"
    store = make_store(
        [
            fetch_obs(url, page(body=LOREM)),
            classification_obs(url, "product"),
            probe_obs(
                url,
                [
                    {
                        "id": "primary_offering",
                        "category": "factual",
                        "relevant": True,
                        "expects_explicit_statement": True,
                        "answered": False,
                    }
                ],
            ),
        ]
    )

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-07"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_d_extract_09_fires_on_non_html_content_type():
    store = make_store(
        [
            fetch_obs(
                "https://example.com/page",
                page(),
                headers={"Content-Type": "application/octet-stream"},
            )
        ]
    )

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-09"]
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_d_extract_09_never_fires_on_normal_html():
    store = make_store([fetch_obs("https://example.com/page", page())])

    findings = [f for f in detect_extract.detect_extract(store) if f["check_id"] == "D-EXTRACT-09"]
    assert findings == []


def test_d_extract_08_is_proactive_only_never_a_finding():
    boilerplate = ("Accept cookies. " * 5) + ("Subscribe to our newsletter. " * 5)
    text_body = boilerplate + " The answer is: our office opens at 9am on weekdays."
    html = f"<html><head><title>T</title></head><body><h1>T</h1><p>{text_body}</p></body></html>"
    url = "https://example.com/deep-page"
    store = make_store(
        [
            fetch_obs(url, html),
            probe_obs(
                url,
                [
                    {
                        "id": "hours",
                        "category": "factual",
                        "relevant": True,
                        "answered": True,
                        "evidence_span": "our office opens at 9am on weekdays",
                    }
                ],
            ),
        ]
    )

    findings = detect_extract.detect_extract(store)
    assert all(f["check_id"] != "D-EXTRACT-08" for f in findings)

    opportunities = detect_extract.proactive_opportunities(store)
    assert any(o["check_id"] == "D-EXTRACT-08" for o in opportunities)


# ---------------------------------------------------------------------------
# Cross-cutting: clean site produces zero findings (false-positive regression)
# ---------------------------------------------------------------------------


def test_clean_site_yields_no_findings_across_all_three_detectors():
    home_html = page(
        title="Example Site",
        body=LOREM + '<a href="/about">About</a>',
        extra_head='<link rel="canonical" href="https://example.com/">',
    )
    about_html = page(
        title="About Example Site",
        body=LOREM + '<a href="/">Home</a>',
        extra_head='<link rel="canonical" href="https://example.com/about">',
    )
    store = make_store(
        [
            robots_obs("User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml\n"),
            fetch_obs("https://example.com/", home_html, elapsed_ms=120),
            fetch_obs("https://example.com/about", about_html, elapsed_ms=140),
            render_obs("https://example.com/", home_html),
            render_obs("https://example.com/about", about_html),
        ]
    )

    crawl_findings = detect_crawl.detect_crawl(store)
    render_findings = detect_render.detect_render(store)
    extract_findings = detect_extract.detect_extract(store)

    assert crawl_findings == []
    assert render_findings == []
    assert extract_findings == []


def test_group_by_cluster_collapses_same_shaped_urls():
    from _util import cluster_key

    assert cluster_key("https://example.com/blog/my-first-post") == cluster_key(
        "https://example.com/blog/my-second-post"
    )
    assert cluster_key("https://example.com/product/123") == cluster_key("https://example.com/product/456")


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/cart", True),
        ("/cart/items", True),
        ("/search", True),
        ("/products?color=red", True),
        ("/blog/my-post", False),
        ("/about", False),
    ],
)
def test_is_utility_path(path, expected):
    from _util import is_utility_path

    assert is_utility_path(f"https://example.com{path}") is expected
