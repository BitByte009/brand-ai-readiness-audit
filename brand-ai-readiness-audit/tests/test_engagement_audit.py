"""Tests for the engagement-audit skill.

Unit tests per check (fire + suppress, i.e. both good and bad engagement
patterns), edge cases (flat sites, terminal pages, missing renders, single-page
sites), and regression tests for whole-site scenarios that must stay quiet.

Run from the marketplace root: `python -m pytest tests/test_engagement_audit.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "engagement-audit" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _engagement_util as eu  # noqa: E402
import detect_engagement as de  # noqa: E402

from lib.common.observations import make_observation  # noqa: E402

REPORT_SCHEMA = json.loads((ROOT / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
FINDING_SCHEMA = REPORT_SCHEMA["$defs"]["finding"]

LOREM = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod. " * 8  # > 400 chars


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


def classification_obs(url, page_type):
    return make_observation("PAGE_CLASSIFICATION", url, {"page_type": page_type})


def probe_obs(url, questions):
    return make_observation("PROBE", url, {"questions": questions, "source_text_hash": "deadbeef"})


def engagement_q(question_id, answered, answer=None, evidence_span=None, relevant=True):
    return {"id": question_id, "category": "engagement", "answered": answered, "answer": answer, "evidence_span": evidence_span, "relevant": relevant}


def any_q(question_id, answered, evidence_span, relevant=True, category="factual"):
    return {"id": question_id, "category": category, "answered": answered, "evidence_span": evidence_span, "relevant": relevant}


def page_html(title="Acme", logo_alt=None, jsonld=None, body_extra="", body_text="", h1=None):
    head = f"<title>{title}</title>"
    if jsonld is not None:
        head += f'<script type="application/ld+json">{json.dumps(jsonld)}</script>'
    logo = f'<img src="logo.png" alt="{logo_alt}">' if logo_alt else ""
    heading = title if h1 is None else h1
    body = f"<h1>{heading}</h1>{logo}<p>{body_text}</p>{body_extra}"
    return f"<html><head>{head}</head><body>{body}</body></html>"


ENTITY_PROFILE = {"fields": {"canonical_name": {"value": "Acme"}, "aliases": {"value": ""}}}


@pytest.mark.parametrize("brand,unrelated", [("AI", "Training"), ("Arc", "Research"), ("One", "Someone")])
def test_short_brands_do_not_match_inside_unrelated_words(brand, unrelated):
    html = page_html(title=unrelated, logo_alt=unrelated, body_text=unrelated)
    assert not any(eu.brand_token_positions(html, unrelated, [brand]).values())
    assert eu.brand_token_positions(page_html(body_text=brand + " — welcome"), "", [brand])["body"]


@pytest.mark.parametrize("base,target,expected", [
    ("https://museum.co.uk/", "https://other.co.uk/tickets", "external"),
    ("https://tenant.example.net/", "https://other.example.net/start", "external"),
    ("https://museum.co.uk/", "https://tickets.museum.co.uk/start", "internal_content"),
    ("https://www.museum.co.uk/", "https://museum.co.uk/visit", "internal_content"),
])
def test_continuation_host_scope_does_not_guess_registrable_domains(base, target, expected):
    assert eu.classify_link({"href": target, "text": "Continue", "rel": []}, base) == expected


def test_query_addressed_content_is_not_automatically_utility():
    assert not eu.is_utility_path("https://example.com/read?id=42")


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
# Unit tests -- E-ORIENT-01
# ---------------------------------------------------------------------------


def test_e_orient_01_fires_when_no_brand_token_anywhere():
    html = page_html(title="Blog Post", body_text="Some content with no brand mention at all here today.")
    store = make_store([fetch_obs("https://example.com/blog/post", html)])

    findings = de.check_e_orient_01(store, ENTITY_PROFILE)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_e_orient_01_never_fires_with_brand_in_title():
    html = page_html(title="Acme - Blog Post", body_text="Some content here today.")
    store = make_store([fetch_obs("https://example.com/blog/post", html)])

    assert de.check_e_orient_01(store, ENTITY_PROFILE) == []


def test_e_orient_01_never_fires_with_brand_in_logo_alt():
    html = page_html(title="Blog Post", logo_alt="Acme logo", body_text="Some content here today.")
    store = make_store([fetch_obs("https://example.com/blog/post", html)])

    assert de.check_e_orient_01(store, ENTITY_PROFILE) == []


def test_e_orient_01_never_fires_on_homepage_depth():
    html = page_html(title="Blog Post", body_text="Some content with no brand mention at all here today.")
    store = make_store([fetch_obs("https://example.com/", html)])

    assert de.check_e_orient_01(store, ENTITY_PROFILE) == []


def test_e_orient_01_never_fires_without_entity_profile():
    html = page_html(title="Blog Post", body_text="Some content with no brand mention here today.")
    store = make_store([fetch_obs("https://example.com/blog/post", html)])

    assert de.check_e_orient_01(store, None) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-ORIENT-03
# ---------------------------------------------------------------------------


def test_e_orient_03_fires_on_deep_page_with_no_breadcrumb():
    deep = page_html(title="Post", body_text=LOREM)
    hub = page_html(title="2024", body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/2024/post", deep),
            fetch_obs("https://example.com/blog/2024/", hub),
        ]
    )

    findings = de.check_e_orient_03(store)
    hits = [f for f in findings if "post" in f["source_urls"][0]]
    assert len(hits) == 1
    assert_finding_shape(hits[0])


def test_e_orient_03_never_fires_on_flat_site():
    a = page_html(title="A", body_text=LOREM)
    b = page_html(title="B", body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/a", a), fetch_obs("https://example.com/b", b)])

    assert de.check_e_orient_03(store) == []


def test_e_orient_03_never_fires_with_breadcrumb_jsonld():
    deep = page_html(title="Post", jsonld={"@type": "BreadcrumbList", "itemListElement": []}, body_text=LOREM)
    hub = page_html(title="2024", jsonld={"@type": "BreadcrumbList", "itemListElement": []}, body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/2024/post", deep),
            fetch_obs("https://example.com/blog/2024/", hub),
        ]
    )

    assert de.check_e_orient_03(store) == []


def test_e_orient_03_never_fires_with_textual_breadcrumb():
    deep = page_html(title="Post", body_text="Home > Blog > Post " + LOREM)
    hub = page_html(title="2024", body_text="Home > Blog " + LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/2024/post", deep),
            fetch_obs("https://example.com/blog/2024/", hub),
        ]
    )

    assert de.check_e_orient_03(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-ORIENT-04
# ---------------------------------------------------------------------------


def test_e_orient_04_fires_on_unresolved_fragment():
    source = page_html(title="A", body_extra='<a href="/other#missing">Jump</a>', body_text=LOREM)
    target = page_html(title="B", body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/a", source), fetch_obs("https://example.com/other", target)])

    findings = de.check_e_orient_04(store)
    assert len(findings) == 1
    assert_finding_shape(findings[0])
    assert_evidence_binds(store, findings)


def test_e_orient_04_never_fires_when_fragment_resolves():
    source = page_html(title="A", body_extra='<a href="/other#section">Jump</a>', body_text=LOREM)
    target = page_html(title="B", body_extra='<h2 id="section">Section</h2>', body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/a", source), fetch_obs("https://example.com/other", target)])

    assert de.check_e_orient_04(store) == []


def test_e_orient_04_never_fires_when_target_not_crawled():
    source = page_html(title="A", body_extra='<a href="/uncrawled#missing">Jump</a>', body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/a", source)])

    assert de.check_e_orient_04(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-ANSWER-01
# ---------------------------------------------------------------------------


def test_e_answer_01_fires_on_clear_title_body_mismatch():
    html = page_html(
        title="10 Best Hiking Boots for Winter",
        h1="Quarterly Investor Update",
        body_text="Our quarterly financial results show strong revenue growth across all regions. " + LOREM,
    )
    store = make_store([fetch_obs("https://example.com/hiking-boots", html)])

    findings = de.check_e_answer_01(store)
    assert len(findings) == 1
    assert findings[0]["severity"] == "medium"
    assert findings[0]["confidence"] == "medium"
    assert_finding_shape(findings[0])


def test_e_answer_01_never_fires_when_title_matches_body():
    html = page_html(title="Hiking Boots Guide", body_text="This guide covers the best hiking boots for winter. " + LOREM)
    store = make_store([fetch_obs("https://example.com/hiking-boots", html)])

    assert de.check_e_answer_01(store) == []


def test_e_answer_01_never_fires_on_short_listing_page():
    html = page_html(title="Totally Unrelated Title Here", body_text="Short.")
    store = make_store([fetch_obs("https://example.com/list", html)])

    assert de.check_e_answer_01(store) == []


def test_e_answer_01_never_fires_when_probe_disagrees():
    """Same deterministic-miss setup as the 'fires' test above, but the probe
    (which reads the full rendered text, not just the h1 proxy) confirms the
    title's topic really is covered -- the probe's confirmation overrides the
    deterministic miss rather than letting it fire on thin evidence."""
    url = "https://example.com/hiking-boots"
    html = page_html(
        title="10 Best Hiking Boots for Winter",
        h1="Quarterly Investor Update",
        body_text="Our quarterly financial results show strong revenue growth. " + LOREM,
    )
    store = make_store(
        [
            fetch_obs(url, html),
            probe_obs(url, [engagement_q("Q5", True, answer="This page is about the best hiking boots for winter")]),
        ]
    )

    assert de.check_e_answer_01(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-ANSWER-02
# ---------------------------------------------------------------------------


# E-ANSWER-01 compares a title against its body by word overlap. When that
# comparison could not see a script, overlap was always zero and the check
# fired on every content page of an entire language -- a systematic false
# positive on unseen sites, not a missed edge case. These use scripts that are
# structurally different from each other and from the Latin fixtures above:
# a non-Latin alphabet that uses spaces, a script with no spaces at all, and
# accented Latin, where the old tokenizer split words at the accent.

MATCHING_PAGES = {
    "greek": (
        "Ρουλεμάν ακριβείας για μηχανουργεία",
        "Πουλάμε ρουλεμάν ακριβείας σε μηχανουργεία στην Ελλάδα. Τα ρουλεμάν αποστέλλονται "
        "την επόμενη εργάσιμη ημέρα από την αποθήκη μας. Διαθέτουμε ρουλεμάν βαθιάς αύλακας "
        "και κωνικά ρουλεμάν ακριβείας για μηχανουργεία σε όλη την Ελλάδα και την Κύπρο. ",
    ),
    "japanese": (
        "機械工場向けの精密ベアリング",
        "当社は機械工場向けの精密ベアリングを販売しています。在庫のある精密ベアリングは翌営業日に"
        "倉庫から発送されます。深溝玉軸受と円すいころ軸受の両方を機械工場向けに取り揃えています。",
    ),
    "french": (
        "Roulements de précision pour ateliers",
        "Nous vendons des roulements de précision pour ateliers de mécanique en France. Les "
        "roulements de précision en stock sont expédiés le jour ouvrable suivant depuis notre "
        "entrepôt. Nous proposons des roulements à billes et des roulements coniques. ",
    ),
}


@pytest.mark.parametrize("script", sorted(MATCHING_PAGES), ids=sorted(MATCHING_PAGES))
def test_e_answer_01_never_fires_when_a_non_ascii_title_matches_its_body(script):
    title, body = MATCHING_PAGES[script]
    html = page_html(title=title, body_text=body * 3)
    store = make_store([fetch_obs("https://example.com/p", html)])

    assert de.check_e_answer_01(store) == [], f"healthy {script} page reported as a mismatch"


def test_e_answer_01_still_fires_on_a_genuine_non_ascii_mismatch():
    # The cross-script fix must not blind the check: a Greek title about
    # bearings over a Greek body about holiday opening hours is still a miss.
    html = page_html(
        title="Ρουλεμάν ακριβείας για μηχανουργεία",
        h1="Εορταστικές ώρες λειτουργίας",
        body_text="Οι εορταστικές ώρες λειτουργίας των καταστημάτων ανακοινώνονται κάθε Δεκέμβριο. "
                  "Τα καταστήματα παραμένουν κλειστά τις αργίες και ανοίγουν ξανά τον Ιανουάριο. " * 4,
    )
    store = make_store([fetch_obs("https://example.com/p", html)])

    findings = de.check_e_answer_01(store)
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_e_answer_02_fires_on_visible_modal():
    html = f'<html><body><div role="dialog" class="newsletter-modal">Subscribe!</div><p>{LOREM}</p></body></html>'
    store = make_store([fetch_obs("https://example.com/", html), render_obs("https://example.com/", html)])

    findings = de.check_e_answer_02(store)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert_finding_shape(findings[0])


def test_e_answer_02_never_fires_without_render():
    html = f'<html><body><div role="dialog" class="newsletter-modal">Subscribe!</div><p>{LOREM}</p></body></html>'
    store = make_store([fetch_obs("https://example.com/", html)])

    assert de.check_e_answer_02(store) == []


def test_e_answer_02_never_fires_on_compliant_cookie_banner():
    html = f'<html><body><div class="cookie-banner">We use cookies.</div><p>{LOREM}</p></body></html>'
    store = make_store([fetch_obs("https://example.com/", html), render_obs("https://example.com/", html)])

    assert de.check_e_answer_02(store) == []


def test_e_answer_02_never_fires_on_hidden_modal():
    html = f'<html><body><div role="dialog" class="newsletter-modal" hidden>Subscribe!</div><p>{LOREM}</p></body></html>'
    store = make_store([fetch_obs("https://example.com/", html), render_obs("https://example.com/", html)])

    assert de.check_e_answer_02(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-ANSWER-03
# ---------------------------------------------------------------------------


def test_e_answer_03_fires_on_paywall_with_substantive_content():
    html = f'<html><body><p>{LOREM}</p><div class="paywall">Subscribe to continue reading</div></body></html>'
    store = make_store([fetch_obs("https://example.com/article", html), render_obs("https://example.com/article", html)])

    findings = de.check_e_answer_03(store)
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_e_answer_03_never_fires_without_render():
    html = f'<html><body><p>{LOREM}</p><div class="paywall">Subscribe to continue reading</div></body></html>'
    store = make_store([fetch_obs("https://example.com/article", html)])

    assert de.check_e_answer_03(store) == []


def test_e_answer_03_never_fires_on_honest_short_preview():
    html = '<html><body><p>Short preview.</p><div class="paywall">Subscribe to continue reading</div></body></html>'
    store = make_store([fetch_obs("https://example.com/article", html), render_obs("https://example.com/article", html)])

    assert de.check_e_answer_03(store) == []


def test_e_answer_03_never_fires_without_a_gate():
    html = f"<html><body><p>{LOREM}</p></body></html>"
    store = make_store([fetch_obs("https://example.com/article", html), render_obs("https://example.com/article", html)])

    assert de.check_e_answer_03(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-ANSWER-04
# ---------------------------------------------------------------------------


def test_e_answer_04_fires_when_answer_is_deep_below_fold():
    filler = "Filler word here. " * 100
    html = f"<html><body><p>{filler}The answer is forty two.</p></body></html>"
    store = make_store(
        [
            fetch_obs("https://example.com/faq", html),
            render_obs("https://example.com/faq", html),
            probe_obs("https://example.com/faq", [any_q("q1", True, "The answer is forty two")]),
        ]
    )

    findings = de.check_e_answer_04(store)
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_e_answer_04_fires_when_answer_is_in_collapsed_region():
    """Answer text placed near the top (low scroll-depth fraction) so the
    ONLY reason this fires is the collapsed region, isolating that path from
    the separate scroll-depth trigger tested above."""
    html = '<html><body><div aria-expanded="false">The answer is forty two.</div></body></html>'
    store = make_store(
        [
            fetch_obs("https://example.com/faq", html),
            render_obs("https://example.com/faq", html),
            probe_obs("https://example.com/faq", [any_q("q1", True, "The answer is forty two")]),
        ]
    )

    findings = de.check_e_answer_04(store)
    assert len(findings) == 1
    assert "collapsed" in findings[0]["observed_signal"]


def test_e_answer_04_never_fires_when_answer_is_near_top():
    filler = "Filler word here. " * 100
    html = f"<html><body><p>The answer is forty two. {filler}</p></body></html>"
    store = make_store(
        [
            fetch_obs("https://example.com/faq", html),
            render_obs("https://example.com/faq", html),
            probe_obs("https://example.com/faq", [any_q("q1", True, "The answer is forty two")]),
        ]
    )

    assert de.check_e_answer_04(store) == []


def test_e_answer_04_never_fires_without_render():
    filler = "Filler word here. " * 100
    html = f"<html><body><p>{filler}The answer is forty two.</p></body></html>"
    store = make_store(
        [
            fetch_obs("https://example.com/faq", html),
            probe_obs("https://example.com/faq", [any_q("q1", True, "The answer is forty two")]),
        ]
    )

    assert de.check_e_answer_04(store) == []


def test_e_answer_04_never_fires_without_probe():
    filler = "Filler word here. " * 100
    html = f"<html><body><p>{filler}The answer is forty two.</p></body></html>"
    store = make_store([fetch_obs("https://example.com/faq", html), render_obs("https://example.com/faq", html)])

    assert de.check_e_answer_04(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-CONTINUE-01 / E-CONTINUE-02
# ---------------------------------------------------------------------------


def test_e_continue_02_fires_on_true_dead_end():
    # A second, unrelated page exists in the crawl so this isn't a genuinely
    # single-page site (which E-CONTINUE-02 exempts entirely -- see the
    # single-page-site regression test below).
    html = page_html(title="Post", body_text=LOREM)
    other = page_html(title="Other", body_extra='<a href="/blog/post">Post</a>', body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/blog/post", html), fetch_obs("https://example.com/blog/other", other)])

    findings = de.check_e_continue_02(store)
    hits = [f for f in findings if f["source_urls"][0] == "https://example.com/blog/post"]
    assert len(hits) == 1
    assert_finding_shape(hits[0])


# E-CONTINUE-02 asks whether a visitor has anywhere to go, not whether the
# prose happens to link there. Standing navigation is a real continuation path:
# brochure, documentation and catalogue sites routinely keep their whole
# internal link graph in a <nav> and nowhere else, and reporting each of those
# pages as a dead end is a false positive on healthy, conventional markup.

def nav_page(nav_html, body_text=None):
    return page_html(title="Page", body_text=body_text or LOREM, body_extra=nav_html)


def two_page_store(html, other_html=None):
    other = other_html or page_html(title="Other", body_extra='<a href="/b">B</a>', body_text=LOREM)
    return make_store([
        fetch_obs("https://example.com/a", html),
        fetch_obs("https://example.com/other", other),
    ])


def continue_02_hits(store, url="https://example.com/a"):
    return [f for f in de.check_e_continue_02(store) if f["source_urls"][0] == url]


# -- A: healthy brochure page, internal links only in <nav> ------------------

def test_e_continue_02_does_not_fire_on_a_brochure_page_with_nav_only_links():
    html = nav_page('<nav><a href="/">Home</a><a href="/services">Services</a>'
                    '<a href="/contact">Contact</a></nav>')
    assert continue_02_hits(two_page_store(html)) == []


@pytest.mark.parametrize("region", ["header", "footer"], ids=["header", "footer"])
def test_e_continue_02_accepts_continuation_from_header_or_footer(region):
    html = nav_page(f'<{region}><a href="/services">Services</a>'
                    f'<a href="/pricing">Pricing</a></{region}>')
    assert continue_02_hits(two_page_store(html)) == []


def test_e_continue_02_accepts_the_aria_spelling_of_navigation():
    # Generated markup often uses role="navigation" rather than <nav>.
    html = nav_page('<div role="navigation"><a href="/docs">Docs</a>'
                    '<a href="/support">Support</a></div>')
    assert continue_02_hits(two_page_store(html)) == []


# -- B: documentation page with a sidebar nav -------------------------------

def test_e_continue_02_does_not_fire_on_a_docs_page_with_a_sidebar_nav():
    html = nav_page(
        '<nav class="sidebar"><a href="/docs/install">Install</a>'
        '<a href="/docs/config">Configure</a><a href="/docs/api">API</a></nav>',
        body_text="Rate limits are enforced per API key. " + LOREM,
    )
    assert continue_02_hits(two_page_store(html)) == []


# -- C: a genuine dead end still fires --------------------------------------

def test_e_continue_02_still_fires_on_a_true_dead_end_with_no_navigation():
    assert len(continue_02_hits(two_page_store(nav_page("")))) == 1


def test_e_continue_02_still_fires_when_navigation_only_returns_home():
    # One destination is not continuation: it sends the visitor back to the
    # start rather than onward.
    html = nav_page('<nav><a href="/">Home</a></nav>')
    hits = continue_02_hits(two_page_store(html))
    assert len(hits) == 1
    assert_finding_shape(hits[0])


# -- D: malformed or empty navigation must not suppress ---------------------

@pytest.mark.parametrize("nav_html,reason", [
    ("<nav></nav>", "empty nav element"),
    ('<nav><a>Services</a><a>Pricing</a></nav>', "anchors carrying no href"),
    ('<nav><a href="">Services</a><a href="#">Pricing</a></nav>', "empty and fragment-only hrefs"),
    ('<nav><a href="#top">Top</a><a href="#end">End</a></nav>', "same-page anchors only"),
    ('<nav><a href="/a">This page</a><a href="/a#section">This page again</a></nav>',
     "links only back to the page itself"),
], ids=["empty", "no-href", "empty-href", "fragments", "self-links"])
def test_malformed_navigation_does_not_suppress_the_finding(nav_html, reason):
    hits = continue_02_hits(two_page_store(nav_page(nav_html)))
    assert len(hits) == 1, f"{reason} is not a continuation path"


# -- E: navigation that leaves the site must not suppress -------------------

def test_external_only_navigation_does_not_suppress_the_finding():
    html = nav_page('<nav><a href="https://partner.example/x">Partner</a>'
                    '<a href="https://other.example/y">Other</a>'
                    '<a href="mailto:hi@example.com">Mail</a></nav>')
    hits = continue_02_hits(two_page_store(html))
    assert len(hits) == 1, "leaving the site is not continuing into it"


def test_navigation_destinations_counts_only_real_internal_destinations():
    from _engagement_util import navigation_destinations
    html = ('<body><nav><a href="/a">self</a><a href="/b">b</a><a href="/b#x">b again</a>'
            '<a href="https://other.example/z">external</a><a href="#top">anchor</a>'
            '<a href="/c">c</a></nav></body>')
    # /a is the page itself, /b and /b#x are one destination, external and
    # fragment links are not destinations at all.
    assert navigation_destinations(html, "https://example.com/a") == [
        "https://example.com/b", "https://example.com/c"]


def test_e_continue_01_fires_when_only_social_links_present():
    html = page_html(title="Post", body_extra='<a href="mailto:x@example.com">Email</a>', body_text=LOREM)
    other = page_html(title="Other", body_extra='<a href="/blog/post">Post</a>', body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/blog/post", html), fetch_obs("https://example.com/blog/other", other)])

    findings = [f for f in de.check_e_continue_01(store) if f["source_urls"][0] == "https://example.com/blog/post"]
    assert len(findings) == 1
    assert_finding_shape(findings[0])
    # a dead end (E-CONTINUE-02) must not ALSO fire for this page since a link exists
    assert [f for f in de.check_e_continue_02(store) if f["source_urls"][0] == "https://example.com/blog/post"] == []


def test_e_continue_01_never_fires_with_genuine_internal_link():
    html = page_html(title="Post", body_extra='<a href="/blog/related">Related post</a>', body_text=LOREM)
    # "related" also links onward so it doesn't independently dead-end and
    # muddy the assertion below with an unrelated E-CONTINUE-02 finding of its own.
    related = page_html(title="Related", body_extra='<a href="/blog/post">Back</a>', body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/post", html),
            fetch_obs("https://example.com/blog/related", related),
        ]
    )

    assert by_check(de.check_e_continue_01(store), "E-CONTINUE-01") == []
    assert [f for f in de.check_e_continue_02(store) if f["source_urls"][0] == "https://example.com/blog/post"] == []


def test_e_continue_01_and_02_never_fire_on_terminal_pages():
    html = page_html(title="Contact", body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/contact", html),
            classification_obs("https://example.com/contact", "contact"),
        ]
    )

    assert de.check_e_continue_01(store) == []
    assert de.check_e_continue_02(store) == []


def test_e_continue_01_never_fires_when_probe_confirms_a_next_step():
    url = "https://example.com/blog/post"
    html = page_html(title="Post", body_extra='<a href="mailto:x@example.com">Email</a>', body_text=LOREM)
    store = make_store(
        [
            fetch_obs(url, html),
            probe_obs(url, [engagement_q("Q8", True, answer="Contact us by email for more information")]),
        ]
    )

    assert de.check_e_continue_01(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-CONTINUE-03
# ---------------------------------------------------------------------------


def test_e_continue_03_fires_when_hub_exists_but_not_linked():
    deep = page_html(title="Post", body_text=LOREM)
    hub = page_html(title="Blog", body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/post", deep),
            fetch_obs("https://example.com/blog/", hub),
        ]
    )

    findings = de.check_e_continue_03(store)
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_e_continue_03_never_fires_when_hub_not_crawled():
    deep = page_html(title="Post", body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/blog/post", deep)])

    assert de.check_e_continue_03(store) == []


def test_e_continue_03_never_fires_when_hub_is_linked():
    deep = page_html(title="Post", body_extra='<a href="/blog/">Back to Blog</a>', body_text=LOREM)
    hub = page_html(title="Blog", body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/post", deep),
            fetch_obs("https://example.com/blog/", hub),
        ]
    )

    assert de.check_e_continue_03(store) == []


# ---------------------------------------------------------------------------
# Unit tests -- E-CONTINUE-04
# ---------------------------------------------------------------------------


def test_e_continue_04_fires_on_broken_internal_link():
    html = page_html(title="Post", body_extra='<a href="/blog/gone">Gone</a>', body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/post", html),
            fetch_obs("https://example.com/blog/gone", "<html></html>", status_code=404),
        ]
    )

    findings = de.check_e_continue_04(store)
    assert len(findings) == 1
    assert_finding_shape(findings[0])


def test_e_continue_04_never_fires_when_target_not_crawled():
    html = page_html(title="Post", body_extra='<a href="/blog/uncrawled">Link</a>', body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/blog/post", html)])

    assert de.check_e_continue_04(store) == []


def test_e_continue_04_never_fires_when_target_is_healthy():
    html = page_html(title="Post", body_extra='<a href="/blog/other">Other</a>', body_text=LOREM)
    other = page_html(title="Other", body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/blog/post", html),
            fetch_obs("https://example.com/blog/other", other),
        ]
    )

    assert de.check_e_continue_04(store) == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_single_page_site_deep_page_checks_stay_quiet():
    """A single-page site has no depth-2 pages at all -- E-ORIENT-01/03,
    E-CONTINUE-03 all have nothing to evaluate and must not fabricate findings."""
    html = page_html(title="Acme", body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/", html)], archetype="personal-portfolio")

    findings = de.detect_engagement(store, ENTITY_PROFILE)
    assert by_check(findings, "E-ORIENT-01") == []
    assert by_check(findings, "E-ORIENT-03") == []
    assert by_check(findings, "E-CONTINUE-03") == []


def test_edge_render_unavailable_render_only_checks_stay_silent():
    """No RENDER observations anywhere -- E-ANSWER-02/03/04 must never
    approximate first-paint state from raw HTML."""
    html = f'<html><body><div role="dialog" class="newsletter-modal">Sub</div><p>{LOREM}</p></body></html>'
    store = make_store([fetch_obs("https://example.com/", html)])

    findings = de.detect_engagement(store, ENTITY_PROFILE)
    assert by_check(findings, "E-ANSWER-02") == []
    assert by_check(findings, "E-ANSWER-03") == []
    assert by_check(findings, "E-ANSWER-04") == []


def test_edge_never_flags_short_page_with_no_cta():
    """Explicit brief requirement: short pages / no CTA where none is
    appropriate must never be flagged by any check."""
    html = page_html(title="Acme - Contact", body_text="Call us at 555-0100.")
    store = make_store(
        [
            fetch_obs("https://example.com/contact", html),
            classification_obs("https://example.com/contact", "contact"),
        ]
    )

    findings = de.detect_engagement(store, ENTITY_PROFILE)
    assert findings == []


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("archetype", ["brand-product", "ecommerce", "institutional"])
def test_regression_clean_site_yields_no_findings(archetype):
    home = page_html(title="Acme", body_extra='<a href="/blog/">Blog</a>', body_text="Acme builds developer tools. " + LOREM)
    hub_html = page_html(
        title="Acme - Blog",
        jsonld={"@type": "BreadcrumbList", "itemListElement": []},
        body_extra='<a href="/">Home</a> <a href="/blog/2024/post">Latest post</a>',
        body_text="Acme's blog. " + LOREM,
    )
    deep_html = page_html(
        title="Latest Post - Acme",
        jsonld={"@type": "BreadcrumbList", "itemListElement": []},
        body_extra='<a href="/blog/">Back to Blog</a> <a href="/blog/2024/other">Another post</a>',
        body_text="Acme's latest post covers new features. " + LOREM,
    )
    other_html = page_html(
        title="Other Post - Acme",
        jsonld={"@type": "BreadcrumbList", "itemListElement": []},
        body_extra='<a href="/blog/">Back to Blog</a> <a href="/blog/2024/post">Latest post</a>',
        body_text="Another Acme post. " + LOREM,
    )

    observations = [
        fetch_obs("https://example.com/", home),
        render_obs("https://example.com/", home),
        fetch_obs("https://example.com/blog/", hub_html),
        render_obs("https://example.com/blog/", hub_html),
        fetch_obs("https://example.com/blog/2024/post", deep_html),
        render_obs("https://example.com/blog/2024/post", deep_html),
        fetch_obs("https://example.com/blog/2024/other", other_html),
        render_obs("https://example.com/blog/2024/other", other_html),
    ]
    store = make_store(observations, archetype=archetype)

    findings = de.detect_engagement(store, ENTITY_PROFILE)
    assert findings == []


# ---------------------------------------------------------------------------
# Hostile-review regression tests
# ---------------------------------------------------------------------------


def test_hostile_01_single_page_saas_site_never_flagged_dead_end():
    """An excellent, minimalist one-page site (in-page anchor nav + an
    external booking CTA) has nowhere 'deeper' to go by design -- must never
    fire E-CONTINUE-01/02, which used to flag it purely for being one page."""
    html = f"""<html><head><title>Acme</title></head><body>
    <h1>Acme</h1><nav><a href="#features">Features</a></nav>
    <section id="features">{LOREM}</section>
    <a href="https://calendly.com/acme/demo">Book a demo</a>
    </body></html>"""
    store = make_store([fetch_obs("https://example.com/", html)])

    findings = de.detect_engagement(store, ENTITY_PROFILE)
    assert by_check(findings, "E-CONTINUE-01") == []
    assert by_check(findings, "E-CONTINUE-02") == []


def test_hostile_01b_real_multi_page_dead_end_still_fires():
    """Companion: the single-page exemption must not swallow a genuine
    dead end on a site that has other pages."""
    dead_end = page_html(title="Post", body_text=LOREM)
    other = page_html(title="Other", body_extra='<a href="/post">Post</a>', body_text=LOREM)
    store = make_store([fetch_obs("https://example.com/post", dead_end), fetch_obs("https://example.com/other", other)])

    findings = de.check_e_continue_02(store)
    assert [f for f in findings if f["source_urls"][0] == "https://example.com/post"] != []


def test_hostile_02_modal_trigger_button_never_flagged_as_blocking_overlay():
    """A harmless, visible trigger button that opens a properly-hidden
    dialog must never be mistaken for the blocking dialog itself -- lightbox/
    video-modal trigger buttons are near-ubiquitous on real sites."""
    html = f'<html><body><button class="modal-trigger-btn">Watch demo</button><div class="video-modal" hidden></div><p>{LOREM}</p></body></html>'
    store = make_store([fetch_obs("https://example.com/", html), render_obs("https://example.com/", html)])

    assert de.check_e_answer_02(store) == []


def test_hostile_02b_genuine_visible_modal_still_fires():
    """Companion: a real, visible-by-default modal container must still fire."""
    html = f'<html><body><div role="dialog" class="newsletter-modal">Subscribe!</div><p>{LOREM}</p></body></html>'
    store = make_store([fetch_obs("https://example.com/", html), render_obs("https://example.com/", html)])

    assert len(de.check_e_answer_02(store)) == 1


def test_hostile_03_same_organization_subdomain_counts_as_next_step():
    """The marketing-site -> app-subdomain CTA (app.acme.com from acme.com)
    is a near-universal SaaS pattern and must count as a genuine next step,
    not 'external'."""
    home = page_html(title="Acme", body_extra='<a href="https://app.acme.com/signup">Sign up</a>', body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://acme.com/", home),
            fetch_obs("https://acme.com/other", page_html(title="Other", body_extra='<a href="https://acme.com/">Home</a>', body_text=LOREM)),
        ]
    )

    assert de.check_e_continue_01(store) == []
    assert de.check_e_continue_02(store) == []


def test_hostile_03b_genuinely_external_link_does_not_count():
    """Companion: an unrelated third-party domain must still classify
    'external', not be treated as a next step."""
    link = {"href": "https://twitter.com/acme", "text": "Follow us", "rel": []}
    assert eu.classify_link(link, "https://acme.com/") == "external"


def test_hostile_04_landing_page_classification_exempts_no_next_step_checks():
    """A campaign landing page, classified as such, intentionally minimizes
    navigation as a conversion-optimization best practice -- must not fire
    E-CONTINUE-01/02/E-ORIENT-03 merely for having no breadcrumb or links."""
    deep = page_html(title="Summer Sale - Acme", body_text=LOREM)
    other_deep = page_html(title="Other", body_text=LOREM)
    store = make_store(
        [
            fetch_obs("https://example.com/campaigns/summer/sale", deep),
            fetch_obs("https://example.com/campaigns/summer/other", other_deep),
            classification_obs("https://example.com/campaigns/summer/sale", "landing_page"),
        ]
    )

    findings = de.detect_engagement(store)
    assert [f for f in findings if f["source_urls"][0] == "https://example.com/campaigns/summer/sale"] == []


def test_hostile_05_probe_question_missing_relevant_key_never_fires():
    """A PROBE question with no explicit relevant:true must never be treated
    as fair game for a citation-landing-mismatch finding -- an unset field is
    not evidence of relevance."""
    filler = "Filler word here. " * 100
    html = f"<html><body><p>{filler}The answer is forty two.</p></body></html>"
    store = make_store(
        [
            fetch_obs("https://example.com/faq", html),
            render_obs("https://example.com/faq", html),
            probe_obs("https://example.com/faq", [{"id": "q1", "category": "factual", "answered": True, "evidence_span": "The answer is forty two"}]),
        ]
    )

    assert de.check_e_answer_04(store) == []


def test_hostile_06_long_page_with_anchor_nav_to_answer_never_flagged():
    """A long, single-page site with a sticky nav that jumps directly to the
    answer's section is a deliberate, well-regarded structure -- must not be
    penalized purely for the answer sitting far down the raw character count."""
    filler = "Filler word here. " * 100
    html = (
        '<html><body><nav><a href="#pricing">Pricing</a></nav>'
        f"<h1>Home</h1><p>{filler}</p>"
        '<section id="pricing">The price is forty two dollars.</section></body></html>'
    )
    store = make_store(
        [
            fetch_obs("https://example.com/", html),
            render_obs("https://example.com/", html),
            probe_obs("https://example.com/", [any_q("q1", True, "The price is forty two dollars")]),
        ]
    )

    assert de.check_e_answer_04(store) == []


def test_hostile_06b_long_page_without_anchor_nav_still_fires():
    """Companion: the anchor-nav exemption must not swallow a genuinely
    buried answer with no navigational aid at all."""
    filler = "Filler word here. " * 100
    html = f'<html><body><h1>Home</h1><p>{filler}</p><section id="pricing">The price is forty two dollars.</section></body></html>'
    store = make_store(
        [
            fetch_obs("https://example.com/", html),
            render_obs("https://example.com/", html),
            probe_obs("https://example.com/", [any_q("q1", True, "The price is forty two dollars")]),
        ]
    )

    assert len(de.check_e_answer_04(store)) == 1
