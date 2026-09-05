import json

import pytest

from lib.common.extract import (
    compare_raw_vs_rendered,
    extract_canonical_url,
    extract_jsonld,
    extract_links,
    extract_metadata,
    extract_text,
    normalize_schema_type,
    page_inventory,
    schema_type_matches,
)
from lib.common import http_client
from lib.common.http_client import fetch_url, resolve_redirect_chain
from lib.common.observations import ObservationStore, make_observation
from lib.common.robots import fetch_robots, parse_robots, robots_allows
from lib.site_observer.render import detect_capability, render_page


def test_schema_type_normalization_does_not_conflate_foreign_vocabularies():
    assert not schema_type_matches("https://example.org/Organization", "Organization")
    assert not schema_type_matches("custom:Product", "Product")
    assert schema_type_matches("https://schema.org/Product", "Product")


class DummyResponse:
    def __init__(self, *, url, status_code=200, text="", headers=None, history=None, encoding="utf-8"):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.history = history or []
        self.encoding = encoding
        self.content = text.encode(encoding)


def test_fetch_url_collects_http_evidence(monkeypatch):
    def fake_get(url, timeout=10):
        return DummyResponse(
            url=url,
            status_code=200,
            text='<html><head><title>Example</title></head><body><h1>Hello</h1></body></html>',
            headers={"content-type": "text/html; charset=utf-8"},
        )

    monkeypatch.setattr(http_client, "request_once", fake_get)

    from lib.common.network_policy import RequestPolicy
    policy = RequestPolicy("https://example.com")
    policy.robots = {"status": "missing"}
    result = fetch_url("https://example.com", policy=policy)

    assert result["status_code"] == 200
    assert result["final_url"] == "https://example.com"
    assert result["redirect_chain"] == []
    assert result["evidence"]["status"] == "ok"
    assert result["evidence"]["content_type"] == "text/html; charset=utf-8"


def test_resolve_redirect_chain_handles_multiple_hops():
    history = [
        DummyResponse(url="https://example.com/old", status_code=301, headers={"location": "https://example.com/new"}),
        DummyResponse(url="https://example.com/new", status_code=302, headers={"location": "https://example.com/final"}),
    ]

    chain = resolve_redirect_chain(history)

    assert chain == [
        {"from": "https://example.com/old", "to": "https://example.com/new", "status": 301},
        {"from": "https://example.com/new", "to": "https://example.com/final", "status": 302},
    ]


def test_fetch_robots_parses_permissions(monkeypatch):
    def fake_get(url, timeout=10):
        if url.endswith("/robots.txt"):
            return DummyResponse(
                url=url,
                status_code=200,
                text="User-agent: *\nDisallow: /private\nAllow: /public\nSitemap: https://example.com/sitemap.xml\n",
            )
        raise AssertionError("unexpected URL")

    monkeypatch.setattr("lib.common.robots.request_once", fake_get)

    robots = fetch_robots("https://example.com")

    assert robots["status"] == "ok"
    assert robots["allow_all"] is False
    assert robots["document"]["sitemap"] == ["https://example.com/sitemap.xml"]
    assert robots_allows(robots, "/public") is True
    assert robots_allows(robots, "/private") is False


def test_parse_robots_handles_missing_and_unparseable_text():
    missing = parse_robots("")
    assert missing["status"] == "missing"
    assert missing["allow_all"] is True

    unparseable = parse_robots("this is not robots")
    assert unparseable["status"] == "unparseable"
    assert unparseable["allow_all"] is False


def test_extract_canonical_metadata_jsonld_and_links():
    html = """
    <html>
      <head>
        <title>Example title</title>
        <meta name="description" content="Example description">
        <meta property="og:title" content="Example social title">
        <link rel="canonical" href="https://example.com/canonical/page">
        <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"WebPage","name":"Example page","url":"https://example.com/canonical/page"}
        </script>
      </head>
      <body>
        <a href="/about">About</a>
        <a href="https://example.com/contact">Contact</a>
        <div>Visible content text here.</div>
      </body>
    </html>
    """

    canonical = extract_canonical_url(html, "https://example.com/start")
    meta = extract_metadata(html)
    jsonld = extract_jsonld(html)
    links = extract_links(html, base_url="https://example.com/start")
    text = extract_text(html)

    assert canonical == "https://example.com/canonical/page"
    assert meta["title"] == "Example title"
    assert meta["description"] == "Example description"
    assert jsonld[0]["@type"] == "WebPage"
    assert [link["href"] for link in links] == ["https://example.com/about", "https://example.com/contact"]
    assert "Visible content text here." in text


def test_extract_jsonld_flattens_containers_and_normalizes_type_uris():
    html = """
    <script type="Application/LD+JSON; charset=UTF-8">
      {
        "@context": "https://schema.org",
        "@graph": [
          {"@type": "https://schema.org/Organization", "name": "Northstar"},
          {"@list": [
            {"@type": ["schema:Product", "https://schema.org/Thing"], "name": "Compass"}
          ]}
        ]
      }
    </script>
    <script type="application/javascript">{"@type": "Event"}</script>
    """

    nodes = extract_jsonld(html)

    assert [node["name"] for node in nodes] == ["Northstar", "Compass"]
    assert normalize_schema_type(nodes[0]["@type"]) == "Organization"
    assert schema_type_matches(nodes[1]["@type"], "Product")
    assert schema_type_matches(nodes[1]["@type"], "https://schema.org/Thing")


def test_page_inventory_and_raw_rendered_comparison_include_evidence():
    raw_html = "<html><body><h1>Page</h1><a href='/a'>A</a><img src='/img.png'><script>var x = 1;</script></body></html>"
    rendered_html = "<html><body><h1>Page</h1><a href='/a'>A</a><img src='/img.png'></body></html>"

    inventory = page_inventory(raw_html)
    comparison = compare_raw_vs_rendered(raw_html, rendered_html)

    assert inventory["link_count"] == 1
    assert inventory["image_count"] == 1
    assert inventory["script_count"] == 1
    assert comparison["evidence"]["raw_only_nodes"] == ["script"]
    assert comparison["evidence"]["rendered_only_nodes"] == []


def test_observation_store_generates_stable_ids_and_resolves_evidence():
    store = ObservationStore()
    obs = make_observation(
        "HTTP_FETCH",
        "https://example.com",
        {
            "status_code": 200,
            "final_url": "https://example.com",
            "redirect_chain": [],
            "evidence": {"status": "ok"},
        },
    )

    store.add(obs)

    assert obs["id"].startswith("OBS-HTTP-FETCH-")
    assert store.resolve(obs["id"]) == obs
    assert store.resolve("OBS-HTTP-FETCH-0000000000000000") is None


def test_observation_ids_include_type_and_source_url_in_identity():
    value = {"status_code": 200, "html": "<p>Shared template</p>"}
    first = make_observation("HTTP_FETCH", "https://example.com/one", value)
    first_again = make_observation("HTTP_FETCH", "https://example.com/one", value)
    second = make_observation("HTTP_FETCH", "https://example.com/two", value)
    normalized_type_collision = make_observation("HTTP-FETCH", "https://example.com/one", value)

    assert first["id"] == first_again["id"]
    assert first["id"] != second["id"]
    assert first["id"] != normalized_type_collision["id"]

    store = ObservationStore()
    store.add(first)
    store.add(second)
    assert len(store.all()) == 2
    assert store.resolve(first["id"])["source_url"].endswith("/one")
    assert store.resolve(second["id"])["source_url"].endswith("/two")


def test_detect_capability_reports_unavailable_when_playwright_not_installed(monkeypatch):
    monkeypatch.setattr("lib.site_observer.render.importlib.util.find_spec", lambda name: None)

    capability = detect_capability()

    assert capability == {"available": False, "reason": "PLAYWRIGHT_NOT_INSTALLED"}


def test_render_page_records_coverage_gap_when_capability_unavailable():
    result = render_page("https://example.com", capability={"available": False, "reason": "PLAYWRIGHT_NOT_INSTALLED"})

    assert result["status"] == "unavailable"
    assert result["html"] == ""
    assert result["final_url"] == "https://example.com"
    assert result["evidence"] == {
        "status": "coverage_gap",
        "check_id": "X-COV-01",
        "reason": "PLAYWRIGHT_NOT_INSTALLED",
    }


def test_render_page_returns_rendered_html_when_capability_available(monkeypatch):
    def fake_render(url, timeout_ms, policy=None):
        return {
            "html": "<html><body><h1>Rendered</h1></body></html>",
            "final_url": "https://example.com/",
            "status_code": 200,
        }

    monkeypatch.setattr("lib.site_observer.render._render_with_playwright", fake_render)

    result = render_page("https://example.com", capability={"available": True, "reason": None})

    assert result["status"] == "ok"
    assert result["status_code"] == 200
    assert result["final_url"] == "https://example.com/"
    assert "<h1>Rendered</h1>" in result["html"]
    assert result["evidence"]["status"] == "ok"


def test_render_page_reports_error_without_raising_when_render_fails(monkeypatch):
    def fake_render(url, timeout_ms, policy=None):
        raise TimeoutError("navigation timed out")

    monkeypatch.setattr("lib.site_observer.render._render_with_playwright", fake_render)

    result = render_page("https://example.com", capability={"available": True, "reason": None})

    assert result["status"] == "error"
    assert result["html"] == ""
    assert "navigation timed out" in result["evidence"]["error"]


def test_raw_vs_rendered_pipeline_flags_render_only_content():
    raw_html = "<html><body><h1>Shell</h1></body></html>"

    render_result = render_page(
        "https://example.com",
        capability={"available": False, "reason": "PLAYWRIGHT_NOT_INSTALLED"},
    )
    assert render_result["status"] == "unavailable"

    rendered_html = "<html><body><h1>Shell</h1><p>Full article text.</p></body></html>"
    comparison = compare_raw_vs_rendered(raw_html, rendered_html)

    assert comparison["evidence"]["rendered_only_nodes"] == ["p"]


# ---------------------------------------------------------------------------
# Cross-script generalization: decoding and tokenization
# ---------------------------------------------------------------------------
#
# Every text-based check reads whatever these two produce. When they assume
# ASCII, the assumption does not fail loudly on an unseen non-Latin site -- it
# quietly corrupts or empties the input and the checks draw conclusions from
# the wreckage. The scripts below are deliberately structurally different from
# each other: accented Latin, a non-Latin alphabet, and a script with no word
# spaces at all.

GREEK = "Ρουλεμάν ακριβείας για μηχανουργεία"
JAPANESE = "機械工場向けの精密ベアリング"
FRENCH = "Roulements de précision pour ateliers"


@pytest.mark.parametrize("declaration,body_prefix", [
    ("text/html; charset=utf-8", b""),                       # transport declares it
    ("text/html", b'<meta charset="utf-8">'),                # only the document declares it
    ("text/html", b'<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">'),
    ("text/html", b"\xef\xbb\xbf"),                          # only a byte-order mark
    ("text/html", b""),                                      # nothing declares it at all
], ids=["http-header", "meta-charset", "meta-http-equiv", "bom", "undeclared-utf8"])
def test_html_is_decoded_the_way_a_browser_decodes_it(declaration, body_prefix):
    # requests defaults text/* with no charset to ISO-8859-1, which turns every
    # non-ASCII page into mojibake. HTML5, and every browser, does not.
    body = body_prefix + f"<html><body><h1>{GREEK}</h1></body></html>".encode("utf-8")
    encoding = http_client.html_encoding({"Content-Type": declaration}, body)
    assert GREEK in body.decode(encoding)


def test_an_explicit_transport_charset_still_wins_over_the_document():
    body = b'<meta charset="utf-8">' + "caf\xe9".encode("latin-1")
    assert http_client.html_encoding({"Content-Type": "text/html; charset=iso-8859-1"}, body) == "iso-8859-1"


def test_genuinely_latin1_bytes_are_not_forced_to_utf8():
    assert http_client.html_encoding({"Content-Type": "text/html"}, b"caf\xe9") == "iso-8859-1"


@pytest.mark.parametrize("text", [GREEK, JAPANESE, FRENCH], ids=["greek", "japanese", "french"])
def test_identical_text_is_recognized_as_identical_in_any_script(text):
    from lib.common.extract import containment_ratio, significant_words
    # The ASCII-only tokenizer this replaced returned an empty set for Greek and
    # Japanese, so a page whose title exactly described its body scored 0.0 and
    # read as a mismatch.
    assert significant_words(text)
    assert containment_ratio(text, text) == 1.0


def test_accented_words_are_not_split_at_the_accent():
    from lib.common.extract import significant_words
    # "précision" came back as "cision" under [a-z0-9]+, silently corrupting
    # every overlap comparison on French, Spanish, German or Portuguese pages.
    assert "précision" in significant_words(FRENCH)
    assert "cision" not in significant_words(FRENCH)


def test_ascii_tokenization_is_unchanged_by_the_unicode_rewrite():
    from lib.common.extract import significant_words
    import re
    ascii_text = "Precision bearings for machine shops, next-day dispatch (stocked sizes only) 2026."
    previous = {w for w in re.findall(r"[a-z0-9]+", ascii_text.lower())
                if len(w) >= 4 and w not in {"a", "an", "the", "and", "or", "but", "of", "to", "for",
                                             "in", "on", "at", "is", "are", "was", "were", "with",
                                             "that", "this", "it", "as", "by", "be"}}
    assert significant_words(ascii_text) == previous


def test_word_thresholds_are_measurable_in_scripts_without_spaces():
    from lib.common.extract import text_weight
    # Splitting on whitespace scores any amount of Japanese prose as one word,
    # which puts every word-count threshold permanently out of reach for it.
    assert text_weight("one two three four five") == 5          # unchanged for spaced text
    assert text_weight(JAPANESE * 10) > 25
    assert text_weight(JAPANESE) < text_weight(JAPANESE * 10)   # monotonic, not a constant
