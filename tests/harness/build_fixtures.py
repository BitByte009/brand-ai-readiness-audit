"""Generates the adversarial fixture corpus: static HTML sites under
tests/fixtures/<id>/site/, plus expected.json declaring the check IDs each
site should and should not trigger. Run once (`python build_fixtures.py`) to
(re)write the corpus; the generated files are committed like any other
fixture content per tests/fixtures/README.md -- this script is the build
tool, not something run.py depends on at audit time.

Trigger conditions encoded here were reverse-engineered directly from the
detector source (skills/*/scripts/detect_*.py, lib/site_observer/*.py)
rather than the checks' prose descriptions, and cross-checked empirically
via tests/harness/run_corpus.py against a real run of the pipeline.

Two confirmed tool defects (see the final report) mean every fixture below
follows fixed conventions to avoid contaminating unrelated checks with
incidental noise:
  - Seed URL always ends in "/" (run_corpus.py). A bare seed
    ("http://host:port") plus an internal href="/" link makes
    lib/site_observer/crawl.py double-count the homepage under two distinct
    URL strings for the same resource.
  - Every page uses a single consistent "<h1>{brand}</h1>" (never a
    page-specific H1 like "Services" or "About {brand}"). D-ENTITY-01's
    name-candidate extraction (build_entity_profile.py::_collect_name_candidates)
    has no minimum-frequency floor, so ordinary page-specific H1 text
    dilutes an otherwise 100%-consistent brand name below the 70%
    consistency threshold -- confirmed via clean-static during authoring
    (see the report's tool-defects section). Fixtures that deliberately
    test entity-name inconsistency (ambiguous-entity) still vary the H1.
  - Every page not deliberately testing E-CONTINUE dead-ends carries at
    least one in-main-content (non-nav) link to another crawled page.
  - Every fixture not deliberately testing D-TRUST-06 opacity includes a
    contact email/phone or an /about path.
  - Homepage prose includes an explicit "we <verb> ..." offering sentence
    (matching entity-semantic-audit's _OFFERING_PATTERN_RE) unless the
    fixture deliberately tests D-ENTITY-06 or sits on an archetype that
    suppresses it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"

ROBOTS_ALLOW_ALL = "User-agent: *\nAllow: /\n"


def page(
    title: str,
    description: str,
    body: str,
    *,
    jsonld: Optional[List[Dict[str, Any]]] = None,
    extra_head: str = "",
    lang: str = "en",
) -> str:
    jsonld_block = ""
    if jsonld:
        for node in jsonld:
            jsonld_block += f'<script type="application/ld+json">{json.dumps(node)}</script>\n'
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="description" content="{description}">
{extra_head}
{jsonld_block}</head>
<body>
{body}
</body>
</html>
"""


def org_jsonld(name: str, url: str, *, same_as: Optional[List[str]] = None, description: str = "") -> Dict[str, Any]:
    node: Dict[str, Any] = {"@context": "https://schema.org", "@type": "Organization", "name": name, "url": url}
    if same_as:
        node["sameAs"] = same_as
    if description:
        node["description"] = description
    return node


def navlinks(items: List[tuple]) -> str:
    return "<nav>" + " ".join(f'<a href="{href}">{label}</a>' for href, label in items) + "</nav>"


def brand_footer(brand: str, year: int = 2026) -> str:
    """A consistent, realistic '(c) YEAR Brand' footer on every page. This is
    an independent name-candidate source (footer_copyright_name in
    _entity_util.py) separate from title/h1/schema -- see the module
    docstring's note on D-ENTITY-01's fragile 70% threshold: on a small
    (3-5 page) site, standard 'Page | Brand' titles alone leave enough
    page-specific segments ('Home', 'Pricing', 'Contact') in the candidate
    pool that the majority share can land just under 70% even with an
    identical H1 on every page. A footer anchor is what a normal production
    site would also have, and it is what pushes real sites over the line."""
    return f"<footer>&copy; {year} {brand}</footer>"


def write_fixture(fixture_id: str, files: Dict[str, str], expected: Dict[str, Any], server_config: Optional[Dict[str, Any]] = None) -> None:
    root = FIXTURES_ROOT / fixture_id
    site = root / "site"
    site.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        target = site / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (root / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    if server_config is not None:
        (root / "server_config.json").write_text(json.dumps(server_config, indent=2), encoding="utf-8")
    elif (root / "server_config.json").exists():
        (root / "server_config.json").unlink()


EXTRACT_RENDER_WIRING_GAP = (
    "CRITICAL, CONFIRMED ORCHESTRATOR BUG (more fundamental than any probe-availability gap): "
    "skills/audit-orchestrator/scripts/run_audit.py::_invoke_detectors() imports and calls only "
    "detect_crawl.detect_crawl(store), detect_entity.detect_entity(...), detect_trust.detect_trust(...), "
    "and detect_engagement.detect_engagement(...). It never imports or calls detect_render.detect_render(store) "
    "or detect_extract.detect_extract(store) -- confirmed by grep: those two functions are invoked ONLY from "
    "tests/test_crawl_render_audit.py, nowhere in production code. detect_crawl.py's own CHECKS list (feeding "
    "its detect_crawl() dispatcher) contains only check_d_crawl_01..15 -- no delegation to the other two files. "
    "Consequence: ALL 5 D-RENDER-01..05 checks and ALL 9 D-EXTRACT-01..09 checks -- 14 of the marketplace's 53 "
    "taxonomy checks, more than a quarter of the whole catalog, including the flagship raw-vs-rendered-gap and "
    "structured-data-validity checks -- never fire in any real audit, regardless of site content, independent of "
    "and in addition to the two checks' own probe-capability gaps documented elsewhere. Verified directly: calling "
    "detect_extract.check_d_extract_04(store) by hand on this fixture's real collected store returns the correct "
    "findings; calling the real run_audit(url) end to end on the identical fixture returns none. The 63 unit tests "
    "in tests/test_crawl_render_audit.py all call detect_render()/detect_extract() directly and therefore pass "
    "despite this gap -- they could not have caught it; only an end-to-end run through the real entrypoint could, "
    "which is exactly what this fixture corpus does. The fix is a two-line addition to _invoke_detectors()."
)
PROBE_GAP = (
    "Requires a PROBE observation. lib/site_observer/probe.py::detect_capability() is "
    "hardcoded to always return {'available': False, 'reason': 'MODEL_UNAVAILABLE'} -- "
    "not environment-detected, unconditional -- so PROBE observations never exist through "
    "the real pipeline regardless of fixture content. This check is dead code in every real run."
)
CORROBORATION_GAP = (
    "Requires a CORROBORATION/CLAIM_CORROBORATION observation with performed=true from an "
    "outbound-search instrument that is never wired into this environment (OQ-3, still open). "
    "Dead code in every real run; only exercisable by hand-injecting the observation into the "
    "store JSON, bypassing the HTTP pipeline entirely."
)


# ===========================================================================
# 1. clean-static -- strong static site, baseline near-zero findings
# ===========================================================================


def build_clean_static() -> None:
    brand = "Northwind Robotics"
    nav = navlinks([("/", "Home"), ("/about.html", "About"), ("/services.html", "Services"), ("/contact.html", "Contact")])
    org_home = org_jsonld(brand, "https://example.test/",
                           same_as=["https://www.linkedin.com/company/northwind-robotics"],
                           description="Northwind Robotics designs and builds industrial automation arms for manufacturers.")
    org_about = org_jsonld(brand, "https://example.test/",
                            same_as=["https://www.linkedin.com/company/northwind-robotics"],
                            description="Northwind Robotics designs and builds industrial automation arms for manufacturers.")

    files = {
        "index.html": page(
            f"{brand} | Home",
            "Northwind Robotics designs and builds industrial automation arms for manufacturers.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a robotics engineering company. "
            f"We design and build industrial automation arms for manufacturers worldwide. "
            f"Our team partners with factory operators to install and maintain robotic arms "
            f"on production lines. Learn more about our <a href=\"services.html\">services</a> "
            f"or read about <a href=\"about.html\">our team</a>.</p></main>",
            jsonld=[org_home],
        ),
        "about.html": page(
            f"About | {brand}",
            "Northwind Robotics designs and builds industrial automation arms for manufacturers.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a robotics engineering company "
            f"founded by a team of mechanical and controls engineers. We build industrial "
            f"automation arms used on factory floors. See our <a href=\"services.html\">services</a> "
            f"or <a href=\"contact.html\">get in touch</a>.</p></main>",
            jsonld=[org_about],
        ),
        "services.html": page(
            f"Services | {brand}",
            "Robotic arm design, installation and maintenance services from Northwind Robotics.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} provides robotic arm design, installation "
            f"and ongoing maintenance for manufacturers. We help factory operators automate "
            f"repetitive assembly and packaging tasks. <a href=\"contact.html\">Contact us</a> "
            f"to discuss a project, or read more <a href=\"about.html\">about our team</a>.</p></main>",
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach the Northwind Robotics team by email or phone.",
            f"{nav}<h1>{brand}</h1><main><p>Reach {brand} at hello@example.test or call "
            f"555-201-3040 to discuss a project. See our <a href=\"services.html\">services</a> "
            f"for what we offer.</p></main>",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "Strong static site: consistent brand H1/title everywhere, stated type/offering, contact info, clean robots/canonical, no schema defects, working continuation links.",
        "expected_findings": [],
        "expected_non_findings": ["D-ENTITY-01", "D-ENTITY-02", "D-ENTITY-05", "D-ENTITY-06", "D-TRUST-01", "D-TRUST-02", "D-TRUST-06", "D-EXTRACT-02", "D-CRAWL-01", "D-CRAWL-03", "D-CRAWL-07", "E-CONTINUE-01", "E-CONTINUE-02"],
        "notes": "Baseline. Any finding here is presumed a false positive unless evidence shows otherwise.",
    }
    write_fixture("clean-static", files, expected)


# ===========================================================================
# 2. js-render-gap -- JS-heavy site, bulk content only exists post-render
# ===========================================================================


def build_js_render_gap() -> None:
    brand = "Alloy Dynamics"
    nav = navlinks([("/", "Home"), ("/platform.html", "Platform"), ("/pricing.html", "Pricing"), ("/contact.html", "Contact")])
    heavy_text = (
        "We build a workflow automation platform for operations teams. "
        "Our platform connects spreadsheets, ticketing systems and internal tools into "
        "one automated pipeline, so operations teams stop copying data by hand between "
        "systems every day. Teams using Alloy Dynamics report fewer manual handoffs and "
        "faster incident response because every system update flows through one place."
    )
    js_inject = f"""<script>
document.addEventListener('DOMContentLoaded', function() {{
  document.getElementById('app').innerHTML = {json.dumps('<p>' + heavy_text + '</p>')};
}});
</script>"""

    files = {
        "index.html": page(
            f"{brand} | Home",
            "Alloy Dynamics is a workflow automation platform for operations teams.",
            f'{nav}<h1>{brand}</h1><main><div id="app">Loading&hellip;</div>'
            f'<p>See our <a href="platform.html">platform</a> or <a href="pricing.html">pricing</a>.</p></main>{brand_footer(brand)}{js_inject}',
            jsonld=[org_jsonld(brand, "https://example.test/")],
        ),
        "platform.html": page(
            f"Platform | {brand}",
            "How the Alloy Dynamics automation platform connects your tools.",
            f'{nav}<h1>{brand}</h1><main><div id="app">Loading&hellip;</div>'
            f'<p><a href="contact.html">Contact us</a> to see a demo.</p></main>{brand_footer(brand)}{js_inject}',
        ),
        "pricing.html": page(
            f"Pricing | {brand}",
            "Alloy Dynamics pricing plans for operations teams of any size.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} offers monthly and annual plans for "
            f"operations teams. <a href=\"contact.html\">Contact sales</a> for a quote.</p></main>{brand_footer(brand)}",
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach the Alloy Dynamics team.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at hello@example.test or call "
            f"555-330-7700. See our <a href=\"platform.html\">platform</a>.</p></main>{brand_footer(brand)}",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "JS-heavy site: index/platform pages render almost all body text client-side via a DOMContentLoaded script; raw HTML is a near-empty shell. This is textbook D-RENDER-01 (raw-vs-rendered text ratio <0.30).",
        "expected_findings": [],
        "expected_non_findings": ["D-ENTITY-01", "D-ENTITY-02", "D-TRUST-06"],
        "confirmed_false_negative": {
            "check": "D-RENDER-01",
            "why": EXTRACT_RENDER_WIRING_GAP + " Verified directly for this fixture: calling detect_render.check_d_render_01(store) by hand on the real collected store correctly returns a finding; the real run_audit(url) returns none.",
        },
        "structurally_untestable": {"D-RENDER-02": PROBE_GAP + " Moot in any case since detect_render() is never invoked at all -- see D-RENDER-01's confirmed_false_negative."},
        "notes": "Playwright is installed and rendering succeeds (verified: RENDER observations are present and correct) -- the gap is entirely in the orchestrator never calling the detector, not in rendering capability.",
    }
    write_fixture("js-render-gap", files, expected)


# ===========================================================================
# 3. facts-render-only -- ONE critical fact hidden behind JS, bulk text is
#    already substantial raw (ratio stays >=0.30) -- a documented false-
#    negative case, since D-RENDER-02 (which targets exactly this) is
#    probe-gated and unreachable.
# ===========================================================================


def build_facts_render_only() -> None:
    brand = "Cascade Freight"
    nav = navlinks([("/", "Home"), ("/tracking.html", "Tracking"), ("/rates.html", "Rates"), ("/contact.html", "Contact")])
    raw_prose = (
        "Cascade Freight is a freight logistics company. We provide freight transport "
        "between distribution centers for retail and grocery chains across the Pacific "
        "Northwest. Our dispatch team plans routes daily to keep delivery windows tight "
        "and reliable for every customer on our network, from small retailers to large "
        "grocery chains who depend on consistent, on-time freight service every week."
    )
    js_inject = """<script>
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('rate').textContent = 'Current LTL rate: $184 per pallet, zone 3.';
});
</script>"""

    files = {
        "index.html": page(
            f"{brand} | Home",
            "Cascade Freight is a regional freight carrier serving the Pacific Northwest.",
            f"{nav}<h1>{brand}</h1><main><p>{raw_prose} See our <a href=\"tracking.html\">tracking</a> "
            f"tool or <a href=\"rates.html\">current rates</a>.</p></main>{brand_footer(brand)}",
            jsonld=[org_jsonld(brand, "https://example.test/")],
        ),
        "tracking.html": page(
            f"Tracking | {brand}",
            "Track a Cascade Freight shipment by reference number.",
            f"{nav}<h1>{brand}</h1><main><p>Enter your reference number to track a shipment. "
            f"See our <a href=\"rates.html\">rates</a> or <a href=\"contact.html\">contact us</a>.</p></main>{brand_footer(brand)}",
        ),
        "rates.html": page(
            f"Rates | {brand}",
            "Current Cascade Freight LTL shipping rates by zone.",
            f'{nav}<h1>{brand}</h1><main><p>{raw_prose}</p><p id="rate">Loading current rate&hellip;</p>'
            f'<p><a href="contact.html">Contact us</a> for a custom quote.</p></main>{brand_footer(brand)}{js_inject}',
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach the Cascade Freight dispatch team.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at dispatch@example.test or call "
            f"555-660-9020. See our <a href=\"tracking.html\">tracking</a> tool.</p></main>{brand_footer(brand)}",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "rates.html has substantial raw prose (ratio stays above the 0.30 D-RENDER-01 threshold) but the one load-bearing fact -- the actual rate -- exists only in a client-side script.",
        "expected_findings": [],
        "expected_non_findings": ["D-ENTITY-01", "D-ENTITY-02", "D-ENTITY-06", "D-TRUST-06"],
        "expected_false_negative": {
            "check": "D-RENDER-02 (facts-render-only, the check designed for exactly this)",
            "why": "Doubly unreachable: " + EXTRACT_RENDER_WIRING_GAP + " Independently, this specific check also requires a PROBE observation, and " + PROBE_GAP + " Either gap alone would already zero this out. The tool reports zero findings on this page despite the rate being genuinely unextractable from raw HTML.",
        },
        "notes": "Deliberately distinct from js-render-gap: isolates the case D-RENDER-01's bulk-ratio heuristic cannot catch -- a single critical fact hidden in an otherwise text-heavy page.",
    }
    write_fixture("facts-render-only", files, expected)


# ===========================================================================
# 4. image-locked-facts -- a fact stated only inside an image with no alt
#    text. D-EXTRACT-01 is probe-gated and therefore also unreachable.
# ===========================================================================


def build_image_locked_facts() -> None:
    brand = "Marlowe Hardware"
    nav = navlinks([("/", "Home"), ("/hours.html", "Store Hours"), ("/location.html", "Location")])
    files = {
        "index.html": page(
            f"{brand} | Home",
            "Marlowe Hardware is a family-owned hardware store.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a family-owned hardware store. "
            f"We sell tools, fasteners and paint for local contractors and homeowners. "
            f"See our <a href=\"hours.html\">store hours</a> or <a href=\"location.html\">location</a>.</p></main>",
            jsonld=[org_jsonld(brand, "https://example.test/")],
        ),
        "hours.html": page(
            f"Store Hours | {brand}",
            "Marlowe Hardware store hours.",
            f'{nav}<h1>{brand}</h1><main><p>Our hours are shown below.</p>'
            f'<img src="/hours.png" alt="">'
            f'<p>See our <a href="location.html">location</a>.</p></main>',
        ),
        "location.html": page(
            f"Location | {brand}",
            "Marlowe Hardware store location.",
            f"{nav}<h1>{brand}</h1><main><p>Visit {brand} at 12 Elm Street, or call "
            f"555-887-2200. See our <a href=\"hours.html\">store hours</a>.</p></main>",
        ),
        "hours.png": "not a real image -- content-type/binary irrelevant, extraction never reads image bytes",
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "hours.html states store hours only inside an <img> with empty alt text; no surrounding prose states the hours in machine-readable text.",
        "expected_findings": [],
        "expected_false_negative": {
            "check": "D-EXTRACT-01 (image-locked facts, the check designed for exactly this)",
            "why": "Doubly unreachable: " + EXTRACT_RENDER_WIRING_GAP + " Independently, this specific check also requires a PROBE observation (a relevant factual question answered=false AND an image/PDF carrier present), and " + PROBE_GAP,
        },
        "notes": "The clearest single demonstration that the marketplace's stated probe-driven-extractability differentiator is not wired into the shipped pipeline -- and that even if it were, the detector that would use it is itself never invoked.",
    }
    write_fixture("image-locked-facts", files, expected)


# ===========================================================================
# 5. no-structured-data-ok -- FP trap: zero JSON-LD anywhere, but identity is
#    stated clearly in prose. Absence of schema alone must never be a finding.
# ===========================================================================


def build_no_structured_data_ok() -> None:
    brand = "Fielder and Cross"
    nav = navlinks([("/", "Home"), ("/about.html", "About"), ("/work.html", "Our Work"), ("/contact.html", "Contact")])
    files = {
        "index.html": page(
            f"{brand} | Home",
            "Fielder and Cross is a landscape architecture studio.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a landscape architecture studio. "
            f"We design public parks and campus grounds for municipalities and universities. "
            f"See our <a href=\"work.html\">work</a> or <a href=\"about.html\">team</a>.</p></main>{brand_footer(brand)}",
        ),
        "about.html": page(
            f"About | {brand}",
            "The people behind the Fielder and Cross landscape architecture studio.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a landscape architecture studio founded "
            f"by two principal designers with backgrounds in horticulture and civil planning. "
            f"<a href=\"contact.html\">Get in touch</a>.</p></main>{brand_footer(brand)}",
        ),
        "work.html": page(
            f"Our Work | {brand}",
            "Selected public park and campus projects by Fielder and Cross.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} designs public parks, plazas and campus "
            f"grounds. Recent projects include a riverside park and two university quads. "
            f"See our <a href=\"about.html\">team</a>.</p></main>{brand_footer(brand)}",
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Contact the Fielder and Cross studio.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at studio@example.test or call "
            f"555-410-2200. See our <a href=\"work.html\">work</a>.</p></main>{brand_footer(brand)}",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "No JSON-LD anywhere on the site. Identity (name/type/offering) is stated clearly in prose instead. Structured data is absent, not wrong -- absence alone must never be a finding.",
        "expected_findings": [],
        "expected_non_findings": ["D-EXTRACT-03", "D-EXTRACT-04", "D-ENTITY-01", "D-ENTITY-02", "D-ENTITY-05", "D-ENTITY-06"],
        "notes": "D-ENTITY-05 (no identity anchor) is a compound check that only fires alongside D-ENTITY-01 or -02; since name/type are clearly stated in prose, neither fires, so -05 correctly stays silent even though there genuinely is no sameAs/url anchor. D-EXTRACT-03/04 are moot here regardless of content: detect_extract() is never invoked by the real pipeline at all (see EXTRACT_RENDER_WIRING_GAP in invalid-structured-data's expected.json) -- this fixture's 'clean' D-EXTRACT result and invalid-structured-data's 'clean' (i.e. silent) result would look identical to this harness even if this fixture's absence-guardrail logic were broken, since the check can't run either way. That specific ambiguity is why invalid-structured-data verifies detect_extract's logic directly as well as end-to-end.",
    }
    write_fixture("no-structured-data-ok", files, expected)


# ===========================================================================
# 6. invalid-structured-data -- D-EXTRACT-04: malformed JSON-LD + a
#    schema-mapped type missing a required property.
# ===========================================================================


def build_invalid_structured_data() -> None:
    brand = "Torrey Kitchenware"
    nav = navlinks([("/", "Home"), ("/product-a.html", "Cast Iron Pan"), ("/product-b.html", "Chef Knife"), ("/about.html", "About")])
    broken_jsonld_script = (
        '<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Product", '
        '"name": "Cast Iron Pan",, "offers": {"@type": "Offer" "price": "39.00"}}</script>'
    )
    incomplete_product = {"@context": "https://schema.org", "@type": "Product", "name": "Chef Knife"}

    files = {
        "index.html": page(
            f"{brand} | Home",
            "Torrey Kitchenware sells cast iron and stainless kitchen tools.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a kitchenware store. We sell cast iron "
            f"and stainless kitchen tools for home cooks. See our <a href=\"about.html\">story</a>, "
            f"or shop the <a href=\"product-a.html\">cast iron pan</a> and "
            f"<a href=\"product-b.html\">chef knife</a>.</p></main>{brand_footer(brand)}",
        ),
        "product-a.html": page(
            "Cast Iron Pan | " + brand,
            "A 10-inch pre-seasoned cast iron pan from Torrey Kitchenware.",
            f'{nav}<h1>{brand}</h1><main><p>A 10-inch pre-seasoned cast iron pan, '
            f'{brand} exclusive. See the <a href="product-b.html">chef knife</a> too.</p>{broken_jsonld_script}{brand_footer(brand)}</main>',
        ),
        "product-b.html": page(
            "Chef Knife | " + brand,
            "An 8-inch forged chef knife from Torrey Kitchenware.",
            f"{nav}<h1>{brand}</h1><main><p>An 8-inch forged chef knife with a full tang. "
            f'See the <a href="product-a.html">cast iron pan</a> too.</p>'
            f'<script type="application/ld+json">{json.dumps(incomplete_product)}</script>{brand_footer(brand)}</main>',
        ),
        "about.html": page(
            f"About | {brand}",
            "The story of Torrey Kitchenware.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} has sold kitchen tools since it was founded "
            f"as a small hardware counter. Email storefront@example.test or call 555-773-1100. "
            f"See our <a href=\"product-a.html\">products</a>.</p></main>{brand_footer(brand)}",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "product-a.html has syntactically broken JSON-LD (trailing comma + missing colon). product-b.html has valid JSON but a Product node missing the required offers.price/priceCurrency. Verified by calling detect_extract.check_d_extract_04() directly on this fixture's real collected store: it correctly returns both findings (the JSONDecodeError branch and the required-property branch).",
        "expected_findings": [],
        "expected_non_findings": ["D-ENTITY-01", "D-TRUST-06"],
        "confirmed_false_negative": {
            "check": "D-EXTRACT-04",
            "why": EXTRACT_RENDER_WIRING_GAP,
        },
        "notes": "This fixture is the corpus's primary evidence for the detect_extract wiring gap: it isolates D-EXTRACT-04 from every probe/render dependency (pure static JSON-LD parsing, no PROBE, no D-RENDER interaction) and confirms via direct function call that the check logic itself is correct, so the zero-findings result from the real run_audit() can only be explained by the orchestrator never invoking detect_extract() at all.",
    }
    write_fixture("invalid-structured-data", files, expected)


# ===========================================================================
# 7. ambiguous-entity -- D-ENTITY-01 name inconsistency (genuine 50/50 split,
#    no schema anchor) + D-ENTITY-02 type never stated + D-ENTITY-05 compound.
# ===========================================================================


def build_ambiguous_entity() -> None:
    nav = navlinks([("/", "Home"), ("/platform.html", "Platform"), ("/team.html", "Team"), ("/contact.html", "Contact")])
    files = {
        "index.html": page(
            "BrightPath Analytics | Home",
            "A data platform for growing teams.",
            f'{nav}<h1>BrightPath Analytics</h1><main><p>A modern data platform for growing '
            f'teams who want answers fast. See our <a href="platform.html">platform</a> or '
            f'<a href="team.html">team</a>.</p></main>',
        ),
        "platform.html": page(
            "Vertex Data Group | Platform",
            "Connect every data source in minutes.",
            f'{nav}<h1>Vertex Data Group</h1><main><p>Connect every data source in minutes '
            f'and get answers without writing a query. See our <a href="team.html">team</a> '
            f'or <a href="contact.html">contact</a> page.</p></main>',
        ),
        "team.html": page(
            "BrightPath Analytics | Team",
            "The people building BrightPath Analytics.",
            f'{nav}<h1>BrightPath Analytics</h1><main><p>A small team obsessed with fast '
            f'answers. See our <a href="contact.html">contact</a> page.</p></main>',
        ),
        "contact.html": page(
            "Vertex Data Group | Contact",
            "Reach the Vertex Data Group team.",
            f'{nav}<h1>Vertex Data Group</h1><main><p>Email hello@example.test or call '
            f'555-909-4040. See our <a href="platform.html">platform</a>.</p></main>',
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "Exactly 2 of 4 pages call the brand 'BrightPath Analytics', the other 2 call it 'Vertex Data Group' (title AND h1 both vary together, no schema anchor either way, no majority >=70%). No page states an offering-verb sentence, and no JSON-LD anywhere.",
        "expected_findings": ["D-ENTITY-01", "D-ENTITY-05", "D-ENTITY-06"],
        "expected_non_findings": ["D-ENTITY-02"],
        "notes_on_own_authoring": "D-ENTITY-02 (type never stated) does NOT fire here, and correctly so: the homepage/platform copy says 'a modern data platform', and 'platform' is one of entity-semantic-audit's TYPE_KEYWORDS. This is a useful negative result in its own right -- it shows D-ENTITY-01 (identity) and D-ENTITY-02 (type) are genuinely orthogonal: a site can plausibly state its category ('a platform') while still leaving a reader unable to tell WHICH of two names is the real one.",
        "structurally_untestable": {
            "D-ENTITY-03": CORROBORATION_GAP + " What fires instead on a genuinely ambiguous site: D-ENTITY-01/05/06, never -03.",
        },
        "notes": "D-ENTITY-05 is a compound check (fires only alongside 01 or 02 AND no identity anchor) -- expected to co-occur here, not to duplicate 01/02.",
    }
    write_fixture("ambiguous-entity", files, expected)


# ===========================================================================
# 8. stale-content -- D-TRUST-01 (no date signal for a time-sensitive claim),
#    D-TRUST-02a (forward-dated event already past, no page date), D-TRUST-02c
#    (old copyright, no other date signal).
# ===========================================================================


def build_stale_content() -> None:
    brand = "Aurora Retail Co"
    nav = navlinks([("/", "Home"), ("/pricing.html", "Pricing"), ("/events.html", "Events"), ("/contact.html", "Contact")])
    files = {
        "index.html": page(
            f"{brand} | Home",
            "Aurora Retail Co sells home goods online and in stores.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a retail store chain. We sell home goods online "
            f"and in stores. See our <a href=\"pricing.html\">pricing</a> or "
            f"<a href=\"events.html\">events</a>.</p></main>{brand_footer(brand)}",
        ),
        "pricing.html": page(
            f"Pricing | {brand}",
            "Aurora Retail Co pricing information.",
            f"{nav}<h1>{brand}</h1><main><p>Our pricing is currently the best value in the "
            f"industry. See our <a href=\"contact.html\">contact</a> page.</p></main>{brand_footer(brand)}",
        ),
        "events.html": page(
            f"Events | {brand}",
            "Upcoming Aurora Retail Co events.",
            f"{nav}<h1>{brand}</h1><main><p>Join us for our upcoming product launch event on "
            f"March 3, 2024. See our <a href=\"pricing.html\">pricing</a>.</p>"
            f"<footer>&copy; 2022 {brand}</footer></main>",
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach the Aurora Retail Co team.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at hello@example.test or call "
            f"555-440-8800. See our <a href=\"events.html\">events</a>.</p></main>{brand_footer(brand)}",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "pricing.html: 'currently' with no date signal anywhere on the page (D-TRUST-01). events.html: a forward-framed event dated March 3, 2024 (already past at any real audit time) with no page-level date at/before it, PLUS a bare (c) 2022 footer with no other date signal on that page (D-TRUST-02a and D-TRUST-02c both on the same page).",
        "expected_findings": ["D-TRUST-01", "D-TRUST-02"],
        "expected_non_findings": ["D-ENTITY-01", "D-ENTITY-02", "D-ENTITY-05", "D-TRUST-06"],
        "notes": "D-TRUST-02's two sub-triggers (a and c) may report as one finding or two depending on how detect_trust.py aggregates per-page vs per-subtrigger -- recorded as observed.",
    }
    write_fixture("stale-content", files, expected)


# ===========================================================================
# 9. conflicting-content -- D-TRUST-03 (founded-year entity_fact conflict)
#    + D-ENTITY-04 (address conflict, same org name both nodes -> no
#    legitimate-multi-location suppression).
# ===========================================================================


def build_conflicting_content() -> None:
    brand = "Palisade Outfitters"
    nav = navlinks([("/", "Home"), ("/history.html", "History"), ("/contact.html", "Contact"), ("/careers.html", "Careers")])
    org_a = {"@context": "https://schema.org", "@type": "Organization", "name": brand,
             "address": {"@type": "PostalAddress", "streetAddress": "100 Main St", "addressLocality": "Boulder", "addressRegion": "CO", "postalCode": "80301"}}
    org_b = {"@context": "https://schema.org", "@type": "Organization", "name": brand,
             "address": {"@type": "PostalAddress", "streetAddress": "500 Oak Ave", "addressLocality": "Denver", "addressRegion": "CO", "postalCode": "80202"}}

    files = {
        "index.html": page(
            f"{brand} | Home",
            "Palisade Outfitters sells outdoor gear.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is an outdoor gear store. We sell hiking and "
            f"camping gear. See our <a href=\"history.html\">history</a> or "
            f"<a href=\"contact.html\">contact</a> page.</p></main>",
        ),
        "history.html": page(
            f"History | {brand}",
            "The history of Palisade Outfitters.",
            f"{nav}<h1>{brand}</h1><main><p>Founded in 2008, we've been serving customers "
            f"ever since. See our <a href=\"careers.html\">careers</a> page.</p></main>",
            jsonld=[org_a],
        ),
        "careers.html": page(
            f"Careers | {brand}",
            "Work at Palisade Outfitters.",
            f"{nav}<h1>{brand}</h1><main><p>We have been operating since 2015, expanding across "
            f"three states. See our <a href=\"contact.html\">contact</a> page.</p></main>",
            jsonld=[org_b],
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach Palisade Outfitters.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at hello@example.test or call "
            f"555-772-9090. See our <a href=\"history.html\">history</a>.</p></main>",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "history.html claims 'Founded in 2008'; careers.html claims 'Since our founding in 2015' -- same entity_fact key (founded_year), different values (D-TRUST-03). Two Organization JSON-LD nodes carry the same org name (not distinguishing branch labels) but genuinely different addresses (D-ENTITY-04).",
        "expected_findings": ["D-TRUST-03", "D-ENTITY-04"],
        "expected_non_findings": ["D-ENTITY-01", "D-TRUST-06"],
        "notes": "Contrasts directly with fp-trap-composite's distinct-branch-name multi-location pattern, which must NOT fire D-ENTITY-04.",
    }
    write_fixture("conflicting-content", files, expected)


# ===========================================================================
# 10. strong-disc-weak-engage -- clean crawl/schema/entity/trust, but deep
#     category/product pages give a cold arrival no brand ID and no path
#     context (E-ORIENT-01 + E-ORIENT-03), repeated across multiple pages.
# ===========================================================================


def build_strong_disc_weak_engage() -> None:
    brand = "Foundry Machine Works"
    same = org_jsonld(brand, "https://example.test/")
    nav = navlinks([("/", "Home"), ("/catalog/", "Catalog"), ("/about.html", "About"), ("/contact.html", "Contact")])

    files = {
        "index.html": page(
            f"{brand}",
            "Foundry Machine Works manufactures precision CNC parts.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a manufacturing company. We manufacture "
            f"precision CNC parts for industrial equipment makers. Browse our "
            f"<a href=\"catalog/\">catalog</a> or read <a href=\"about.html\">about us</a>.</p></main>"
            f"{brand_footer(brand)}",
            jsonld=[same],
        ),
        "about.html": page(
            f"{brand}",
            "The team behind Foundry Machine Works.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} has manufactured CNC parts for over a "
            f"decade. See our <a href=\"catalog/\">catalog</a>.</p></main>{brand_footer(brand)}",
            jsonld=[same],
        ),
        "contact.html": page(
            f"{brand}",
            "Reach the Foundry Machine Works sales team.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at sales@example.test or call "
            f"555-228-4040. See our <a href=\"catalog/\">catalog</a>.</p></main>{brand_footer(brand)}",
            jsonld=[same],
        ),
        "catalog/index.html": page(
            "Product Catalog",
            "Browse CNC part categories.",
            f'<nav><a href="/">Home</a></nav><h1>Product Catalog</h1><main>'
            f'<p>Browse our part categories below, or <a href="/contact.html">contact sales</a> '
            f'for a custom quote.</p>'
            f'<p><a href="/catalog/bearings/">Bearings</a></p></main>{brand_footer(brand)}',
        ),
        "catalog/bearings/index.html": page(
            "Bearings Category",
            "Precision bearing assemblies.",
            f'<nav><a href="/">Home</a></nav><h1>Bearings Category</h1><main>'
            f'<p>Precision bearing assemblies for industrial equipment. '
            f'<a href="/catalog/bearings/b-3000.html">See the B-3000 spec sheet</a>, back to the '
            f'<a href="/catalog/">full catalog</a>, or <a href="/contact.html">request a quote</a>.</p></main>{brand_footer(brand)}',
        ),
        "catalog/bearings/b-3000.html": page(
            "B-3000 Spec Sheet",
            "Technical specifications for the B-3000 bearing assembly.",
            f'<nav><a href="/">Home</a></nav><h1>B-3000 Spec Sheet</h1><main>'
            f'<p>Load rating: 4200 N. Bore diameter: 30mm. Outer diameter: 62mm. '
            f'<a href="/contact.html">Request a quote</a> or see the '
            f'<a href="/catalog/bearings/">bearings category</a>.</p></main>{brand_footer(brand)}',
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "Homepage/about/contact (depth 0-1) are brand-clear and well-formed (clean D-CRAWL/D-ENTITY/D-TRUST). The catalog hierarchy (depth 1-3) is discoverable and well-linked (strong 'discoverability') but its category and product pages (depth>=2) state no brand anywhere in title/h1/body-first-800/img-alt, and the site has no breadcrumb anywhere despite a sitewide max depth of 3 (weak 'engagement' -- orientation specifically).",
        "expected_findings": ["E-ORIENT-03"],
        "expected_non_findings": ["D-ENTITY-01", "D-ENTITY-02", "D-ENTITY-04", "D-CRAWL-01", "D-TRUST-06", "E-CONTINUE-01", "E-CONTINUE-02", "E-CONTINUE-03"],
        "confirmed_false_negative": {
            "check": "E-ORIENT-01 (no brand identification on arrival)",
            "why": "This fixture was built to trigger E-ORIENT-01 (deep pages state no brand anywhere) and does not. Root cause confirmed by direct inspection: entity-semantic-audit's _aliases_field() (build_entity_profile.py) dumps EVERY name candidate that isn't the dominant brand name -- i.e. every other page's own title/h1 text sitewide, with no relevance filtering -- into entity_profile.fields.aliases. detect_engagement.py::_brand_tokens() then feeds those aliases back into E-ORIENT-01's own brand-token search. Since a page's own title is always harvested as a name candidate, and any non-dominant candidate becomes a searchable 'alias', a deep page's own distinctive title always self-matches as one of its own 'brand aliases' -- title_hit is trivially True on nearly every page with a real, non-empty <title> that isn't itself the brand name. In practice this makes E-ORIENT-01 unable to fire on any realistically-titled deep page across the whole corpus; it can only fire on a page with no title and no h1 at all, which is a degenerate case distinct from what the check is meant to catch.",
        },
        "notes": "Brand identity for D-ENTITY-01 purposes is carried via JSON-LD (which E-ORIENT-01 never reads) plus the home/about/contact pages -- isolating 'a machine can identify this entity' (clean) from 'a cold human visitor lands on a deep page and cannot tell whose site it is' (the actual defect under test).",
    }
    write_fixture("strong-disc-weak-engage", files, expected)


# ===========================================================================
# 11. weak-disc-strong-engage -- robots.txt disallows a real, linked content
#     path (D-CRAWL-01); the pages that ARE reachable are shallow, brand-
#     clear, and well-connected (strong engagement on what's actually served).
# ===========================================================================


def build_weak_disc_strong_engage() -> None:
    brand = "Ridgeline Outfitting"
    nav = navlinks([("/", "Home"), ("/catalog/", "Catalog"), ("/about.html", "About"), ("/contact.html", "Contact")])
    files = {
        "index.html": page(
            f"{brand} | Home",
            "Ridgeline Outfitting sells outdoor apparel.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is an outdoor apparel store. We sell "
            f"jackets and packs for backcountry travel. Browse the "
            f"<a href=\"catalog/\">catalog</a> or read <a href=\"about.html\">about us</a>.</p></main>"
            f"{brand_footer(brand)}",
        ),
        "about.html": page(
            f"About | {brand}",
            "The story of Ridgeline Outfitting.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} has outfitted backcountry travelers for "
            f"years. See our <a href=\"contact.html\">contact</a> page.</p></main>{brand_footer(brand)}",
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach Ridgeline Outfitting.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at hello@example.test or call "
            f"555-664-2200. See our <a href=\"about.html\">story</a>.</p></main>{brand_footer(brand)}",
        ),
        "catalog/index.html": (
            "unreachable by design: disallowed by robots.txt, must never be fetched"
        ),
        "robots.txt": "User-agent: *\nDisallow: /catalog/\n",
    }
    expected = {
        "description": "robots.txt disallows /catalog/, which the homepage still links to (a real, linked-but-blocked path). The 3 reachable pages (home/about/contact, all depth<=1) are brand-clear, well-connected and terminal-appropriate.",
        "expected_findings": ["D-CRAWL-01"],
        "expected_non_findings": ["E-ORIENT-01", "E-ORIENT-03", "E-CONTINUE-01", "E-CONTINUE-02", "D-ENTITY-01"],
        "notes": "catalog/index.html's placeholder content is never actually served correctly (robots disallows the fetch entirely, so the crawler must never request it) -- its content is irrelevant to the test.",
    }
    write_fixture("weak-disc-strong-engage", files, expected)


# ===========================================================================
# 12. both-weak -- layered problems across all four detector categories on
#     one small, genuinely bad site.
# ===========================================================================


def build_both_weak() -> None:
    brand = "Glenmark Supply"
    nav = navlinks([("/", "Home"), ("/catalog/", "Catalog"), ("/widget.html", "Widget"), ("/gadget.html", "Gadget")])
    modal = (
        '<div class="modal-overlay" role="dialog" aria-modal="true">'
        '<p>Sign up for our newsletter before continuing!</p></div>'
    )
    files = {
        "index.html": page(
            f"{brand} | Shop",
            "Shop Glenmark Supply.",
            f"{nav}<h1>Shop</h1><main><p>Our pricing is currently the best in the industry. "
            f"Browse the <a href=\"catalog/\">catalog</a>, or see the "
            f"<a href=\"widget.html\">widget</a> and <a href=\"gadget.html\">gadget</a> pages.</p>{modal}</main>",
        ),
        "catalog/index.html": (
            "unreachable by design: disallowed by robots.txt"
        ),
        "widget.html": page(
            "Shop Glenmark Supply",
            "Shop Glenmark Supply.",
            '<h1>Widget</h1><main><p>Load rating: 12kg. No further information.</p></main>',
        ),
        "gadget.html": page(
            "Shop Glenmark Supply",
            "Shop Glenmark Supply.",
            '<h1>Gadget</h1><main><p>Load rating: 8kg. No further information.</p></main>',
        ),
        "robots.txt": "User-agent: *\nDisallow: /catalog/\n",
    }
    expected = {
        "description": "robots.txt blocks the /catalog/ path that the homepage links to (D-CRAWL-01). widget.html/gadget.html (both at root, reachable) share an identical title AND description (a real D-EXTRACT-02 pattern, but see confirmed_false_negative), neither states a brand consistently with the homepage, and no page has contact info -- deliberately unpolished on every axis, unlike the other fixtures which isolate one mechanism. Homepage has a time-sensitive 'currently' claim with no date signal anywhere (D-TRUST-01), a blocking modal visible by default (E-ANSWER-02), and every content page is a dead end with no continuation link (E-CONTINUE-02).",
        "expected_findings": ["D-CRAWL-01", "D-TRUST-01", "D-TRUST-06", "D-ENTITY-01", "D-ENTITY-05", "D-ENTITY-06", "E-ANSWER-02", "E-CONTINUE-02"],
        "expected_non_findings": ["D-ENTITY-02"],
        "confirmed_false_negative": {
            "check": "D-EXTRACT-02",
            "why": EXTRACT_RENDER_WIRING_GAP,
        },
        "notes_on_own_authoring": "D-ENTITY-02 does not fire: the homepage h1 is bare 'Shop', and 'shop' is one of entity-semantic-audit's TYPE_KEYWORDS, so the type is considered (weakly) stated even on this deliberately bad site -- another useful orthogonality data point alongside ambiguous-entity's 'platform' case.",
        "notes": "Deliberately dense to observe evidence-prioritization's distribution guard (recalibrates high-tier findings down once >30% of a report's findings would land high+critical) on a genuinely bad, multi-defect site.",
    }
    write_fixture("both-weak", files, expected)


# ===========================================================================
# 13. both-strong -- deep (3-level), well-built site. NON-FINDING: all.
# ===========================================================================


def build_both_strong() -> None:
    brand = "Meridian Analytics"
    same = org_jsonld(brand, "https://example.test/")
    nav = navlinks([("/", "Home"), ("/docs/", "Docs"), ("/about.html", "About"), ("/contact.html", "Contact")])
    breadcrumb = lambda *crumbs: '<nav aria-label="breadcrumb">' + " &gt; ".join(f'<a href="{h}">{t}</a>' if h else t for t, h in crumbs) + "</nav>"

    files = {
        "index.html": page(
            f"{brand}",
            "Meridian Analytics is a data platform for finance teams.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a data analytics company. We build a "
            f"data platform for finance teams. Read our <a href=\"docs/\">documentation</a> or "
            f"<a href=\"about.html\">learn about us</a>.</p></main>{brand_footer(brand)}",
            jsonld=[same],
        ),
        "about.html": page(
            f"{brand}",
            "The team behind Meridian Analytics.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} was built by a team of finance and data "
            f"engineers. See our <a href=\"contact.html\">contact</a> page.</p></main>{brand_footer(brand)}",
            jsonld=[same],
        ),
        "contact.html": page(
            f"{brand}",
            "Reach the Meridian Analytics team.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at hello@example.test or call "
            f"555-882-1100. See our <a href=\"docs/\">documentation</a>.</p></main>{brand_footer(brand)}",
            jsonld=[same],
        ),
        "docs/index.html": page(
            f"Documentation | {brand}",
            "Meridian Analytics documentation home.",
            f'{navlinks([("/", "Home"), ("/about.html", "About")])}<h1>{brand}</h1>'
            f'{breadcrumb(("Home", "/"), ("Documentation", None))}'
            f'<main><p>Start with the <a href="/docs/getting-started/">getting started guide</a>.</p>'
            f'</main>{brand_footer(brand)}',
            jsonld=[same],
        ),
        "docs/getting-started/index.html": page(
            f"Getting Started | {brand}",
            "Get started with Meridian Analytics.",
            f'{navlinks([("/", "Home"), ("/docs/", "Docs")])}<h1>{brand}</h1>'
            f'{breadcrumb(("Home", "/"), ("Documentation", "/docs/"), ("Getting Started", None))}'
            f'<main><p>Connect a data source, then see '
            f'<a href="/docs/getting-started/connect.html">connecting a data source</a> for details. '
            f'Back to the <a href="/docs/">documentation home</a>.</p></main>{brand_footer(brand)}',
            jsonld=[same],
        ),
        "docs/getting-started/connect.html": page(
            f"Connect a Data Source | {brand}",
            "How to connect a data source in Meridian Analytics.",
            f'{navlinks([("/", "Home"), ("/docs/", "Docs")])}<h1>{brand}</h1>'
            f'{breadcrumb(("Home", "/"), ("Documentation", "/docs/"), ("Getting Started", "/docs/getting-started/"), ("Connect", None))}'
            f'<main><p>Go to Settings &gt; Data Sources and choose your warehouse. '
            f'Back to <a href="/docs/getting-started/">getting started</a> or the '
            f'<a href="/docs/">documentation home</a>.</p></main>{brand_footer(brand)}',
            jsonld=[same],
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "A deep (3-level: /docs/getting-started/connect.html), well-built site: consistent brand everywhere, explicit breadcrumbs on every depth>=2 doc page, working continuation links, unique titles/descriptions, contact info, offering stated, clean robots.",
        "expected_findings": [],
        "expected_non_findings": ["E-ORIENT-01", "E-ORIENT-03", "E-CONTINUE-01", "E-CONTINUE-02", "E-CONTINUE-03", "D-ENTITY-01", "D-EXTRACT-02", "D-CRAWL-01"],
        "notes": "Directly tests whether depth/complexity alone inflates findings on an otherwise well-built site -- a key false-positive-at-scale concern distinct from clean-static's shallow baseline.",
    }
    write_fixture("both-strong", files, expected)


# ===========================================================================
# 14. deep-page-no-orientation -- ONE specific deep page isolates E-ORIENT-01
#     + E-ORIENT-03 + E-ORIENT-04 (broken same-page fragment link) together,
#     in an otherwise well-connected documentation site.
# ===========================================================================


def build_deep_page_no_orientation() -> None:
    brand = "Lumen Cloud"
    same = org_jsonld(brand, "https://example.test/")
    nav_top = navlinks([("/", "Home"), ("/docs/", "Docs"), ("/docs/guides/", "Guides"), ("/contact.html", "Contact")])
    files = {
        "index.html": page(
            f"{brand}",
            "Lumen Cloud documentation and guides.",
            f"{nav_top}<h1>{brand}</h1><main><p>{brand} is a cloud hosting company. We provide "
            f"managed cloud infrastructure. Read our <a href=\"docs/\">documentation</a>.</p></main>"
            f"{brand_footer(brand)}",
            jsonld=[same],
        ),
        "contact.html": page(
            f"{brand}",
            "Reach the Lumen Cloud support team.",
            f"{nav_top}<h1>{brand}</h1><main><p>Email {brand} at support@example.test or call "
            f"555-909-1200. See our <a href=\"docs/\">documentation</a>.</p></main>{brand_footer(brand)}",
            jsonld=[same],
        ),
        "docs/index.html": page(
            f"Documentation | {brand}",
            "Lumen Cloud documentation home.",
            f'{nav_top}<h1>{brand}</h1><main><p>See our '
            f'<a href="/docs/guides/">guides</a> for common tasks.</p></main>{brand_footer(brand)}',
        ),
        "docs/guides/index.html": page(
            f"Guides | {brand}",
            "Lumen Cloud how-to guides.",
            f'{nav_top}<h1>{brand}</h1><main><p>See '
            f'<a href="/docs/guides/rate-limits.html">rate limit configuration</a>, or back to the '
            f'<a href="/docs/">documentation home</a>.</p></main>{brand_footer(brand)}',
        ),
        "docs/guides/rate-limits.html": page(
            "Rate Limit Configuration",
            "How to configure request rate limits.",
            '<main><p>Set the <code>max_requests</code> field in your config file to the '
            'desired ceiling. Values above 10000 require a support ticket. See also '
            '<a href="#see-also">related settings</a> below.</p>'
            '<p>Need help? <a href="/docs/guides/">back to guides</a>.</p></main>',
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "rate-limits.html (depth 3) has no nav, no brand name anywhere (title/h1/body/img-alt), no breadcrumb, and a same-page fragment link to #see-also that has no matching id anywhere on the page. The rest of the site (depth 0-2) is well-connected, brand-clear, and offers a working continuation link back to the guides hub.",
        "expected_findings": ["E-ORIENT-03", "E-ORIENT-04"],
        "expected_non_findings": ["D-ENTITY-01", "D-ENTITY-04", "D-TRUST-06", "E-CONTINUE-02", "E-CONTINUE-03"],
        "confirmed_false_negative": {
            "check": "E-ORIENT-01 (no brand identification on arrival)",
            "why": "Same confirmed root cause as strong-disc-weak-engage: rate-limits.html's own title ('Rate Limit Configuration') is harvested as a name candidate sitewide, lands in entity_profile.fields.aliases (every non-dominant candidate, unfiltered), and detect_engagement.py::_brand_tokens() feeds it back into this exact page's own brand-token search -- the page's title trivially self-matches as its own 'alias', so E-ORIENT-01 never fires despite the page genuinely stating no brand anywhere.",
        },
        "notes": "Isolates the orientation mechanism on a single page rather than strong-disc-weak-engage's broader multi-page pattern; also includes E-ORIENT-04 (broken internal fragment), not exercised elsewhere in the corpus.",
    }
    write_fixture("deep-page-no-orientation", files, expected)


# ===========================================================================
# 15. single-page-site -- minimum-corpus rule: below 3 pages, cross-page
#     checks must disable rather than fabricate findings from n=1.
# ===========================================================================


def build_single_page_site() -> None:
    brand = "Harlow Bookbinding"
    files = {
        "index.html": page(
            f"{brand}",
            "Harlow Bookbinding is a one-person bookbinding studio.",
            f"<h1>{brand}</h1><main><p>{brand} is a bookbinding studio. We provide hand "
            f"bookbinding and restoration services. Email {brand} at harlow@example.test or call "
            f"555-303-9090 to discuss a project.</p></main>",
            jsonld=[org_jsonld(brand, "https://example.test/")],
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": "A genuinely single-page site with no internal links at all.",
        "expected_findings": [],
        "expected_coverage": ["INSUFFICIENT_PAGES"],
        "expected_non_findings": ["D-ENTITY-04", "D-TRUST-03", "E-CONTINUE-03"],
        "notes": "Verifies the minimum-corpus rule (below 3 crawled pages, cross-page consistency checks disable and the coverage block says so) rather than fabricating a conflict/consistency finding from a single data point, and that a page with zero outgoing links doesn't crash single-page-only checks.",
    }
    write_fixture("single-page-site", files, expected)


# ===========================================================================
# 16. large-site -- ~45 templated product pages; the default 30-page crawl
#     budget is exhausted mid-crawl. Tests aggregation-by-template-cluster
#     (one D-EXTRACT-02 finding, not 28) and the empirically-dead D-CRAWL-14.
# ===========================================================================


def build_large_site() -> None:
    brand = "Northwind Supply"
    n_products = 45
    nav = navlinks([("/", "Home"), ("/catalog.html", "Catalog"), ("/about.html", "About")])

    product_links = "".join(f'<a href="/product/{i}.html">Product {i}</a> ' for i in range(1, n_products + 1))
    facet_links = "".join(f'<a href="/catalog.html?sort={s}">{s}</a> ' for s in ("price", "name", "rating", "newest"))

    files = {
        "index.html": page(
            f"{brand} | Home",
            "Northwind Supply sells industrial parts online.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is an industrial parts store. We sell "
            f"fasteners and hardware in bulk. Browse our <a href=\"catalog.html\">full catalog</a> "
            f"or read <a href=\"about.html\">about us</a>.</p></main>{brand_footer(brand)}",
        ),
        "about.html": page(
            f"About | {brand}",
            "The story of Northwind Supply.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} has supplied industrial parts for years. "
            f"Email {brand} at sales@example.test or call 555-500-1000. "
            f"See our <a href=\"catalog.html\">catalog</a>.</p></main>{brand_footer(brand)}",
        ),
        "catalog.html": page(
            f"Catalog | {brand}",
            "Browse the full Northwind Supply product catalog.",
            f"{nav}<h1>{brand}</h1><main><p>Sort the catalog: {facet_links}</p>"
            f"<p>{product_links}</p></main>{brand_footer(brand)}",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    for i in range(1, n_products + 1):
        product = {"@context": "https://schema.org", "@type": "Product", "name": f"Product {i}",
                   "offers": {"@type": "Offer", "price": "19.99", "priceCurrency": "USD"}}
        files[f"product/{i}.html"] = page(
            "Product | Northwind Supply",
            "Buy quality products at Northwind Supply.",
            f'<nav><a href="/">Home</a> <a href="/catalog.html">Catalog</a></nav>'
            f'<h1>{brand}</h1><main><p>Product {i} is a durable industrial part. '
            f'<a href="/catalog.html">Back to catalog</a>.</p></main>{brand_footer(brand)}',
            jsonld=[product],
        )

    expected = {
        "description": f"{n_products} templated /product/N.html pages, all sharing a byte-identical title and meta description (a realistic templating mistake), linked from one catalog.html hub which also carries several ?sort= facet-parameter links. Default crawl budget is 30 pages; BFS order (home, about, catalog, then the ?sort= facet links, then products 1..N) means the crawl exhausts its budget partway through the product list.",
        "expected_findings": [],
        "expected_coverage": ["BUDGET_EXHAUSTED"],
        "structurally_untestable": {
            "D-CRAWL-14": "Requires store['capabilities']['crawl']['budget_exhausted'] == true, but lib/site_observer/collect.py never writes a 'crawl' key into store['capabilities'] at all (only 'renderer' and 'corroboration' are ever set) -- confirmed by grep across the whole repo, this flag is set only in detect_crawl.py's own unit tests, never by real collection. D-CRAWL-14 cannot fire in any real audit regardless of how much of the crawl budget facet URLs consume.",
        },
        "confirmed_false_negative": {
            "check": "D-EXTRACT-02 aggregation across /product/N.html",
            "why": (
                EXTRACT_RENDER_WIRING_GAP + " This fixture was ALSO built to verify PROJECT_CONTEXT.md's Defect-D "
                "promise (one aggregated finding per template cluster, not per URL) using the single most common "
                "real-world templated-URL shape: a numeric ID immediately followed by a file extension in the same "
                "path segment (/product/1.html, /product/2.html, ...). A second, independent bug means this "
                "specific check would still fail to aggregate correctly even if the wiring gap above were fixed: "
                "lib/site_observer/crawl.py's template_shape() collapses a path segment to '#' only via "
                "`_NUMERIC_SEGMENT_RE = re.compile(r'^\\d+$')` (and equivalent hex/UUID patterns), which requires the "
                "ENTIRE segment to be purely numeric. '1.html' fails that match (the extension makes it non-numeric), "
                "so template_shape('/product/1.html') returns '/product/1.html' unchanged -- verified directly: every "
                "product page gets its own distinct 'cluster' of size one. check_d_extract_02's duplicate-title "
                "branch requires >=2 URLs in the SAME cluster (`if len(urls) < 2: continue`), so it would silently "
                "never fire for this entire, very common URL family even with detect_extract() correctly invoked. "
                "(Calling detect_extract.detect_extract(store) directly on this fixture's real collected store "
                "confirms both bugs at once: it returns one D-EXTRACT-02 finding, but only for the ?sort= facet-query "
                "duplicates -- an accidental, unrelated collision from the static test server returning catalog.html "
                "unchanged for every query variant -- never for the deliberately-injected /product/# defect.)"
            ),
        },
        "notes": "Neither bug is local to this one check: the wiring gap zeroes out all 14 D-RENDER/D-EXTRACT checks marketplace-wide, and group_by_cluster()'s extension-blind numeric matching is used by nearly every D-CRAWL/D-EXTRACT check, so any site using '<numeric-id>.ext' URLs (WordPress, most CMS/e-commerce platforms) would additionally get per-URL noise instead of the one-finding-per-template-cluster the architecture promises, for every one of those checks.",
    }
    write_fixture("large-site", files, expected)


# ===========================================================================
# 17. unusual-site-structure -- structural edge cases: a 3-hop redirect chain
#     (fires), a 1-hop redirect (must not fire), a soft-404, hreflang-less
#     locale variants, and numeric-ID template clustering.
# ===========================================================================


def build_unusual_site_structure() -> None:
    brand = "Ferro Analytics"
    nav = navlinks([
        ("/", "Home"), ("/about.html", "About"), ("/contact.html", "Contact"),
        ("/article/101.html", "Article 101"), ("/article/202.html", "Article 202"), ("/article/303.html", "Article 303"),
        ("/en/pricing.html", "Pricing (EN)"), ("/fr/pricing.html", "Pricing (FR)"),
        ("/old-page.html", "Old Page (2-hop redirect)"), ("/a.html", "3-hop redirect"),
        ("/gone.html", "Discontinued"),
    ])

    def article(i: int) -> str:
        return page(
            f"Article {i} | {brand}",
            f"Analysis piece number {i} from Ferro Analytics.",
            f'{nav}<h1>{brand}</h1><main><p>Analysis piece number {i}. See '
            f'<a href="/about.html">about us</a>.</p></main>{brand_footer(brand)}',
        )

    files = {
        "index.html": page(
            f"{brand} | Home",
            "Ferro Analytics publishes industrial market analysis.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} is a market research company. We provide "
            f"industrial market analysis reports. See our <a href=\"about.html\">about</a> page.</p></main>"
            f"{brand_footer(brand)}",
        ),
        "about.html": page(
            f"About | {brand}",
            "About Ferro Analytics.",
            f"{nav}<h1>{brand}</h1><main><p>{brand} has published market analysis for years. "
            f"See our <a href=\"contact.html\">contact</a> page.</p></main>{brand_footer(brand)}",
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach Ferro Analytics.",
            f"{nav}<h1>{brand}</h1><main><p>Email {brand} at hello@example.test or call "
            f"555-701-6060. See our <a href=\"about.html\">about</a> page.</p></main>{brand_footer(brand)}",
        ),
        "article/101.html": article(101),
        "article/202.html": article(202),
        "article/303.html": article(303),
        "en/pricing.html": page(
            f"Pricing | {brand}",
            "Ferro Analytics pricing (English).",
            f'{nav}<h1>{brand}</h1><main><p>Plans start at $99/month. See '
            f'<a href="/contact.html">contact us</a>.</p></main>{brand_footer(brand)}',
        ),
        "fr/pricing.html": page(
            f"Tarifs | {brand}",
            "Tarifs Ferro Analytics (francais).",
            f'{nav}<h1>{brand}</h1><main><p>Les forfaits commencent a 99 $/mois. Voir '
            f'<a href="/contact.html">nous contacter</a>.</p></main>{brand_footer(brand)}',
        ),
        "new-page.html": page(
            f"New Page | {brand}",
            "The destination of a 2-hop redirect.",
            f'{nav}<h1>{brand}</h1><main><p>You have arrived via a short redirect. See '
            f'<a href="/about.html">about us</a>.</p></main>{brand_footer(brand)}',
        ),
        "d.html": page(
            f"Destination | {brand}",
            "The destination of a 3-hop redirect chain.",
            f'{nav}<h1>{brand}</h1><main><p>You have arrived via a 3-hop redirect chain. See '
            f'<a href="/about.html">about us</a>.</p></main>{brand_footer(brand)}',
        ),
        "gone.html": page(
            f"{brand}",
            "This page is no longer available.",
            "<main><p>Sorry, this page no longer available.</p></main>",
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    server_config = {
        "overrides": {
            "/old-page.html": {"status": 302, "headers": {"Location": "/new-page.html"}},
            "/a.html": {"status": 302, "headers": {"Location": "/b.html"}},
            "/b.html": {"status": 302, "headers": {"Location": "/c.html"}},
            "/c.html": {"status": 302, "headers": {"Location": "/d.html"}},
        }
    }
    expected = {
        "description": "Numeric-ID article URLs (/article/101.html etc, should cluster as /article/# per template_shape). /old-page.html -> /new-page.html is a single-hop redirect (must NOT fire D-CRAWL-05). /a.html -> /b.html -> /c.html -> /d.html is a 3-hop chain (must fire D-CRAWL-05). /en/pricing.html and /fr/pricing.html are locale variants with no hreflang tag anywhere (D-CRAWL-11). /gone.html returns HTTP 200 with a short soft-404 phrase (D-CRAWL-04).",
        "expected_findings": ["D-CRAWL-05", "D-CRAWL-11", "D-CRAWL-04", "E-CONTINUE-02"],
        "expected_non_findings": ["D-ENTITY-01", "D-ENTITY-06", "D-TRUST-06"],
        "notes": "The 1-hop /old-page.html redirect is the FP-adjacent guardrail check within this fixture: D-CRAWL-05 needs >=3 hops or a loop, so a normal single redirect must stay silent. scope.template_clusters in the report should show /article/# as one cluster of 3, not 3 separate shapes -- inspected directly, not asserted as a 'finding'.",
    }
    write_fixture("unusual-site-structure", files, expected, server_config=server_config)


# ===========================================================================
# 18. fp-trap-composite -- dedicated false-positive regression suite. Every
#     pattern here looks like a defect but is a legitimate, common practice;
#     ANY finding in this fixture is a false positive by construction.
# ===========================================================================


def build_fp_trap_composite() -> None:
    brand = "Cobalt Field Services"
    nav = navlinks([
        ("/", "Home"), ("/docs/", "Docs"), ("/docs/setup.html", "Setup"),
        ("/locations.html", "Locations"), ("/contact.html", "Contact"), ("/news/2019-05-01-launch.html", "Archive: 2019 Launch"),
    ])
    org_downtown = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "Cobalt Field Services - Downtown",
                    "address": {"@type": "PostalAddress", "streetAddress": "12 Canal St", "addressLocality": "Portland", "addressRegion": "OR"}}
    org_airport = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "Cobalt Field Services - Airport",
                   "address": {"@type": "PostalAddress", "streetAddress": "900 Airport Way", "addressLocality": "Portland", "addressRegion": "OR"}}

    files = {
        "index.html": page(
            f"{brand}",
            "Cobalt Field Services documentation and support portal.",
            f'{nav}<h1>{brand}</h1><main><p>{brand} is a field-service software company. '
            f'We provide field-service scheduling software for contractors. '
            f'Plans start at $49/month (EU pricing: &euro;59/month). See our '
            f'<a href="/docs/">documentation</a> or <a href="/locations.html">locations</a>.</p>'
            f'<p>Sales: 555-123-4567. Support: 555-987-6543.</p></main>'
            f'<footer>&copy; 2019 {brand}</footer><p>Updated: January 15, 2026.</p>',
        ),
        "docs/index.html": page(
            f"Documentation | {brand}",
            "Cobalt Field Services documentation home.",
            f'{nav}<h1>{brand}</h1><main><p>See the <a href="/docs/setup.html">setup guide</a> '
            f'to get started. Pricing details: $49/month (EU: &euro;59/month).</p></main>{brand_footer(brand)}',
        ),
        "docs/setup.html": page(
            f"Setup Guide | {brand}",
            "How to set up Cobalt Field Services.",
            f'{nav}<h1>{brand}</h1><main><p>Install the agent, then register your API key. '
            f'Sales inquiries: 555-123-4567. Back to <a href="/docs/">documentation</a>.</p></main>{brand_footer(brand)}',
        ),
        "locations.html": page(
            f"Locations | {brand}",
            "Cobalt Field Services office locations.",
            f'{nav}<h1>{brand}</h1><main><p>We operate two Portland-area offices. See our '
            f'<a href="/contact.html">contact</a> page.</p>'
            f'<script type="application/ld+json">{json.dumps(org_downtown)}</script>'
            f'<script type="application/ld+json">{json.dumps(org_airport)}</script></main>{brand_footer(brand)}',
        ),
        "contact.html": page(
            f"Contact | {brand}",
            "Reach Cobalt Field Services.",
            f'{nav}<h1>{brand}</h1><main><p>Email {brand} at hello@example.test or call '
            f'555-123-4567. See our <a href="/locations.html">locations</a>.</p></main>{brand_footer(brand)}',
        ),
        "news/2019-05-01-launch.html": page(
            f"We're Launching! | {brand}",
            "Announcing the Cobalt Field Services launch event.",
            f'<nav><a href="/">Home</a></nav><h1>{brand}</h1><main>'
            f'<p>Join us for our upcoming launch event on May 20, 2019, at our downtown office. '
            f'Back to <a href="/">home</a>.</p></main>',
            extra_head='<meta property="article:published_time" content="2019-05-01">',
            jsonld=[{"@context": "https://schema.org", "@type": "Article", "headline": "We're Launching!", "datePublished": "2019-05-01"}],
        ),
        "robots.txt": ROBOTS_ALLOW_ALL,
    }
    expected = {
        "description": (
            "Nine simultaneous false-positive traps: (1) archival news post dated 2019-05-01 discussing "
            "a forward-framed 'upcoming' event on 2019-05-20 -- the page's own date precedes the event, so "
            "not actually stale; (2) regional pricing $49/EUR59 on two pages -- price is never extracted as "
            "an entity_fact; (3) sales vs support phone numbers on different pages -- phone is never extracted "
            "as an entity_fact; (4) two LocalBusiness nodes with distinct branch names ('- Downtown' / '- Airport') "
            "and genuinely different addresses -- legitimate multi-location, not a conflict; (5) title/h1 always "
            "'Cobalt Field Services' with no legal-suffix variant, so no D-ENTITY-01 risk; (6) documentation "
            "archetype (>=30% /docs/ paths) with no offering-verb sentence -- D-ENTITY-06 is archetype-suppressed "
            "for documentation; (7) no sitemap.xml on a small, fully-interlinked site with zero orphans; (8) an "
            "old (c) 2019 footer year paired with a fresh 'Updated: January 15, 2026' freshness-labeled date on "
            "the same page -- a real date signal suppresses the copyright-only staleness path; (9) contact info "
            "present so D-TRUST-06 stays silent despite the documentation archetype."
        ),
        "expected_findings": [],
        "notes": "Any finding in this fixture is a false positive by construction -- this is the corpus's single most direct false-positive-rate measurement.",
    }
    write_fixture("fp-trap-composite", files, expected)


# ===========================================================================
# 19 (bonus). robots-5xx -- degraded-mode / D-CRAWL-15. Not one of the 18
#     requested categories, but load-bearing for Defect G (a schema-valid
#     report under catastrophic failure) and cheap to add.
# ===========================================================================


def build_robots_5xx() -> None:
    files = {
        "index.html": page(
            "Unreachable | Example",
            "This page should never actually be fetched.",
            "<main><p>If this text appears in a report's evidence, the crawl did not "
            "correctly stop at the robots.txt failure.</p></main>",
        ),
    }
    server_config = {"overrides": {"/robots.txt": {"status": 500, "body": "internal server error"}}}
    expected = {
        "description": "robots.txt itself returns HTTP 500. The crawl must stop before fetching anything, per lib/site_observer/collect.py's _robots_degradation.",
        "expected_findings": ["D-CRAWL-15"],
        "expected_coverage": ["ROBOTS_DISALLOWED"],
        "notes": "D-CRAWL-15 is one of exactly four checks allowlisted for 'critical' severity (severity-matrix.md) and must survive the confidence-driven-demotion / distribution-guard pipeline untouched. scope.pages_crawled should be 0 and scope.disallowed should be true; the report must still be schema-valid (Defect G / degraded-mode.md).",
    }
    write_fixture("robots-5xx", files, expected, server_config=server_config)


if __name__ == "__main__":
    build_clean_static()
    build_js_render_gap()
    build_facts_render_only()
    build_image_locked_facts()
    build_no_structured_data_ok()
    build_invalid_structured_data()
    build_ambiguous_entity()
    build_stale_content()
    build_conflicting_content()
    build_strong_disc_weak_engage()
    build_weak_disc_strong_engage()
    build_both_weak()
    build_both_strong()
    build_deep_page_no_orientation()
    build_single_page_site()
    build_large_site()
    build_unusual_site_structure()
    build_fp_trap_composite()
    build_robots_5xx()
    print("All 19 fixtures written.")
